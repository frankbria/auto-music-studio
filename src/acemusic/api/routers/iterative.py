"""Iterative generation endpoints (US-10.3).

AI-powered iterative modes, each taking a source clip (or several, for mashup)
plus mode-specific parameters and producing a *new* clip with lineage back to
its source(s):

* ``POST /clips/{id}/extend``    → continue/grow the clip (ACE-Step ``repaint``)
* ``POST /clips/{id}/cover``     → restyle in a new genre (ACE-Step ``cover``)
* ``POST /clips/{id}/remix``     → style transfer (ACE-Step ``cover``; see Design Choice 2)
* ``POST /clips/{id}/repaint``   → regenerate a time range (ACE-Step ``repaint`` + stitch)
* ``POST /clips/{id}/sample``    → extract a loop and build around it (generate + combine)
* ``POST /clips/{id}/add-vocal`` → layer vocals onto the clip (ACE-Step ``complete``)
* ``POST /mashup``               → blend 2+ clips into one (ACE-Step ``mashup``)

Each endpoint validates the request against the source clip(s), deducts credits
atomically at queue time (mirroring ``POST /generate`` — these are generative,
credit-bearing operations, unlike editing/extraction), persists a queued
:class:`~acemusic.api.models.job.Job`, and returns 202 with a job id trackable
via ``GET /api/v1/jobs/{id}/status``. The worker (``acemusic.api.tasks.iterative``)
runs the generation and creates the lineage-tagged child clip.

Time parameters are human-readable strings ("60s", "1m30s", "5") parsed with
:func:`acemusic.utils.parse_time_string`, matching the CLI commands.
"""

import logging
from enum import Enum
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from acemusic.utils import parse_time_string

from ..auth.dependencies import CurrentUser, get_current_user
from ..models import Clip
from ..services import (
    clips as clip_service,
    credits as credits_service,
    iterative as iterative_service,
    users as user_service,
)

logger = logging.getLogger(__name__)

# Advisory wall-clock estimates (seconds) returned to the client. Iterative
# generations run one ACE-Step task each, so the base is the song estimate;
# sample scales with the number of clips it produces.
_BASE_ESTIMATE_SECONDS = 45
_MAX_SAMPLE_CLIPS = 4

# Router-level dependency gates every route behind a valid Bearer token (mirrors
# the editing/generation routers), so unauthenticated requests get 401. No
# prefix: clip-scoped routes carry the full ``/clips/{id}/...`` path while
# ``/mashup`` is a standalone, multi-source route.
router = APIRouter(tags=["iterative"], dependencies=[Depends(get_current_user)])


# ---------------------------------------------------------------------------
# Enums and shared validators
# ---------------------------------------------------------------------------


class BlendMode(str, Enum):
    """How a mashup combines its sources."""

    LAYERED = "layered"
    SEQUENTIAL = "sequential"
    AI_GUIDED = "ai-guided"


class SampleRole(str, Enum):
    """The musical role an extracted sample plays in the generated track."""

    LOOP_BED = "loop-bed"
    INTRO_OUTRO = "intro-outro"
    RHYTHMIC_ELEMENT = "rhythmic-element"
    MELODIC_HOOK = "melodic-hook"


class GenerationBackend(str, Enum):
    """Which generation backend services a sample request."""

    ACE_STEP = "ace-step"
    ELEVENLABS = "elevenlabs"


def _validate_time_string(value: str) -> str:
    """Field validator: reject unparseable time strings as field-level 422s."""
    parse_time_string(value)
    return value


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class ExtendRequest(BaseModel):
    """Grow a clip by ``duration`` from ``from_point`` (default the end)."""

    model_config = ConfigDict(extra="forbid")

    duration: str
    from_point: str = "end"
    style_override: str | None = None
    lyrics: str | None = None

    @field_validator("duration")
    @classmethod
    def _check_duration(cls, value: str) -> str:
        return _validate_time_string(value)

    @field_validator("from_point")
    @classmethod
    def _check_from_point(cls, value: str) -> str:
        # "end" is the sentinel for "append at the tail"; anything else must be
        # a parseable offset into the source clip.
        if value != "end":
            parse_time_string(value)
        return value


class CoverRequest(BaseModel):
    """Restyle a clip in a different genre/style.

    ``voice_id`` is part of the API contract (US-10.3) but is not yet applied by
    the ACE-Step backend, which has no voice-selection parameter — it is accepted
    and recorded for forward compatibility, not honoured. (Known limitation.)
    """

    model_config = ConfigDict(extra="forbid")

    style: str = Field(min_length=1)
    voice_id: str | None = None
    lyrics_override: str | None = None


