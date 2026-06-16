"""Generation endpoint (US-9.1), mounted under ``/api/v1/generate``.

``POST /api/v1/generate`` accepts the full creative parameter set — text-to-music
("song") and "sound" (one-shot / loop) modes — validates it, creates a queued
:class:`~acemusic.api.models.job.Job`, and returns a job id for async tracking.
Actual job execution is US-9.2; this endpoint only validates and enqueues.

Request/response schemas live here, matching the auth and users routers. Field
bounds and enumerations come from :mod:`acemusic.constants` so CLI and API
validation share one source of truth.
"""

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from acemusic.constants import (
    BPM_MAX,
    BPM_MIN,
    DURATION_MAX,
    DURATION_MIN,
    INFERENCE_STEPS_MAX,
    KEY_MAX_LENGTH,
    LYRICS_MAX_LENGTH,
    PROMPT_MAX_LENGTH,
    SEED_MAX,
    SEED_MIN,
    STYLE_INFLUENCE_MAX,
    STYLE_INFLUENCE_MIN,
    STYLE_MAX_LENGTH,
    VOCAL_LANGUAGE_MAX_LENGTH,
    WEIRDNESS_MAX,
    WEIRDNESS_MIN,
)

from ..auth.dependencies import CurrentUser, get_current_user, get_settings
from ..models import PRESET_PARAM_FIELDS, Preset
from ..services import (
    credits as credits_service,
    generation as generation_service,
    presets as preset_service,
    routing as routing_service,
    users as user_service,
)
from ..services.routing import ComputePreference, ComputeUnavailableError
from ..settings import ApiSettings
from ._validators import validate_format, validate_model, validate_time_signature

logger = logging.getLogger(__name__)

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

    # US-9.5: apply a saved preset as parameter defaults; explicitly-sent
    # request fields override preset values. Never forwarded to the job.
    preset_id: str | None = None

    # US-11.1: per-request compute routing override. ``None`` and ``"auto"`` both
    # defer to the server's configured ``compute_preference`` (with fallback);
    # ``"local"``/``"remote"`` pin the target with no fallback. This is a routing
    # hint, not a creative param — never forwarded to the job's input_params.
    compute_target: Literal["auto", "local", "remote"] | None = None

    prompt: Annotated[str, Field(min_length=1, max_length=PROMPT_MAX_LENGTH)]
    style: Annotated[str, Field(max_length=STYLE_MAX_LENGTH)] | None = None
    lyrics: Annotated[str, Field(max_length=LYRICS_MAX_LENGTH)] | None = None
    vocal_language: Annotated[str, Field(max_length=VOCAL_LANGUAGE_MAX_LENGTH)] | None = None
    instrumental: bool = False
    bpm: Annotated[int, Field(ge=BPM_MIN, le=BPM_MAX)] | Literal["auto"] | None = None
    key: Annotated[str, Field(max_length=KEY_MAX_LENGTH)] | None = None
    time_signature: str | None = None
    # Upper bound and positivity hold for every mode; the 30s song floor is
    # enforced mode-aware below so short sounds (one-shots, loops) are allowed.
    duration: Annotated[float, Field(gt=0, le=DURATION_MAX)] | None = None
    seed: Annotated[int, Field(ge=SEED_MIN, le=SEED_MAX)] | None = None
    inference_steps: Annotated[int, Field(gt=0, le=INFERENCE_STEPS_MAX)] | None = None
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
        return validate_format(value)

    @field_validator("model")
    @classmethod
    def _check_model(cls, value: str | None) -> str | None:
        return validate_model(value)

    @field_validator("time_signature")
    @classmethod
    def _check_time_signature(cls, value: str | None) -> str | None:
        return validate_time_signature(value)

    @model_validator(mode="after")
    def _check_mode_constraints(self) -> "GenerationRequest":
        # With a preset in play the cross-field rules can only be judged on the
        # MERGED parameter set (the preset may supply sound_type, duration, …),
        # so they are deferred to _apply_preset's re-validation, where the
        # merged model carries preset_id=None and these checks run.
        if self.preset_id is not None:
            return self
        # sound_type and mode are coupled: it is required for sounds and
        # meaningless for songs.
        if self.mode == "sound" and self.sound_type is None:
            raise ValueError("sound_type is required when mode is 'sound'")
        if self.mode == "song" and self.sound_type is not None:
            raise ValueError("sound_type must be omitted when mode is 'song'")
        # Songs have a 30s floor (full-track generation); sounds may be short.
        if self.mode == "song" and self.duration is not None and self.duration < DURATION_MIN:
            raise ValueError(f"duration must be at least {DURATION_MIN}s for songs")
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


