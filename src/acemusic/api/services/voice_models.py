"""Voice model service (US-25.1).

Validates reference recordings, charges for training, and records the model.
Transport-agnostic like the other service modules: it raises plain exceptions,
never ``HTTPException``.

The order of validation is the behaviour, not an implementation detail: the
musician is only charged once every check that can reject the request has
already passed, so a bad upload never costs credits.
"""

import asyncio
import io
import logging
import math
from dataclasses import dataclass

from beanie import PydanticObjectId

from acemusic.storage import StorageBackend, get_storage_backend

from ..models import Job, User, VoiceModel, VoiceModelStatus
from ..models.voice_model import (
    MAX_REFERENCE_BYTES,
    MAX_REFERENCE_FILES,
    MIN_REFERENCE_FILES,
    MIN_REFERENCE_SECONDS,
    MIN_SAMPLE_RATE_HZ,
)
from . import credits as credits_service

logger = logging.getLogger(__name__)


class VoiceModelError(Exception):
    """A reference set that cannot be trained on."""


class InsufficientCreditsError(Exception):
    """Not enough credits to start training."""

    def __init__(self, balance: float, required: float) -> None:
        super().__init__(f"Training needs {required} credits; balance is {balance}.")
        self.balance = balance
        self.required = required


@dataclass(frozen=True)
class ReferenceAudio:
    """One uploaded reference and what could be measured from it."""

    filename: str
    data: bytes
    sample_rate: int
    duration: float
    peak: float

    #: Coarse spectral fingerprint, used only for the consistency check below.
    centroid: float


def _probe_sync(filename: str, data: bytes) -> ReferenceAudio:
    """Decode ``data`` far enough to validate it.

    Raises :class:`VoiceModelError` naming the file, because "a file is invalid"
    is useless when ten were uploaded.
    """
    import numpy as np
    import soundfile as sf

    try:
        audio, sample_rate = sf.read(io.BytesIO(data), always_2d=True)
    except Exception as exc:
        # soundfile decodes wav/flac/ogg. An mp3 or a corrupt body lands here.
        raise VoiceModelError(
            f"{filename}: could not be read as audio. Upload WAV or FLAC at {MIN_SAMPLE_RATE_HZ} Hz or above."
        ) from exc

    if audio.size == 0:
        raise VoiceModelError(f"{filename}: contains no audio.")

    mono = audio.mean(axis=1)
    duration = len(mono) / float(sample_rate) if sample_rate else 0.0
    peak = float(np.max(np.abs(mono))) if mono.size else 0.0

    # Spectral centroid as a very coarse timbre fingerprint. See
    # check_consistency for what this is and is not.
    spectrum = np.abs(np.fft.rfft(mono * np.hanning(len(mono)))) if mono.size > 1 else np.zeros(1)
    freqs = np.fft.rfftfreq(len(mono), 1.0 / sample_rate) if mono.size > 1 else np.zeros(1)
    total = float(spectrum.sum())
    centroid = float((spectrum * freqs).sum() / total) if total > 0 else 0.0

    return ReferenceAudio(
        filename=filename,
        data=data,
        sample_rate=int(sample_rate),
        duration=duration,
        peak=peak,
        centroid=centroid if math.isfinite(centroid) else 0.0,
    )


def check_file_count(count: int) -> None:
    """Reject a reference set that is too small or too large, before reading anything."""
    uploaded = f"{count} was uploaded" if count == 1 else f"{count} were uploaded"

    if count < MIN_REFERENCE_FILES:
        raise VoiceModelError(f"Training needs at least {MIN_REFERENCE_FILES} reference files; {uploaded}.")
    if count > MAX_REFERENCE_FILES:
        raise VoiceModelError(f"Training takes at most {MAX_REFERENCE_FILES} reference files; {uploaded}.")


def check_reference(reference: ReferenceAudio) -> None:
    """Reject one reference that cannot usefully be trained on.

    Every message names the file, since the point is to tell the musician which
    recording to replace.
    """
    if reference.sample_rate < MIN_SAMPLE_RATE_HZ:
        raise VoiceModelError(
            f"{reference.filename}: sample rate is {reference.sample_rate} Hz, "
            f"below the {MIN_SAMPLE_RATE_HZ} Hz minimum."
        )

    if reference.duration < MIN_REFERENCE_SECONDS:
        raise VoiceModelError(
            f"{reference.filename}: is {reference.duration:.2f}s long, " f"below the {MIN_REFERENCE_SECONDS}s minimum."
        )

    # Silence trains nothing, and finding that out after ten minutes of GPU time
    # and 10 credits is a bad trade.
    if reference.peak < 0.01:
        raise VoiceModelError(f"{reference.filename}: is silent or almost silent.")