class RemixRequest(BaseModel):
    """Style transfer (no explicit melody preservation; see Design Choice 2)."""

    model_config = ConfigDict(extra="forbid")

    style: str = Field(min_length=1)


class RepaintRequest(BaseModel):
    """Regenerate the ``[start, end]`` range of a clip from ``prompt``."""

    model_config = ConfigDict(extra="forbid")

    start: str
    end: str
    prompt: str = Field(min_length=1)
    style: str | None = None

    @field_validator("start", "end")
    @classmethod
    def _check_time(cls, value: str) -> str:
        return _validate_time_string(value)


class SampleRequest(BaseModel):
    """Extract the ``[start, end]`` range and build ``num_clips`` tracks around it."""

    model_config = ConfigDict(extra="forbid")

    start: str
    end: str
    role: SampleRole
    prompt: str = Field(min_length=1)
    backend: GenerationBackend = GenerationBackend.ACE_STEP
    num_clips: int = Field(default=1, ge=1, le=_MAX_SAMPLE_CLIPS)

    @field_validator("start", "end")
    @classmethod
    def _check_time(cls, value: str) -> str:
        return _validate_time_string(value)


class AddVocalRequest(BaseModel):
    """Layer vocals (``lyrics``) onto an existing clip.

    ``vocal_style`` maps to the ACE-Step style control; ``voice_id`` is recorded
    for forward compatibility but not yet applied by the backend (no voice-
    selection parameter). (Known limitation.)
    """

    model_config = ConfigDict(extra="forbid")

    lyrics: str = Field(min_length=1)
    voice_id: str | None = None
    vocal_style: str | None = None


class MashupRequest(BaseModel):
    """Blend two or more clips into one. ``clip_ids[0]`` is the primary source."""

    model_config = ConfigDict(extra="forbid")

    clip_ids: list[str] = Field(min_length=2)
    blend_mode: BlendMode = BlendMode.LAYERED
    style: str | None = None

    @model_validator(mode="after")
    def _check_distinct(self) -> "MashupRequest":
        if len(set(self.clip_ids)) != len(self.clip_ids):
            raise ValueError("clip_ids must be distinct")
        return self


class IterativeJobResponse(BaseModel):
    """The accepted-job acknowledgement returned with HTTP 202."""

    job_id: str
    status: Literal["queued"] = "queued"
    estimated_time_seconds: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _unprocessable(detail: str) -> HTTPException:
    """Clip-dependent validation failure (the body itself parsed fine)."""
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)


def _require_wav(clip: Clip) -> None:
    """422 unless the clip's audio is wav.

    The repaint/sample/mashup post-processing runs through pydub, which needs
    ffmpeg (absent on the server) for compressed formats, and ACE-Step is fed
    the raw source — so a non-wav source would only fail later in the worker
    with an opaque error. Mirrors the editing endpoints' constraint.
    """
    fmt = clip_service.native_format(clip)
    if fmt != "wav":
        raise _unprocessable(f"unsupported format {fmt!r} for iterative generation; currently only wav is supported.")


def _require_duration_ms(clip: Clip) -> int:
    """The clip's duration in milliseconds, or 422 if the metadata is missing."""
    if clip.duration is None:
        raise _unprocessable(f"Clip {clip.id} has no duration metadata; cannot validate the request.")
    return int(round(clip.duration * 1000))


def _check_range(start_ms: int, end_ms: int, duration_ms: int, start: str, end: str, clip: Clip) -> None:
    """Common ``[start, end]`` bounds check for repaint/sample (422 on failure)."""
    if start_ms >= end_ms:
        raise _unprocessable(f"start ({start}) must be less than end ({end}).")
    if end_ms > duration_ms:
        raise _unprocessable(f"end ({end}) exceeds clip duration ({clip.duration:.1f}s).")


async def _enqueue_generation(
    *,
    user_id: str,
    job_type: str,
    workspace_id,
    params: dict,
    cost: float,
    estimate_seconds: int,
) -> IterativeJobResponse:
    """Resolve the user, deduct credits atomically, persist the job, return 202.

    Mirrors ``POST /generate``: the atomic balance-conditioned deduction is the
    concurrency guard; a job-creation failure refunds; the ledger write is
    best-effort. Raises 404 (stale token), 402 (insufficient credits).
    """
    user = await user_service.get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    balance_after = await credits_service.deduct_credits(user.id, cost)
    if balance_after is None:
        fresh = await user_service.get_user_by_id(user.id)
        balance = fresh.credits_balance if fresh is not None else 0.0
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={"error": "insufficient_credits", "balance": balance, "required": cost},
        )
    try:
        job = await iterative_service.create_iterative_job(
            user_id=user.id,
            workspace_id=workspace_id,
            job_type=job_type,
            params=params,
        )
    except BaseException:
        # The deduction already landed but no job exists — give the credit back.
        # BaseException (not Exception): asyncio.CancelledError must also refund.
        await credits_service.refund_credits(user.id, cost)
        raise
    try:
        await credits_service.record_transaction(
            user_id=user.id,
            amount=-cost,
            action_type=job_type,
            job_id=str(job.id),
            balance_after=balance_after,
        )
    except Exception:
        # The charge is taken and the job dispatched; failing here would invite a
        # retry that double-charges. The ledger row is best-effort history.
        logger.exception("Credit ledger write failed for job %s (user %s)", job.id, user.id)
    return IterativeJobResponse(job_id=str(job.id), estimated_time_seconds=estimate_seconds)


