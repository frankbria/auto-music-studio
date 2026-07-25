"""Music-video generation endpoints (US-22.1).

``POST /api/v1/videos/generate`` accepts a source song plus visual rendering
options, then enqueues a credit-bearing video job and returns 202 with a
trackable job id. ``GET /api/v1/videos/{job_id}/status`` reports the render's
progress in the video vocabulary (queued/rendering/encoding/complete/failed)
with a progress percentage and estimated time remaining.

The credit-gate flow mirrors the mastering endpoint (this is a paid operation):
the source clip is validated for ownership first (404 before any charge), the
resolution/duration-tiered cost is deducted atomically, a job-creation failure
refunds, and the ledger write is best-effort.
"""

import logging
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..auth.dependencies import CurrentUser, get_current_user
from ..models import JobStatus
from ..services import (
    clips as clip_service,
    credits as credits_service,
    users as user_service,
    video as video_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/videos", tags=["videos"], dependencies=[Depends(get_current_user)])

# US-22.2's page uploads up to 5 reference images to guide the visual style.
_MAX_REFERENCE_IMAGES = 5

# US-22.1's status vocabulary. Job.status covers the endpoints of the lifecycle;
# the rendering/encoding middle states come from the provider via progress_detail.
VideoState = Literal["queued", "rendering", "encoding", "complete", "failed"]
_PROVIDER_STATES = ("rendering", "encoding")


class VideoGenerationRequest(BaseModel):
    """A video submission: a source song plus visual rendering options.

    ``extra="forbid"`` rejects unknown keys with 422 (a client typo surfaces
    instead of being silently dropped). At least a free-form style prompt or a
    preset is required — there is nothing to render from otherwise (mirrors the
    US-22.2 page, whose Generate button stays disabled until one is chosen).
    """

    model_config = ConfigDict(extra="forbid")

    clip_id: str
    prompt: str | None = None
    style_preset: Literal["abstract", "cinematic", "animated", "lyric_video", "live_performance", "nature"] | None = (
        None
    )
    reference_image_urls: list[str] = Field(default_factory=list, max_length=_MAX_REFERENCE_IMAGES)
    lyrics_sync: bool = False
    aspect_ratio: Literal["16:9", "9:16", "1:1"] = "16:9"
    resolution: Literal["720p", "1080p", "4k"] = "720p"
    frame_rate: Literal[24, 30, 60] = 30
    transitions: Literal["auto", "cut", "fade", "dissolve"] = "auto"

    @model_validator(mode="after")
    def _check_style(self) -> "VideoGenerationRequest":
        if not self.prompt and self.style_preset is None:
            raise ValueError("Provide a style prompt or a style_preset")
        return self


class VideoJobResponse(BaseModel):
    """The accepted-job acknowledgement returned with HTTP 202."""

    job_id: str
    status: Literal["queued"] = "queued"


class VideoStatusResponse(BaseModel):
    """A video job's live rendering state, progress and (once complete) its video.

    ``response_model_exclude_none`` drops the result fields until they apply:
    ``video_id`` appears only on completion, ``error`` only on failure.
    """

    job_id: str
    status: VideoState
    progress: int  # 0-100
    eta_seconds: float | None = None
    video_id: str | None = None
    error: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


@router.post("/generate", response_model=VideoJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_video_job(
    request: VideoGenerationRequest,
    # The router-level dependency already gates auth; declaring it here too gives
    # the handler the resolved CurrentUser (FastAPI dedupes per request).
    current: CurrentUser = Depends(get_current_user),
) -> VideoJobResponse:
    """Validate the song, charge credits, and enqueue a queued video job.

    Pydantic returns 422 for invalid bodies and the router dependency returns 401
    for missing/invalid tokens — both before this runs. Raises 404 (stale token
    or unknown/unowned clip) and 402 (insufficient credits).
    """
    user = await user_service.get_user_by_id(current.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    # Validate ownership before charging: an unknown/unowned clip yields a clean
    # 404 with no credit movement. The clip's workspace is where the video lands.
    clip = await clip_service.get_owned_clip(request.clip_id, current.user_id)

    cost = credits_service.get_video_cost(request.resolution, clip.duration)
    balance_after = await credits_service.deduct_credits(user.id, cost)
    if balance_after is None:
        # Re-read the balance for the error payload: the copy on ``user`` was
        # loaded before the deduction attempt and may be stale under concurrency.
        fresh = await user_service.get_user_by_id(user.id)
        balance = fresh.credits_balance if fresh is not None else 0.0
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={"error": "insufficient_credits", "balance": balance, "required": cost},
        )

    try:
        params = {
            "clip_id": str(clip.id),
            "prompt": request.prompt,
            "style_preset": request.style_preset,
            "reference_image_urls": request.reference_image_urls,
            "lyrics_sync": request.lyrics_sync,
            "aspect_ratio": request.aspect_ratio,
            "resolution": request.resolution,
            "frame_rate": request.frame_rate,
            "transitions": request.transitions,
        }
        job = await video_service.create_video_job(
            user_id=user.id,
            workspace_id=clip.workspace_id,
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
            action_type=video_service.VIDEO_JOB_TYPE,
            job_id=str(job.id),
            balance_after=balance_after,
        )
    except Exception:
        # The charge is taken and the job dispatched; failing here would invite a
        # retry that double-charges. The ledger row is best-effort history.
        logger.exception("Credit ledger write failed for job %s (user %s)", job.id, user.id)
    return VideoJobResponse(job_id=str(job.id))


@router.get("/{job_id}/status", response_model=VideoStatusResponse, response_model_exclude_none=True)
async def get_video_job_status(
    job_id: str,
    current: CurrentUser = Depends(get_current_user),
) -> VideoStatusResponse:
    """Report the render's state, progress % and ETA (404 for unknown/unowned).

    Maps the platform's 4-state job lifecycle plus the provider's
    ``progress_detail`` onto the video vocabulary: a ``processing`` job surfaces
    the provider's rendering/encoding state, and the endpoints of the lifecycle
    (queued/complete/failed) come from the job itself.
    """
    job = await video_service.get_video_job(job_id, current.user_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video job not found.")

    detail = job.progress_detail or {}
    progress = detail.get("progress")
    eta_seconds = detail.get("eta_seconds")
    video_id: str | None = None
    error: str | None = None

    if job.status == JobStatus.QUEUED:
        state: VideoState = "queued"
        progress = 0
    elif job.status == JobStatus.COMPLETED:
        state = "complete"
        progress = 100
        eta_seconds = None
        video_ids = (job.result or {}).get("video_ids") or []
        video_id = video_ids[0] if video_ids else None
    elif job.status == JobStatus.FAILED:
        state = "failed"
        error = job.error
        eta_seconds = None
    else:  # PROCESSING: the provider owns the fine-grained state.
        raw = detail.get("state")
        state = raw if raw in _PROVIDER_STATES else "rendering"

    return VideoStatusResponse(
        job_id=str(job.id),
        status=state,
        progress=int(progress) if progress is not None else 0,
        eta_seconds=eta_seconds,
        video_id=video_id,
        error=error,
        created_at=job.created_at,
        completed_at=job.completed_at,
    )
