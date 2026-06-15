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

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from acemusic.constants import DURATION_MAX, LYRICS_MAX_LENGTH, PROMPT_MAX_LENGTH, STYLE_MAX_LENGTH
from acemusic.song_structure import plan_sections
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
# Mashup does one DB lookup + download + mix per source at a flat 2-credit cost,
# so cap the source list to keep a single request's DB/storage/CPU work bounded.
_MAX_MASHUP_CLIPS = 8

# Free-text fields are persisted verbatim in Job.input_params / Clip.generation_params,
# so bound them (like the generation API) to keep a single oversized request from
# bloating a Mongo document or exhausting memory. voice_id is an identifier, so a
# small bound suffices; style/prompt/lyrics reuse the shared generation caps.
_VOICE_ID_MAX_LENGTH = 128

# Full-song (US-10.4): the seed must be a short idea, not an already-long track —
# the feature grows a clip *into* a song, so cap the seed and bound the section
# count (each section is one paid ACE-Step extend, so an unbounded list would let
# one request queue arbitrarily much GPU work).
_FULL_SONG_MAX_SEED_SECONDS = 60.0
_MAX_FULL_SONG_SECTIONS = 12

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
    style_override: str | None = Field(default=None, max_length=STYLE_MAX_LENGTH)
    lyrics: str | None = Field(default=None, max_length=LYRICS_MAX_LENGTH)

    @field_validator("duration")
    @classmethod
    def _check_duration(cls, value: str) -> str:
        # A zero-length extend is a no-op repaint that still charges a credit;
        # reject it (parse_time_string accepts "0"/"0s" as 0ms).
        if parse_time_string(value) <= 0:
            raise ValueError("duration must be greater than zero")
        return value

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

    style: str = Field(min_length=1, max_length=STYLE_MAX_LENGTH)
    voice_id: str | None = Field(default=None, max_length=_VOICE_ID_MAX_LENGTH)
    lyrics_override: str | None = Field(default=None, max_length=LYRICS_MAX_LENGTH)


class RemixRequest(BaseModel):
    """Style transfer (no explicit melody preservation; see Design Choice 2)."""

    model_config = ConfigDict(extra="forbid")

    style: str = Field(min_length=1, max_length=STYLE_MAX_LENGTH)


class RepaintRequest(BaseModel):
    """Regenerate the ``[start, end]`` range of a clip from ``prompt``."""

    model_config = ConfigDict(extra="forbid")

    start: str
    end: str
    prompt: str = Field(min_length=1, max_length=PROMPT_MAX_LENGTH)
    style: str | None = Field(default=None, max_length=STYLE_MAX_LENGTH)

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
    prompt: str = Field(min_length=1, max_length=PROMPT_MAX_LENGTH)
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

    lyrics: str = Field(min_length=1, max_length=LYRICS_MAX_LENGTH)
    voice_id: str | None = Field(default=None, max_length=_VOICE_ID_MAX_LENGTH)
    vocal_style: str | None = Field(default=None, max_length=STYLE_MAX_LENGTH)


class FullSongRequest(BaseModel):
    """Assemble a full song from a short seed by chaining one extend per section.

    ``structure_plan`` overrides the canonical intro→outro section list; each name
    must be a known section (validated against the seed at enqueue time). ``style``
    anchors every section's conditioning, and ``lyrics`` (if given) is applied to
    every section.
    """

    model_config = ConfigDict(extra="forbid")

    target_duration: int = Field(default=210, gt=0)
    structure_plan: list[str] | None = None
    style: str | None = Field(default=None, max_length=STYLE_MAX_LENGTH)
    lyrics: str | None = Field(default=None, max_length=LYRICS_MAX_LENGTH)

    @field_validator("structure_plan")
    @classmethod
    def _check_structure_plan(cls, value: list[str] | None) -> list[str] | None:
        # Section *names* are validated against the seed by plan_sections at
        # enqueue time (router), where a clear 422 can be raised; here we only
        # bound the shape (non-empty, within the section cap).
        if value is not None:
            if not value:
                raise ValueError("structure_plan must not be empty")
            if len(value) > _MAX_FULL_SONG_SECTIONS:
                raise ValueError(f"structure_plan may have at most {_MAX_FULL_SONG_SECTIONS} sections")
        return value


class MashupRequest(BaseModel):
    """Blend two or more clips into one. ``clip_ids[0]`` is the primary source."""

    model_config = ConfigDict(extra="forbid")

    clip_ids: list[str] = Field(min_length=2, max_length=_MAX_MASHUP_CLIPS)
    blend_mode: BlendMode = BlendMode.LAYERED
    style: str | None = Field(default=None, max_length=STYLE_MAX_LENGTH)

    @model_validator(mode="after")
    def _check_distinct(self) -> "MashupRequest":
        # Normalise before comparing: ObjectId hex is case-insensitive, so the
        # same id in different casing must still count as a duplicate (a raw
        # string set would treat them as distinct and let it through).
        def _norm(cid: str) -> str:
            try:
                return str(PydanticObjectId(cid))
            except Exception:
                return cid

        normalized = [_norm(cid) for cid in self.clip_ids]
        if len(set(normalized)) != len(normalized):
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