def _apply_preset(request: GenerationRequest, preset: Preset) -> GenerationRequest:
    """Merge ``preset`` into ``request``: preset values are the base, fields the
    client explicitly sent win (``model_fields_set``, so an explicit value equal
    to a schema default still overrides). The merged set is re-validated as a
    plain request (preset_id absent), which enforces the deferred cross-field
    rules; a conflict surfaces as 422 just like any other invalid body.
    """
    base = {field: getattr(preset, field) for field in PRESET_PARAM_FIELDS if getattr(preset, field) is not None}
    explicit = {field: getattr(request, field) for field in request.model_fields_set if field != "preset_id"}
    try:
        return GenerationRequest.model_validate({**base, **explicit})
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=[{"loc": list(error["loc"]), "msg": error["msg"], "type": error["type"]} for error in exc.errors()],
        ) from exc


@router.post(
    "",
    response_model=GenerationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "Compute target unavailable"}},
)
async def create_generation(
    request: GenerationRequest,
    current: CurrentUser = Depends(get_current_user),
    settings: ApiSettings = Depends(get_settings),
) -> GenerationResponse:
    """Validate the request, persist a queued job, and return its id.

    Pydantic returns 422 with field-level errors for invalid bodies; the router
    dependency returns 401 for missing/invalid tokens — both before this runs.
    """
    # The token is valid, but the principal may have been deleted (or carry a
    # malformed id). Resolve the real user before writing any user-scoped records,
    # so a stale token yields a clean 404 instead of orphaned job/workspace rows.
    user = await user_service.get_user_by_id(current.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    if request.preset_id is not None:
        # 404 for unknown/malformed/not-owned ids (never reveals other users' presets).
        preset = await preset_service.get_preset(request.preset_id, current.user_id)
        request = _apply_preset(request, preset)
    # US-11.1: pick the compute target BEFORE charging credits, so an unavailable
    # backend yields a clean 503 without ever touching the balance.
    try:
        resolved_target = await routing_service.resolve_compute_target(
            request_target=request.compute_target,
            preference=ComputePreference(settings.compute_preference),
            local_url=settings.local_url,
            settings=settings,
        )
    except ComputeUnavailableError as exc:
        # Distinguish a request-pinned target from the server preference so the
        # 503 doesn't report a synthetic "preference" the client never set.
        if request.compute_target in ("local", "remote"):
            detail = f"Requested compute target '{exc.target.value}' is unavailable."
        else:
            detail = f"Compute target '{exc.target.value}' is unavailable (preference: {exc.preference.value})."
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail) from exc
    # US-9.6: credits are deducted atomically at queue time. Cost is judged on
    # the merged request, since a preset may supply the mode. The atomic
    # balance-conditioned deduction is the concurrency guard — two requests
    # racing over the last credit cannot both pass.
    cost = credits_service.get_cost(request.mode)
    balance_after = await credits_service.deduct_credits(user.id, cost)
    if balance_after is None:
        # Re-read the balance for the error payload: the copy on ``user`` was
        # loaded before the deduction attempt and may be stale under
        # concurrent requests.
        fresh = await user_service.get_user_by_id(user.id)
        balance = fresh.credits_balance if fresh is not None else 0.0
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={"error": "insufficient_credits", "balance": balance, "required": cost},
        )
    try:
        job = await generation_service.create_generation_job(
            user_id=user.id,
            params=request.model_dump(exclude_none=True, exclude={"preset_id", "compute_target"}),
            compute_target=resolved_target,
        )
    except BaseException:
        # The deduction already landed but no job exists — give the credit back
        # rather than charging for work that will never run. BaseException (not
        # Exception) on purpose: asyncio.CancelledError must also compensate.
        await credits_service.refund_credits(user.id, cost)
        raise
    try:
        await credits_service.record_transaction(
            user_id=user.id,
            amount=-cost,
            action_type=request.mode,
            job_id=str(job.id),
            balance_after=balance_after,
        )
    except Exception:
        # The charge is taken and the job is dispatched (possibly already
        # claimed by the processor), so failing the request here would invite a
        # retry that charges the user twice for work that is already running.
        # The ledger row is best-effort history — log loudly and keep the 202.
        logger.exception("Credit ledger write failed for job %s (user %s)", job.id, user.id)
    return GenerationResponse(job_id=str(job.id), estimated_time_seconds=estimate_seconds(request))
