"""Voice model endpoints (US-25.1 training, US-25.3 library), mounted under
``/api/v1/voice-models``.

* ``POST   /voice-models/train``                  → validate, charge, queue training
* ``GET    /voice-models/train/{job_id}/status``  → phase, progress, ETA (US-25.2)
* ``GET    /voice-models``                        → the caller's models, newest first
* ``GET    /voice-models/{id}/preview``           → a reference recording to listen to (US-25.4)
* ``PATCH  /voice-models/{id}``                   → rename / re-describe (US-25.3)
* ``DELETE /voice-models/{id}``                   → remove it and free its storage

Every read is owner-scoped: a voice model is private, and ownership is part of
the query rather than a check afterwards, so there is no path that reads someone
else's model at all.
"""

import asyncio
import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field

from acemusic.storage import get_storage_backend

from ..auth.dependencies import CurrentUser, require_capability, require_existing_user
from ..models import VoiceModel, VoiceModelStatus
from ..models.voice_model import MAX_REFERENCE_FILES, MIN_REFERENCE_FILES
from ..services import credits as credits_service, voice_models as voice_service
from ..services.tiers import Capability
from ..utils.media_types import get_audio_content_type

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/voice-models", tags=["voice-models"])


class VoiceModelResponse(BaseModel):
    id: str
    name: str
    description: str | None
    status: VoiceModelStatus
    reference_count: int
    job_id: str | None
    error: str | None
    created_at: datetime

    @classmethod
    def from_model(cls, model: VoiceModel) -> "VoiceModelResponse":
        return cls(
            id=str(model.id),
            name=model.name,
            description=model.description,
            status=model.status,
            reference_count=model.reference_count,
            job_id=str(model.job_id) if model.job_id else None,
            error=model.error,
            created_at=model.created_at,
        )


class TrainingAccepted(BaseModel):
    """What a caller needs to follow the run (US-25.2 adds the status endpoint)."""

    job_id: str
    voice_model: VoiceModelResponse
    credits_charged: float


@router.post(
    "/train",
    response_model=TrainingAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    # US-26.2: Pro-only. Reads stay open so a downgraded account can still see and
    # delete voices it already trained.
    dependencies=[Depends(require_capability(Capability.VOICE_MODELS))],
)
async def train_voice_model(
    files: list[UploadFile] = File(...),
    name: str = Form(...),
    description: str | None = Form(default=None),
    current: CurrentUser = Depends(require_existing_user),
) -> TrainingAccepted:
    """Queue a LoRA fine-tune from the caller's reference recordings.

    Validation runs before the charge, so a rejected upload never costs credits.
    """
    # Bounded before the bodies are read: eleven 50MB uploads should not be
    # buffered just to be told there are too many.
    if not MIN_REFERENCE_FILES <= len(files) <= MAX_REFERENCE_FILES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Training takes between {MIN_REFERENCE_FILES} and {MAX_REFERENCE_FILES} "
                f"reference files; {len(files)} were uploaded."
            ),
        )

    payloads = [(f.filename or "reference", await f.read()) for f in files]

    try:
        model, job = await voice_service.create_training_job(current.user_id, name, payloads, description=description)
    except voice_service.InsufficientCreditsError as exc:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=str(exc),
        ) from exc
    except voice_service.VoiceModelError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    return TrainingAccepted(
        job_id=str(job.id),
        voice_model=VoiceModelResponse.from_model(model),
        credits_charged=credits_service.VOICE_TRAINING_COST,
    )


class TrainingStatusResponse(BaseModel):
    """Where a training run has got to.

    ``progress`` is **null** when no total is knowable rather than a fabricated
    number: ACE-Step reports steps and epochs, not a fraction, and a progress bar
    that lies is worse than one that says "working".
    """

    job_id: str
    voice_model_id: str
    status: VoiceModelStatus
    phase: str
    progress: float | None = None
    eta_seconds: float | None = None
    step: int | None = None
    epoch: int | None = None
    loss: float | None = None
    error: str | None = None


@router.get("/train/{job_id}/status", response_model=TrainingStatusResponse)
async def get_training_status(
    job_id: str,
    current: CurrentUser = Depends(require_existing_user),
) -> TrainingStatusResponse:
    """Progress of a training run.

    Resolved through the voice model's owner, so another user's run 404s rather
    than leaking that it exists.
    """
    found = await voice_service.find_model_for_job(job_id, current.user_id)

    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Training job not found.")

    model, job = found
    progress = voice_service.describe_progress(job, model)

    return TrainingStatusResponse(
        job_id=str(job.id),
        voice_model_id=str(model.id),
        status=model.status,
        phase=progress["phase"],
        progress=progress.get("progress"),
        eta_seconds=progress.get("eta_seconds"),
        step=progress.get("step"),
        epoch=progress.get("epoch"),
        loss=progress.get("loss"),
        error=progress.get("error"),
    )


class VoiceModelUpdate(BaseModel):
    """Editable fields. ``extra="forbid"`` so a client cannot smuggle in ``status``
    or ``weights_path`` — those are the system's, not theirs. Mirrors ClipUpdate."""

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=120)] | None = None
    description: Annotated[str, Field(max_length=1000)] | None = None


@router.patch("/{model_id}", response_model=VoiceModelResponse)
async def update_voice_model(
    model_id: str,
    update: VoiceModelUpdate,
    current: CurrentUser = Depends(require_existing_user),
) -> VoiceModelResponse:
    """Rename or re-describe a voice model."""
    try:
        model = await voice_service.rename_voice_model(
            model_id, current.user_id, name=update.name, description=update.description
        )
    except voice_service.VoiceModelError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    if model is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Voice model not found.")

    return VoiceModelResponse.from_model(model)


@router.delete("/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_voice_model(
    model_id: str,
    current: CurrentUser = Depends(require_existing_user),
) -> Response:
    """Remove a voice model and free its stored weights and references."""
    try:
        removed = await voice_service.delete_voice_model(model_id, current.user_id)
    except voice_service.VoiceModelError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    if not removed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Voice model not found.")

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("", response_model=list[VoiceModelResponse])
async def list_voice_models(
    current: CurrentUser = Depends(require_existing_user),
) -> list[VoiceModelResponse]:
    """The caller's voice models, newest first."""
    models = await voice_service.list_voice_models(current.user_id)
    return [VoiceModelResponse.from_model(m) for m in models]


@router.get("/{model_id}/preview")
async def preview_voice_model(
    model_id: str,
    current: CurrentUser = Depends(require_existing_user),
) -> Response:
    """The first reference recording this voice was trained from (US-25.4).

    It is what the musician can actually listen to before attaching a voice: a trained
    LoRA has no renderable sample of its own, and generating one on demand would cost a
    GPU run per browse. Owner-scoped like every other read here.
    """
    model = await voice_service.find_owned_model(model_id, current.user_id)

    if model is None or not model.reference_paths:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Voice model preview not found.")

    path = model.reference_paths[0]
    storage = get_storage_backend()

    try:
        data = await asyncio.to_thread(storage.download, path)
    except FileNotFoundError as exc:
        logger.warning("Voice model %s exists but its reference %r is missing", model.id, path)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Voice model preview not found.") from exc

    suffix = path.rsplit(".", 1)[-1] if "." in path else None
    return Response(content=data, media_type=get_audio_content_type(suffix))
