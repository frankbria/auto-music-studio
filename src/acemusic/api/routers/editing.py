"""Audio editing endpoints (US-10.1), mounted under ``/api/v1/clips``.

* ``POST /clips/{id}/crop``     → trim to a time range (optional fades / beat-snap)
* ``POST /clips/{id}/speed``    → time-stretch by a multiplier or to a target BPM
* ``POST /clips/{id}/remaster`` → loudness-normalise to a target LUFS

Each endpoint validates the request against the source clip, persists a queued
:class:`~acemusic.api.models.job.Job` and returns 202 with a job id trackable
via ``GET /api/v1/jobs/{id}/status`` (mirrors ``POST /generate``). Editing is
non-generative local CPU work, so no credits are deducted.

Time parameters are human-readable strings ("10s", "1m30s", "5") parsed with
:func:`acemusic.utils.parse_time_string`, matching the CLI commands.
"""

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from acemusic.audio import calculate_speed_multiplier
from acemusic.utils import parse_time_string, snap_to_beat

from ..auth.dependencies import CurrentUser, get_current_user, require_existing_user
from ..models import Clip
from ..services import clips as clip_service, editing as editing_service

logger = logging.getLogger(__name__)

# Time-stretch quality degrades sharply outside this window (mirrors the CLI).
SPEED_MULTIPLIER_MIN = 0.5
SPEED_MULTIPLIER_MAX = 2.0

# Router-level dependency gates every route behind a valid Bearer token
# (mirrors the clips/generation routers), so unauthenticated requests get 401.
router = APIRouter(prefix="/clips", tags=["editing"], dependencies=[Depends(get_current_user)])


def _unprocessable(detail: str) -> HTTPException:
    """Clip-dependent validation failure (the body itself parsed fine)."""
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)


class CropRequest(BaseModel):
    """Trim spec. Times are strings ("10s", "1m30s", "5") like the CLI flags."""

    model_config = ConfigDict(extra="forbid")

    start: str
    end: str
    fade_in: str = "0s"
    fade_out: str = "0s"
    snap_to_beat: bool = False

    @field_validator("start", "end", "fade_in", "fade_out")
    @classmethod
    def _check_time_string(cls, value: str) -> str:
        # Surface unparseable values as field-level 422s; the handler re-parses
        # the (now guaranteed-valid) strings into milliseconds.
        parse_time_string(value)
        return value


class SpeedRequest(BaseModel):
    """Time-stretch spec: exactly one of ``multiplier`` or ``target_bpm``."""

    model_config = ConfigDict(extra="forbid")

    multiplier: float | None = Field(default=None, ge=SPEED_MULTIPLIER_MIN, le=SPEED_MULTIPLIER_MAX)
    target_bpm: float | None = Field(default=None, gt=0)
    preserve_pitch: bool = True

    @model_validator(mode="after")
    def _check_exactly_one(self) -> "SpeedRequest":
        if (self.multiplier is None) == (self.target_bpm is None):
            raise ValueError("provide either multiplier or target_bpm, not both")
        return self


class RemasterRequest(BaseModel):
    """Loudness-normalisation spec (defaults to the -14 LUFS streaming target)."""

    model_config = ConfigDict(extra="forbid")

    target_lufs: float = -14.0


class EditJobResponse(BaseModel):
    """The accepted-job acknowledgement returned with HTTP 202."""

    job_id: str
    status: Literal["queued"] = "queued"


def _require_wav(clip: Clip) -> None:
    """422 unless the clip's audio is wav.

    The editing pipeline can only round-trip wav: ``soundfile`` cannot write
    PCM_16 mp3/aac/opus and pydub needs ffmpeg (absent on the server) for
    compressed formats, so a non-wav job would only fail later in the worker
    with an opaque library error.
    """
    fmt = clip_service.native_format(clip)
    if fmt != "wav":
        raise _unprocessable(f"unsupported format {fmt!r} for editing; currently only wav is supported.")


def _require_duration_ms(clip: Clip) -> int:
    """The clip's duration in milliseconds, or 422 if the metadata is missing."""
    if clip.duration is None:
        raise _unprocessable(f"Clip {clip.id} has no duration metadata; cannot validate the edit.")
    return int(round(clip.duration * 1000))


