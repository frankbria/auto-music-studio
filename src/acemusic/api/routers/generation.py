"""Generation endpoint (US-9.1), mounted under ``/api/v1/generate``.

``POST /api/v1/generate`` accepts the full creative parameter set — text-to-music
("song") and "sound" (one-shot / loop) modes — validates it, creates a queued
:class:`~acemusic.api.models.job.Job`, and returns a job id for async tracking.
Actual job execution is US-9.2; this endpoint only validates and enqueues.

Request/response schemas live here, matching the auth and users routers. Field
bounds and enumerations come from :mod:`acemusic.constants` so CLI and API
validation share one source of truth.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from acemusic.constants import (
    BPM_MAX,
    BPM_MIN,
    DURATION_MAX,
    DURATION_MIN,
    STYLE_INFLUENCE_MAX,
    STYLE_INFLUENCE_MIN,
    VALID_FORMATS,
    VALID_MODELS,
    VALID_TIME_SIGNATURES,
    WEIRDNESS_MAX,
    WEIRDNESS_MIN,
)

from ..auth.dependencies import CurrentUser, get_current_user
from ..services import generation as generation_service

# Estimate heuristic (seconds): a song's wall-clock scales with its duration; a
# short sound is roughly fixed. These are advisory hints returned to the client.
_SONG_BASE_SECONDS = 30
_SOUND_BASE_SECONDS = 15

# Router-level dependency gates every route behind a valid Bearer token, so an
# unauthenticated request is rejected with 401 before any handler runs.
router = APIRouter(prefix="/generate", tags=["generation"], dependencies=[Depends(get_current_user)])


class GenerationRequest(BaseModel):
    """The full creative parameter set for a generation request.

    ``extra="forbid"`` rejects unknown keys with 422 (a client typo surfaces
    instead of being silently dropped). Numeric ranges are enforced with
    ``Field`` constraints; enum-like fields validate against the shared constants.
    """

    model_config = ConfigDict(extra="forbid")

    prompt: Annotated[str, Field(min_length=1)]
    style: str | None = None
    lyrics: str | None = None
    vocal_language: str | None = None
    instrumental: bool = False
    bpm: Annotated[int, Field(ge=BPM_MIN, le=BPM_MAX)] | Literal["auto"] | None = None
    key: str | None = None
    time_signature: str | None = None
    duration: Annotated[float, Field(ge=DURATION_MIN, le=DURATION_MAX)] | None = None
    seed: int | None = None
    inference_steps: Annotated[int, Field(gt=0)] | None = None
    model: str | None = None
    weirdness: Annotated[int, Field(ge=WEIRDNESS_MIN, le=WEIRDNESS_MAX)] = 50
    style_influence: Annotated[int, Field(ge=STYLE_INFLUENCE_MIN, le=STYLE_INFLUENCE_MAX)] = 50
    format: str = "wav"
    thinking: bool = False
    mode: Literal["song", "sound"] = "song"
    sound_type: Literal["one-shot", "loop"] | None = None

    @field_validator("format")
    @classmethod
    def _check_format(cls, value: str) -> str:
        if value not in VALID_FORMATS:
            raise ValueError(f"format must be one of {sorted(VALID_FORMATS)}")
        return value

    @field_validator("model")
    @classmethod
    def _check_model(cls, value: str | None) -> str | None:
        if value is not None and value not in VALID_MODELS:
            raise ValueError(f"model must be one of {sorted(VALID_MODELS)}")
        return value

    @field_validator("time_signature")
    @classmethod
    def _check_time_signature(cls, value: str | None) -> str | None:
        if value is not None and value not in VALID_TIME_SIGNATURES:
            raise ValueError(f"time_signature must be one of {sorted(VALID_TIME_SIGNATURES)}")
        return value

    @model_validator(mode="after")
    def _check_mode_constraints(self) -> "GenerationRequest":
        # sound_type and mode are coupled: it is required for sounds and
        # meaningless for songs.
        if self.mode == "sound" and self.sound_type is None:
            raise ValueError("sound_type is required when mode is 'sound'")
        if self.mode == "song" and self.sound_type is not None:
            raise ValueError("sound_type must be omitted when mode is 'song'")
        # A one-shot is a single hit with no tempo/tonal context; bpm/key apply
        # only to loops (mirrors the CLI `sounds` command).
        if self.sound_type == "one-shot" and (self.bpm is not None or self.key is not None):
            raise ValueError("bpm and key are not allowed for one-shot sounds")
        return self


class GenerationResponse(BaseModel):
    """The accepted-job acknowledgement returned with HTTP 202."""

    job_id: str
    status: Literal["queued"] = "queued"
    estimated_time_seconds: int


def estimate_seconds(request: GenerationRequest) -> int:
    """Rough wall-clock estimate for a request, in seconds (advisory)."""
    if request.mode == "sound":
        return _SOUND_BASE_SECONDS
    duration = request.duration if request.duration is not None else DURATION_MIN
    return _SONG_BASE_SECONDS + int(duration)


@router.post("", response_model=GenerationResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_generation(
    request: GenerationRequest,
    current: CurrentUser = Depends(get_current_user),
) -> GenerationResponse:
    """Validate the request, persist a queued job, and return its id.

    Pydantic returns 422 with field-level errors for invalid bodies; the router
    dependency returns 401 for missing/invalid tokens — both before this runs.
    """
    job = await generation_service.create_generation_job(
        user_id=current.user_id,
        params=request.model_dump(exclude_none=True),
    )
    return GenerationResponse(job_id=str(job.id), estimated_time_seconds=estimate_seconds(request))