async def _owned_wav_clip(clip_id: str, user_id: str) -> Clip:
    """Resolve a source clip the user owns and gate it to wav (404 then 422)."""
    clip = await clip_service.get_owned_clip(clip_id, user_id)
    _require_wav(clip)
    return clip


# ---------------------------------------------------------------------------
# Single-clip transformation endpoints
# ---------------------------------------------------------------------------


@router.post("/clips/{clip_id}/extend", response_model=IterativeJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def extend_clip(
    clip_id: str,
    request: ExtendRequest,
    current: CurrentUser = Depends(get_current_user),
) -> IterativeJobResponse:
    """Enqueue an extension of ``clip_id`` by ``duration``; the original is preserved."""
    clip = await _owned_wav_clip(clip_id, current.user_id)
    if request.from_point != "end":
        duration_ms = _require_duration_ms(clip)
        if parse_time_string(request.from_point) > duration_ms:
            raise _unprocessable(f"from_point ({request.from_point}) exceeds clip duration ({clip.duration:.1f}s).")
    params = {
        "clip_id": str(clip.id),
        "duration": request.duration,
        "from_point": request.from_point,
        "style_override": request.style_override,
        "lyrics": request.lyrics,
    }
    return await _enqueue_generation(
        user_id=current.user_id,
        job_type=iterative_service.EXTEND_JOB_TYPE,
        workspace_id=clip.workspace_id,
        params=params,
        cost=credits_service.get_cost(iterative_service.EXTEND_JOB_TYPE),
        estimate_seconds=_BASE_ESTIMATE_SECONDS,
    )


@router.post("/clips/{clip_id}/cover", response_model=IterativeJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def cover_clip(
    clip_id: str,
    request: CoverRequest,
    current: CurrentUser = Depends(get_current_user),
) -> IterativeJobResponse:
    """Enqueue a cover (restyle) of ``clip_id``; the original is preserved."""
    clip = await _owned_wav_clip(clip_id, current.user_id)
    params = {
        "clip_id": str(clip.id),
        "style": request.style,
        "voice_id": request.voice_id,
        "lyrics_override": request.lyrics_override,
    }
    return await _enqueue_generation(
        user_id=current.user_id,
        job_type=iterative_service.COVER_JOB_TYPE,
        workspace_id=clip.workspace_id,
        params=params,
        cost=credits_service.get_cost(iterative_service.COVER_JOB_TYPE),
        estimate_seconds=_BASE_ESTIMATE_SECONDS,
    )


@router.post("/clips/{clip_id}/remix", response_model=IterativeJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def remix_clip(
    clip_id: str,
    request: RemixRequest,
    current: CurrentUser = Depends(get_current_user),
) -> IterativeJobResponse:
    """Enqueue a remix (style transfer) of ``clip_id``; the original is preserved."""
    clip = await _owned_wav_clip(clip_id, current.user_id)
    params = {"clip_id": str(clip.id), "style": request.style}
    return await _enqueue_generation(
        user_id=current.user_id,
        job_type=iterative_service.REMIX_JOB_TYPE,
        workspace_id=clip.workspace_id,
        params=params,
        cost=credits_service.get_cost(iterative_service.REMIX_JOB_TYPE),
        estimate_seconds=_BASE_ESTIMATE_SECONDS,
    )


@router.post("/clips/{clip_id}/repaint", response_model=IterativeJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def repaint_clip(
    clip_id: str,
    request: RepaintRequest,
    current: CurrentUser = Depends(get_current_user),
) -> IterativeJobResponse:
    """Enqueue a repaint of ``clip_id``'s ``[start, end]`` range; the original is preserved."""
    clip = await _owned_wav_clip(clip_id, current.user_id)
    duration_ms = _require_duration_ms(clip)
    start_ms = parse_time_string(request.start)
    end_ms = parse_time_string(request.end)
    _check_range(start_ms, end_ms, duration_ms, request.start, request.end, clip)
    params = {
        "clip_id": str(clip.id),
        "start_ms": start_ms,
        "end_ms": end_ms,
        "prompt": request.prompt,
        "style": request.style,
    }
    return await _enqueue_generation(
        user_id=current.user_id,
        job_type=iterative_service.REPAINT_JOB_TYPE,
        workspace_id=clip.workspace_id,
        params=params,
        cost=credits_service.get_cost(iterative_service.REPAINT_JOB_TYPE),
        estimate_seconds=_BASE_ESTIMATE_SECONDS,
    )


@router.post("/clips/{clip_id}/sample", response_model=IterativeJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def sample_clip(
    clip_id: str,
    request: SampleRequest,
    current: CurrentUser = Depends(get_current_user),
) -> IterativeJobResponse:
    """Enqueue a sample-and-build of ``clip_id``'s ``[start, end]`` range; original preserved."""
    clip = await _owned_wav_clip(clip_id, current.user_id)
    # The worker only implements the ACE-Step backend; reject elevenlabs at
    # enqueue rather than silently producing ace-step output (the enum keeps the
    # value reserved for when the EL music path is wired into the worker).
    if request.backend is GenerationBackend.ELEVENLABS:
        raise _unprocessable("the 'elevenlabs' backend is not yet supported for sampling; use 'ace-step'.")
    duration_ms = _require_duration_ms(clip)
    start_ms = parse_time_string(request.start)
    end_ms = parse_time_string(request.end)
    _check_range(start_ms, end_ms, duration_ms, request.start, request.end, clip)
    params = {
        "clip_id": str(clip.id),
        "start_ms": start_ms,
        "end_ms": end_ms,
        "role": request.role.value,
        "prompt": request.prompt,
        "backend": request.backend.value,
        "num_clips": request.num_clips,
    }
    # Sample produces ``num_clips`` outputs, so it costs that many generations.
    cost = credits_service.get_cost(iterative_service.SAMPLE_JOB_TYPE) * request.num_clips
    return await _enqueue_generation(
        user_id=current.user_id,
        job_type=iterative_service.SAMPLE_JOB_TYPE,
        workspace_id=clip.workspace_id,
        params=params,
        cost=cost,
        estimate_seconds=_BASE_ESTIMATE_SECONDS * request.num_clips,
    )


@router.post("/clips/{clip_id}/add-vocal", response_model=IterativeJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def add_vocal_clip(
    clip_id: str,
    request: AddVocalRequest,
    current: CurrentUser = Depends(get_current_user),
) -> IterativeJobResponse:
    """Enqueue a vocal layering onto ``clip_id``; the original is preserved."""
    clip = await _owned_wav_clip(clip_id, current.user_id)
    params = {
        "clip_id": str(clip.id),
        "lyrics": request.lyrics,
        "voice_id": request.voice_id,
        "vocal_style": request.vocal_style,
    }
    return await _enqueue_generation(
        user_id=current.user_id,
        job_type=iterative_service.ADD_VOCAL_JOB_TYPE,
        workspace_id=clip.workspace_id,
        params=params,
        cost=credits_service.get_cost(iterative_service.ADD_VOCAL_JOB_TYPE),
        estimate_seconds=_BASE_ESTIMATE_SECONDS,
    )


# ---------------------------------------------------------------------------
# Multi-clip mashup endpoint
# ---------------------------------------------------------------------------


@router.post("/mashup", response_model=IterativeJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def mashup_clips(
    request: MashupRequest,
    current: CurrentUser = Depends(get_current_user),
) -> IterativeJobResponse:
    """Enqueue a mashup of 2+ owned clips into one; the originals are preserved.

    Lineage tracks every source (``parent_clip_ids``); the first clip is the
    primary, and the derived clip lands in its workspace.
    """
    # Validate every source up front so an unknown/unowned/non-wav id fails the
    # whole request (404/422) before any credit is touched.
    clips = [await _owned_wav_clip(clip_id, current.user_id) for clip_id in request.clip_ids]
    primary = clips[0]
    params = {
        "clip_ids": [str(clip.id) for clip in clips],
        "blend_mode": request.blend_mode.value,
        "style": request.style,
    }
    return await _enqueue_generation(
        user_id=current.user_id,
        job_type=iterative_service.MASHUP_JOB_TYPE,
        workspace_id=primary.workspace_id,
        params=params,
        cost=credits_service.get_cost(iterative_service.MASHUP_JOB_TYPE),
        estimate_seconds=_BASE_ESTIMATE_SECONDS,
    )