def check_consistency(references: list[ReferenceAudio]) -> None:
    """Reject a reference set whose files clearly are not the same source.

    **This is not speaker verification.** Comparing "similar vocal
    characteristics" properly needs speaker embeddings; this compares spectral
    centroids, which catches the mistake that actually happens — a drum loop or a
    backing track mixed in among the vocal takes — and will not catch two
    different people with similar timbre. The PR and the docs say so rather than
    implying otherwise.

    The threshold is deliberately loose: a false reject costs the musician a
    usable model, which is worse than training on one slightly odd take.
    """
    centroids = [r.centroid for r in references if r.centroid > 0]

    if len(centroids) < 2:
        return

    median = sorted(centroids)[len(centroids) // 2]

    if median <= 0:
        return

    for reference in references:
        if reference.centroid <= 0:
            continue
        # An octave-and-a-half either side of the median. Vocal takes vary; a
        # drum loop does not land anywhere near a voice.
        ratio = reference.centroid / median
        if ratio > 3.0 or ratio < (1 / 3.0):
            raise VoiceModelError(
                f"{reference.filename}: does not sound like the other references "
                f"(very different spectral balance). Remove it, or train it separately."
            )


async def validate_references(files: list[tuple[str, bytes]]) -> list[ReferenceAudio]:
    """Run every check, in the order that keeps a rejection free.

    Raises :class:`VoiceModelError` on the first problem, naming the file.
    """
    check_file_count(len(files))

    for filename, data in files:
        if len(data) > MAX_REFERENCE_BYTES:
            raise VoiceModelError(f"{filename}: exceeds the {MAX_REFERENCE_BYTES} byte limit for one reference.")

    # Decoding is CPU work; keep it off the event loop.
    references = await asyncio.gather(*(asyncio.to_thread(_probe_sync, filename, data) for filename, data in files))

    for reference in references:
        check_reference(reference)

    check_consistency(list(references))
    return list(references)


async def create_training_job(
    user_id: str,
    name: str,
    files: list[tuple[str, bytes]],
    *,
    description: str | None = None,
) -> tuple[VoiceModel, Job]:
    """Validate, charge, store, and queue a voice-training run.

    Nothing is charged or stored until validation passes, and if queueing fails
    after the charge the credits are refunded before the error propagates —
    otherwise a musician pays 10 credits for a job that never existed.
    """
    if not name or not name.strip():
        raise VoiceModelError("Give the voice model a name.")

    references = await validate_references(files)

    uid = PydanticObjectId(user_id)
    cost = credits_service.VOICE_TRAINING_COST

    deducted = await credits_service.deduct_credits(uid, cost)
    if deducted is None:
        user = await User.get(uid)
        raise InsufficientCreditsError(
            balance=user.credits_balance if user is not None else 0.0,
            required=cost,
        )

    model = VoiceModel(
        user_id=uid,
        name=name.strip(),
        description=(description or "").strip() or None,
        status=VoiceModelStatus.QUEUED,
        credits_charged=cost,
    )

    storage = get_storage_backend()

    try:
        await model.insert()
        model.reference_paths = await _store_references(storage, model, references)
        await model.save()

        job = Job(
            user_id=uid,
            # Voice training is account-scoped, not workspace-scoped: the model is
            # usable from every workspace. The field is required, so it carries the
            # model id to keep the record self-describing rather than a fake id.
            workspace_id=model.id,
            job_type="voice_training",
            input_params={
                "voice_model_id": str(model.id),
                "reference_count": len(references),
            },
        )
        await job.insert()

        model.job_id = job.id
        await model.save()

        # The ledger, not just the balance: /users/me/credits builds its history
        # from CreditTransaction, so without this the balance drops with no usage
        # row to explain it -- unlike every other billed endpoint.
        await credits_service.record_transaction(
            user_id=uid,
            amount=-cost,
            action_type="voice_training",
            job_id=str(job.id),
            balance_after=deducted,
        )
    except BaseException:
        # BaseException, not Exception: a shutdown CancelledError must also give
        # the credits back rather than leaving the musician charged for nothing.
        await credits_service.refund_credits(uid, cost)
        await _cleanup_partial(storage, model)
        raise

    return model, job


async def _store_references(storage: StorageBackend, model: VoiceModel, references: list[ReferenceAudio]) -> list[str]:
    """Upload the references and return their storage keys, in upload order."""
    paths: list[str] = []

    for index, reference in enumerate(references):
        suffix = reference.filename.rsplit(".", 1)[-1].lower() if "." in reference.filename else "wav"
        path = f"{model.user_id}/voice-models/{model.id}/ref-{index}.{suffix}"
        await asyncio.to_thread(storage.upload, path, reference.data)
        paths.append(path)

    return paths


async def _cleanup_partial(storage: StorageBackend, model: VoiceModel) -> None:
    """Best-effort removal of a half-created model's objects and record."""
    for path in model.reference_paths:
        try:
            await asyncio.to_thread(storage.delete, path)
        except Exception:  # pragma: no cover - cleanup is best-effort
            logger.exception("Failed to delete orphaned voice reference %s", path)

    try:
        if model.id is not None:
            await model.delete()
    except Exception:  # pragma: no cover
        logger.exception("Failed to delete partial voice model %s", model.id)


async def fail_training(model: VoiceModel, reason: str) -> VoiceModel:
    """Mark a model failed and refund what its training cost.

    The refund uses ``credits_charged`` rather than the current price, so a
    change to the cost table cannot alter what someone already paid gets back.
    """
    model.status = VoiceModelStatus.FAILED
    model.error = reason
    await model.save()

    if model.credits_charged > 0:
        await credits_service.refund_credits(model.user_id, model.credits_charged)

        user = await User.get(model.user_id)
        await credits_service.record_transaction(
            user_id=model.user_id,
            amount=model.credits_charged,
            action_type="voice_training_refund",
            job_id=str(model.job_id) if model.job_id else "",
            balance_after=user.credits_balance if user is not None else 0.0,
        )

    return model


async def list_voice_models(user_id: str) -> list[VoiceModel]:
    """Every voice model owned by ``user_id``, newest first."""
    uid = PydanticObjectId(user_id)
    models = await VoiceModel.find(VoiceModel.user_id == uid).to_list()
    models.sort(key=lambda m: m.created_at, reverse=True)
    return models


async def find_owned_model(model_id: str, user_id: str) -> VoiceModel | None:
    """A voice model, only if ``user_id`` owns it.

    Ownership is part of the query rather than a check afterwards, so there is no
    path that reads someone else's model at all.
    """
    try:
        oid = PydanticObjectId(model_id)
    except Exception:
        return None

    return await VoiceModel.find_one(VoiceModel.id == oid, VoiceModel.user_id == PydanticObjectId(user_id))
