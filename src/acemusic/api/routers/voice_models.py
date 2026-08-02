"""Voice model endpoints (US-25.1 training, US-25.3 library), mounted under
``/api/v1/voice-models``.

* ``POST   /voice-models/train`` → validate references, charge, queue training
* ``GET    /voice-models``       → the caller's models, newest first

Every read is owner-scoped: a voice model is private, and ownership is part of
the query rather than a check afterwards, so there is no path that reads someone
else's model at all.
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel

from ..auth.dependencies import CurrentUser, require_existing_user
from ..models import VoiceModel, VoiceModelStatus
from ..models.voice_model import MAX_REFERENCE_FILES, MIN_REFERENCE_FILES
from ..services import credits as credits_service, voice_models as voice_service

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


@router.post("/train", response_model=TrainingAccepted, status_code=status.HTTP_202_ACCEPTED)
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


@router.get("", response_model=list[VoiceModelResponse])
async def list_voice_models(
    current: CurrentUser = Depends(require_existing_user),
) -> list[VoiceModelResponse]:
    """The caller's voice models, newest first."""
    models = await voice_service.list_voice_models(current.user_id)
    return [VoiceModelResponse.from_model(m) for m in models]
