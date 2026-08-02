"""Voice model training worker (US-25.1).

Drives ACE-Step's LoRA fine-tuning over its HTTP API:

    POST /v1/dataset/scan              (audio_dir)
    PUT  /v1/dataset/sample/{i}        (label each sample)
    POST /v1/dataset/preprocess_async  ->  poll /v1/dataset/preprocess_status
    POST /v1/training/start            ->  poll /v1/training/status
    POST /v1/training/export           ->  store the weights

**Scan and label are not optional.** Preprocessing operates on the server's
*current* dataset, and an unlabelled sample is skipped -- calling preprocess
without them returns "No labeled samples to preprocess" and produces nothing.
Auto-labelling goes through the LLM, which a memory-constrained ACE-Step host may
not have loaded, so each sample is labelled directly instead.

The payloads and the status vocabulary here are taken from ACE-Step's own
request models (``acestep/api/train_api_models.py``,
``train_api_dataset_models.py``) and from a live probe of the running server,
**not** from a guess. That distinction cost a rewrite: the first version of this
module invented ``{"dataset": ..., "name": ...}`` payloads and expected a
``"completed"``/``"failed"`` status string, and its stub tests passed because the
stub encoded the same guess. The real API takes ``tensor_dir`` and reports
``{"is_training": bool, "status": "Idle", "error": null}``.

**The references have to be materialised before ACE-Step can see them.** Uploads
live in the platform's storage backend, which may be S3; ACE-Step scans a
*directory*. So the worker downloads each reference into the shared training
directory first. Without that step every real job scans an empty directory,
finds nothing, and refunds -- the live verification of this module missed it
because the files had been copied there by hand.

**ACE-Step reads its own filesystem.** These endpoints take *paths*, not uploads,
and reject anything resolving outside the server's working directory
(``acestep/training/path_safety.py``). So voice training requires the platform and
ACE-Step to share a filesystem, and ``TRAINING_ROOT`` is deliberately relative so
it lands under that root. A split deployment needs a shared volume; there is no
upload endpoint to fall back on.

**Credits are refunded on every failure path**, including a cancellation during
shutdown. A musician who paid 10 credits for a run that produced nothing must not
stay charged, and that is the easiest thing here to get wrong.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import httpx

from acemusic.storage import StorageBackend

from ..models import Job, VoiceModel, VoiceModelStatus
from ..services import voice_models as voice_service

logger = logging.getLogger(__name__)

VOICE_TRAINING_JOB_TYPE = "voice_training"

#: Where ACE-Step keeps this platform's training artefacts, on the ACE-Step host.
#: Relative on purpose -- it must resolve under ACE-Step's working directory or
#: its path-safety check rejects it.
TRAINING_ROOT = "./acemusic-voice-training"

#: ``/v1/training/export`` writes a directory; the loadable PEFT adapter is this
#: child of it. Handing /v1/lora/load the export root fails.
ADAPTER_SUBDIR = "adapter"

#: How often the training status is polled, and how long before it is abandoned.
#: Training is minutes on a GPU; the timeout is generous because giving up on a
#: run that is still going would refund a model the musician is about to get.
POLL_INTERVAL_S = 5.0
POLL_TIMEOUT_S = 3600.0

#: How long ``is_training`` may still read false after /training/start before the
#: run is treated as having failed to begin.
TRAINING_START_GRACE_S = 60.0

#: The phases reported back, in order. US-25.2 turns these into a progress bar.
PHASES = ("preprocessing", "training", "finalizing")


class VoiceTrainingError(Exception):
    """Training could not be completed."""


async def _post(client: httpx.AsyncClient, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = await client.post(path, json=payload)
    response.raise_for_status()
    body = response.json()
    # ACE-Step wraps everything in {"data": ..., "code": ...}; `data` is sometimes
    # absent, in which case the body itself is the payload.
    data = body.get("data")
    return data if isinstance(data, dict) else body


async def _put(client: httpx.AsyncClient, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = await client.put(path, json=payload)
    response.raise_for_status()
    body = response.json()
    data = body.get("data")
    return data if isinstance(data, dict) else body


async def _get(client: httpx.AsyncClient, path: str) -> dict[str, Any]:
    response = await client.get(path)
    response.raise_for_status()
    body = response.json()
    data = body.get("data")
    return data if isinstance(data, dict) else body


async def _poll_preprocess(
    client: httpx.AsyncClient, task_id: str, *, interval: float, timeout: float
) -> dict[str, Any]:
    """Wait for a dataset preprocess task.

    ``PreprocessTask`` carries ``status`` plus ``current``/``total``, and its
    terminal states are the ordinary words — unlike training, which reports a
    boolean.
    """
    waited = 0.0

    while waited < timeout:
        data = await _get(client, f"/v1/dataset/preprocess_status/{task_id}")
        state = str(data.get("status") or "").lower()

        if state in {"completed", "complete", "success", "succeeded", "finished", "done"}:
            return data

        if state in {"failed", "error", "cancelled", "canceled"}:
            raise VoiceTrainingError(str(data.get("error") or data.get("progress") or f"preprocessing {state}"))

        await asyncio.sleep(interval)
        waited += interval

    raise VoiceTrainingError(f"Preprocessing did not finish within {int(timeout)}s")


async def _poll_training(
    client: httpx.AsyncClient, *, interval: float, timeout: float, on_progress=None
) -> dict[str, Any]:
    """Wait for a training run to finish.

    The real contract is a **boolean**, not a status word: ``/v1/training/status``
    reports ``is_training`` with a human ``status`` string ("Idle") alongside it.
    So "finished" means *is_training went false after having been true*, and the
    ``error`` field is what distinguishes success from failure.

    The started grace period matters: immediately after ``/training/start``
    returns, ``is_training`` can still read false, and treating that as "already
    finished" would report success for a run that never began.
    """
    waited = 0.0
    started = False

    while waited < timeout:
        data = await _get(client, "/v1/training/status")
        is_training = bool(data.get("is_training"))
        error = data.get("error")

        if on_progress is not None:
            await on_progress(data)

        if error:
            raise VoiceTrainingError(str(error))

        if is_training:
            started = True
        elif started:
            return data
        elif waited >= TRAINING_START_GRACE_S:
            raise VoiceTrainingError(f"Training never started (status: {data.get('status') or 'unknown'})")

        await asyncio.sleep(interval)
        waited += interval

    raise VoiceTrainingError(f"Training did not finish within {int(timeout)}s")


async def process_voice_training_job(
    job: Job,
    *,
    storage: StorageBackend,
    base_url: str,
    training_root: str = TRAINING_ROOT,
    poll_interval: float = POLL_INTERVAL_S,
    poll_timeout: float = POLL_TIMEOUT_S,
) -> dict[str, Any]:
    """Train a voice model from its stored references.

    On any failure the model is marked failed and its credits refunded, and the
    error is re-raised so the job record reflects it too.
    """
    model_id = (job.input_params or {}).get("voice_model_id")
    model = await VoiceModel.get(model_id) if model_id else None

    if model is None:
        # Nothing to refund against and nothing to train; a job pointing at a
        # missing model is a bug, not a user error.
        raise VoiceTrainingError(f"Voice training job {job.id} references unknown model {model_id!r}")

    try:
        return await _train(
            model,
            job,
            storage=storage,
            base_url=base_url,
            training_root=training_root,
            poll_interval=poll_interval,
            poll_timeout=poll_timeout,
        )
    except asyncio.CancelledError:
        # Deliberately NOT failed-and-refunded. JobProcessor re-raises this without
        # marking the job, leaving it `processing` so startup requeues it as stale.
        # Refunding here would either give the credits back for a run that then
        # succeeds, or -- refunds not being idempotent -- refund the same charge
        # twice when the retry also fails.
        model.status = VoiceModelStatus.QUEUED
        await model.save()
        raise
    except Exception as exc:
        reason = str(exc) or exc.__class__.__name__
        try:
            await voice_service.fail_training(model, reason)
            await voice_service.notify_training_finished(model, succeeded=False)
        except Exception:  # pragma: no cover - the refund must not mask the cause
            logger.exception("Failed to refund voice training for model %s", model.id)
        raise


async def _materialise_references(model: VoiceModel, storage: StorageBackend, training_root: str) -> None:
    """Copy the stored references into the directory ACE-Step will scan.

    ``training_root`` is the *local* path that ACE-Step sees as ``TRAINING_ROOT``;
    the platform writes here and ACE-Step reads the same bytes. A split deployment
    needs it to be a shared volume, because ACE-Step's training endpoints take
    paths rather than uploads.
    """
    local_dir = Path(training_root) / str(model.id) / "refs"
    local_dir.mkdir(parents=True, exist_ok=True)

    for index, key in enumerate(model.reference_paths):
        data = await asyncio.to_thread(storage.download, key)
        suffix = key.rsplit(".", 1)[-1] if "." in key else "wav"
        await asyncio.to_thread((local_dir / f"ref-{index}.{suffix}").write_bytes, data)

    logger.info(
        "Materialised %d references for voice model %s into %s", len(model.reference_paths), model.id, local_dir
    )


async def _train(
    model: VoiceModel,
    job: Job,
    *,
    storage: StorageBackend,
    base_url: str,
    training_root: str,
    poll_interval: float,
    poll_timeout: float,
) -> dict[str, Any]:
    model.status = VoiceModelStatus.TRAINING
    await model.save()

    # Server-side paths: ACE-Step preprocesses, trains and exports on its own
    # filesystem, so these name directories on that host rather than storage keys.
    reference_dir = f"{TRAINING_ROOT}/{model.id}/refs"
    tensor_dir = f"{TRAINING_ROOT}/{model.id}/tensors"
    lora_dir = f"{TRAINING_ROOT}/{model.id}/lora"
    export_path = f"{TRAINING_ROOT}/{model.id}/voice.safetensors"

    async def record(phase: str) -> None:
        job.progress = phase
        await job.save()

    async with httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=60.0) as client:
        # 1. Preprocess the references into a training dataset.
        await record("preprocessing")

        # Materialise the references where ACE-Step can see them. They live in the
        # platform's storage backend (possibly S3); ACE-Step scans a directory.
        await _materialise_references(model, storage, training_root)

        # Scan first: preprocessing works on the server's current dataset, so
        # without this it either preprocesses someone else's samples or nothing.
        scan = await _post(client, "/v1/dataset/scan", {"audio_dir": reference_dir})
        samples = scan.get("samples") or []

        if not samples:
            raise VoiceTrainingError(f"ACE-Step found no audio in {reference_dir}")

        # Then label. A scanned sample is `labeled: false`, and preprocessing
        # silently skips those -- "No labeled samples to preprocess" with a task
        # that immediately 404s. Auto-labelling needs the LLM, which is not
        # guaranteed to be loaded, so the caption is set directly.
        caption = (model.description or f"{model.name} vocal reference").strip()

        for index, _ in enumerate(samples):
            await _put(
                client,
                f"/v1/dataset/sample/{index}",
                {
                    "sample_idx": index,
                    "caption": caption,
                    "genre": "vocal",
                    "is_instrumental": False,
                    "lyrics": "[Verse]",
                    "labeled": True,
                },
            )

        dataset = await _post(
            client,
            "/v1/dataset/preprocess_async",
            {"output_dir": tensor_dir, "skip_existing": False},
        )
        task_id = dataset.get("task_id")

        if task_id:
            await _poll_preprocess(client, str(task_id), interval=poll_interval, timeout=poll_timeout)

        # 2. Fine-tune.
        await record("training")
        await _post(
            client,
            "/v1/training/start",
            {"tensor_dir": tensor_dir, "lora_output_dir": lora_dir},
        )

        async def on_progress(data: dict[str, Any]) -> None:
            # Structured provider progress, in the field the platform already has
            # for exactly this (US-22.1 video uses it the same way).
            # Field names are ACE-Step's own (see its /v1/training/status payload).
            job.progress_detail = {
                "phase": "training",
                "step": data.get("current_step"),
                "epoch": data.get("current_epoch"),
                "loss": data.get("current_loss"),
                "eta_seconds": data.get("estimated_time_remaining"),
            }
            await job.save()

        await _poll_training(client, interval=poll_interval, timeout=poll_timeout, on_progress=on_progress)

        # 3. Export the LoRA weights and keep them.
        await record("finalizing")
        exported = await _post(
            client,
            "/v1/training/export",
            {"export_path": export_path, "lora_output_dir": lora_dir},
        )

    exported_path = str(
        exported.get("export_path") or exported.get("weights") or exported.get("path") or export_path or ""
    ).rstrip("/")

    # The export writes a *directory*, and /v1/lora/load wants the PEFT adapter
    # inside it -- pointing at the export root is rejected with "Invalid adapter:
    # expected PEFT LoRA directory containing adapter_config.json". Verified end to
    # end against a real trained model, so what is stored here is the path that
    # actually loads.
    weights = f"{exported_path}/{ADAPTER_SUBDIR}" if exported_path else None

    if not weights:
        # A training run that produces no weights has produced no voice, whatever
        # the status said.
        raise VoiceTrainingError("Training finished but produced no weights")

    model.weights_path = str(weights)
    model.status = VoiceModelStatus.READY
    model.error = None
    await model.save()

    await voice_service.notify_training_finished(model, succeeded=True)

    return {"voice_model_id": str(model.id), "weights_path": model.weights_path}


VOICE_TRAINING_JOB_HANDLERS = {VOICE_TRAINING_JOB_TYPE: process_voice_training_job}