async def _owned_wav_clip(clip_id: str, user_id: str, *, cap_duration: bool = False) -> Clip:
    """Resolve a source clip the user owns and gate it to wav with duration.

    Every iterative mode feeds the source's duration to ACE-Step (as the target
    ``audio_duration`` or to bound a range), so a clip without duration metadata
    would be charged then fail or produce a duration-less derived clip — reject
    it here (404 unknown/unowned, then 422 non-wav / no-duration).

    ``cap_duration`` additionally rejects a source longer than ``DURATION_MAX``:
    the modes that submit ``source.duration`` verbatim as ``audio_duration``
    (cover/remix/repaint/add-vocal/mashup) would otherwise charge then queue a
    job that exceeds the generation cap. extend (which trims to a prefix) and
    sample (which works on a bounded range) don't set this.
    """
    clip = await clip_service.get_owned_clip(clip_id, user_id)
    _require_wav(clip)
    _require_duration_ms(clip)
    if cap_duration and clip.duration is not None and clip.duration > DURATION_MAX:
        raise _unprocessable(
            f"clip duration ({clip.duration:.1f}s) exceeds the maximum generation duration ({DURATION_MAX:.0f}s)."
        )
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
    # The worker needs the source duration for every extend (it splices the new
    # tail onto the existing audio), so require it before charging — otherwise a
    # clip without duration metadata would deduct a credit then fail in the worker.
    duration_ms = _require_duration_ms(clip)
    from_ms = duration_ms
    if request.from_point != "end":
        # The splice point must fall strictly inside the clip: 0 makes the worker
        # trim to a zero-length prefix (slice_audio raises), and past the end has
        # no audio to continue from. Mirrors the CLI's ``0 < t <= duration`` rule.
        from_ms = parse_time_string(request.from_point)
        if not (0 < from_ms <= duration_ms):
            raise _unprocessable(
                f"from_point ({request.from_point}) must be within the clip (0 < t <= {clip.duration:.1f}s)."
            )
    # The worker submits audio_duration = from_point + duration to ACE-Step;
    # cap that target at the platform's generation maximum so an extend can't
    # request an oversized GPU job at the flat one-credit cost.
    target_s = (from_ms + parse_time_string(request.duration)) / 1000.0
    if target_s > DURATION_MAX:
        raise _unprocessable(
            f"extended length ({target_s:.1f}s) exceeds the maximum generation duration ({DURATION_MAX:.0f}s)."
        )
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
    clip = await _owned_wav_clip(clip_id, current.user_id, cap_duration=True)
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
    clip = await _owned_wav_clip(clip_id, current.user_id, cap_duration=True)
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
    clip = await _owned_wav_clip(clip_id, current.user_id, cap_duration=True)
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
    clip = await _owned_wav_clip(clip_id, current.user_id, cap_duration=True)
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


@router.post("/clips/{clip_id}/full-song", response_model=IterativeJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def full_song(
    clip_id: str,
    request: FullSongRequest,
    current: CurrentUser = Depends(get_current_user),
) -> IterativeJobResponse:
    """Enqueue a full-song assembly of ``clip_id``; the seed is preserved.

    Grows a short seed into a ~target-duration song by chaining one paid extend
    per planned section, so credits scale with the section count.
    """
    clip = await _owned_wav_clip(clip_id, current.user_id)
    # _owned_wav_clip already 422s a clip without duration metadata; bind the
    # value so the planner is well-typed (and stay defensive if that changes).
    seed_duration = clip.duration
    if seed_duration is None:
        raise _unprocessable(f"Clip {clip.id} has no duration metadata; cannot plan a full song.")
    # The seed is a short idea to grow *into* a song; an already-long clip is a
    # misuse (and would blow past the per-section duration budget immediately).
    if seed_duration >= _FULL_SONG_MAX_SEED_SECONDS:
        raise _unprocessable(
            f"full-song requires a seed shorter than {_FULL_SONG_MAX_SEED_SECONDS:.0f}s "
            f"(clip is {seed_duration:.1f}s)."
        )
    # Each section's repaint submits audio_duration up to target_duration, so the
    # whole song must fit the backend's generation cap.
    if request.target_duration > DURATION_MAX:
        raise _unprocessable(
            f"target_duration ({request.target_duration}s) exceeds the maximum song length ({DURATION_MAX:.0f}s)."
        )
    # plan_sections enforces the remaining invariants against the actual seed:
    # target must exceed the seed, and every structure_plan name must be known.
    try:
        sections = plan_sections(seed_duration, request.target_duration, structure=request.structure_plan)
    except ValueError as exc:
        raise _unprocessable(str(exc)) from exc
    num_sections = len(sections)
    params = {
        "clip_id": str(clip.id),
        "target_duration": request.target_duration,
        "structure_plan": request.structure_plan,
        "style": request.style,
        "lyrics": request.lyrics,
    }
    # One paid extend per section (mirrors sample's per-output pricing).
    cost = credits_service.get_cost(iterative_service.FULL_SONG_JOB_TYPE) * num_sections
    return await _enqueue_generation(
        user_id=current.user_id,
        job_type=iterative_service.FULL_SONG_JOB_TYPE,
        workspace_id=clip.workspace_id,
        params=params,
        cost=cost,
        estimate_seconds=_BASE_ESTIMATE_SECONDS * num_sections,
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
    clips = [await _owned_wav_clip(clip_id, current.user_id, cap_duration=True) for clip_id in request.clip_ids]
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