async def _enqueue(clip: Clip, job_type: str, params: dict) -> EditJobResponse:
    job = await editing_service.create_edit_job(
        user_id=clip.user_id,
        workspace_id=clip.workspace_id,
        job_type=job_type,
        params={"clip_id": str(clip.id), **params},
    )
    return EditJobResponse(job_id=str(job.id))


@router.post("/{clip_id}/crop", response_model=EditJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def crop_clip(
    clip_id: str,
    request: CropRequest,
    current: CurrentUser = Depends(require_existing_user),
) -> EditJobResponse:
    """Enqueue a crop of ``clip_id`` to ``[start, end]``; the original is preserved."""
    clip = await clip_service.get_owned_clip(clip_id, current.user_id)
    _require_wav(clip)
    duration_ms = _require_duration_ms(clip)

    start_ms = parse_time_string(request.start)
    end_ms = parse_time_string(request.end)
    if request.snap_to_beat:
        if clip.bpm is None:
            raise _unprocessable(f"snap_to_beat requires BPM metadata on clip {clip.id}, but none is set.")
        start_ms = snap_to_beat(start_ms, clip.bpm)
        end_ms = snap_to_beat(end_ms, clip.bpm)

    if start_ms >= end_ms:
        if request.snap_to_beat:
            raise _unprocessable(
                f"after beat-snapping, start ({start_ms / 1000:.3f}s) is not less than end ({end_ms / 1000:.3f}s)."
            )
        raise _unprocessable(f"start ({request.start}) must be less than end ({request.end}).")
    if end_ms > duration_ms:
        raise _unprocessable(f"end ({request.end}) exceeds clip duration ({clip.duration:.1f}s).")

    return await _enqueue(
        clip,
        editing_service.CROP_JOB_TYPE,
        {
            "start_ms": start_ms,
            "end_ms": end_ms,
            "fade_in_ms": parse_time_string(request.fade_in),
            "fade_out_ms": parse_time_string(request.fade_out),
        },
    )


@router.post("/{clip_id}/speed", response_model=EditJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def speed_clip(
    clip_id: str,
    request: SpeedRequest,
    current: CurrentUser = Depends(require_existing_user),
) -> EditJobResponse:
    """Enqueue a pitch-preserving time-stretch of ``clip_id``; the original is preserved."""
    clip = await clip_service.get_owned_clip(clip_id, current.user_id)
    _require_wav(clip)
    # The derived clip's duration is source / multiplier, so the metadata must exist.
    _require_duration_ms(clip)

    if request.target_bpm is not None:
        if clip.bpm is None:
            raise _unprocessable(f"target_bpm requires BPM metadata on clip {clip.id}, but none is set.")
        multiplier = calculate_speed_multiplier(clip.bpm, request.target_bpm)
        if not (SPEED_MULTIPLIER_MIN <= multiplier <= SPEED_MULTIPLIER_MAX):
            raise _unprocessable(
                f"target BPM of {request.target_bpm} would require a rate of {multiplier:.4g}x, "
                f"which is outside the allowed range {SPEED_MULTIPLIER_MIN}-{SPEED_MULTIPLIER_MAX}."
            )
    else:
        multiplier = request.multiplier

    if not request.preserve_pitch:
        # The librosa phase vocoder always preserves pitch; the flag is accepted
        # for API-shape compatibility but cannot change the behaviour.
        logger.warning(
            "preserve_pitch=false requested for clip %s, but time-stretching always preserves pitch; ignoring.",
            clip.id,
        )

    return await _enqueue(
        clip,
        editing_service.SPEED_JOB_TYPE,
        {"multiplier": multiplier, "preserve_pitch": request.preserve_pitch},
    )


@router.post("/{clip_id}/remaster", response_model=EditJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def remaster_clip(
    clip_id: str,
    request: RemasterRequest,
    current: CurrentUser = Depends(require_existing_user),
) -> EditJobResponse:
    """Enqueue a remaster of ``clip_id`` to ``target_lufs``; the original is preserved."""
    clip = await clip_service.get_owned_clip(clip_id, current.user_id)
    _require_wav(clip)

    return await _enqueue(clip, editing_service.REMASTER_JOB_TYPE, {"target_lufs": request.target_lufs})
