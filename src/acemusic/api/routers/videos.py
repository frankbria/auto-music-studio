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

import asyncio
import logging
import secrets
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from acemusic.storage import get_storage_backend

from ..auth.dependencies import CurrentUser, get_current_user, get_current_user_optional
from ..models import JobStatus, Video
from ..services import (
    clips as clip_service,
    credits as credits_service,
    users as user_service,
    video as video_service,
)
from ..services.clips import get_clip_for_streaming
from ..settings import ApiSettings
from ..utils.range_requests import build_multipart_ranges_response, parse_range_header_multi
from ..utils.rate_limit import enforce_stream_rate_limit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/videos", tags=["videos"], dependencies=[Depends(get_current_user)])

# Delivery reads (metadata/playback) must open for the public song page, so they
# live on a separate router WITHOUT the router-level auth gate — mirrors the
# clips ``stream_router``. Each route resolves visibility per request instead.
public_router = APIRouter(prefix="/videos", tags=["videos"])

# Rendered videos are always MP4 (the worker uploads ``{job_id}.mp4``).
_VIDEO_MEDIA_TYPE = "video/mp4"

# US-22.2's page uploads up to 5 reference images to guide the visual style.
_MAX_REFERENCE_IMAGES = 5

# Bounds on user-supplied text forwarded to the provider: the prompt cap matches
# the artwork router's; reference URLs must be web URLs (a file:// or
# metadata-service URL would turn the provider into an SSRF proxy) of sane length.
_PROMPT_MAX_LENGTH = 2000
_REFERENCE_URL_MAX_LENGTH = 2048


def _settings(request: Request) -> ApiSettings:
    return request.app.state.settings


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
    prompt: str | None = Field(default=None, max_length=_PROMPT_MAX_LENGTH)
    style_preset: Literal["abstract", "cinematic", "animated", "lyric_video", "live_performance", "nature"] | None = (
        None
    )
    reference_image_urls: list[str] = Field(default_factory=list, max_length=_MAX_REFERENCE_IMAGES)
    lyrics_sync: bool = False
    aspect_ratio: Literal["16:9", "9:16", "1:1"] = "16:9"
    resolution: Literal["720p", "1080p", "4k"] = "720p"
    frame_rate: Literal[24, 30, 60] = 30
    transitions: Literal["auto", "cut", "fade", "dissolve"] = "auto"

    @field_validator("reference_image_urls")
    @classmethod
    def _check_reference_urls(cls, urls: list[str]) -> list[str]:
        for url in urls:
            if len(url) > _REFERENCE_URL_MAX_LENGTH:
                raise ValueError(f"Reference image URLs must be at most {_REFERENCE_URL_MAX_LENGTH} characters")
            if not url.startswith(("http://", "https://")):
                raise ValueError("Reference image URLs must be http(s) URLs")
        return urls

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
    settings: ApiSettings = Depends(_settings),
) -> VideoJobResponse:
    """Validate the song, charge credits, and enqueue a queued video job.

    Pydantic returns 422 for invalid bodies and the router dependency returns 401
    for missing/invalid tokens — both before this runs. Raises 503 (provider not
    configured), 404 (stale token or unknown/unowned clip) and 402 (insufficient
    credits).
    """
    # Gate BEFORE any charge: settings are process-static, so an unconfigured
    # deployment would otherwise take the credits and then have the worker fail
    # every claimed job with "not configured" — a guaranteed charge for nothing.
    if not settings.video_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Video generation is not configured on this deployment.",
        )

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


# ---------------------------------------------------------------------------
# US-22.3 delivery: metadata, playback/download, publish
# ---------------------------------------------------------------------------


class VideoDetailResponse(BaseModel):
    """A rendered video's metadata (its bytes come from ``/stream``)."""

    id: str
    clip_id: str
    job_id: str
    resolution: str
    aspect_ratio: str
    published: bool
    created_at: datetime

    @classmethod
    def from_video(cls, video: Video) -> "VideoDetailResponse":
        return cls(
            id=str(video.id),
            clip_id=str(video.clip_id),
            job_id=str(video.job_id),
            resolution=video.resolution,
            aspect_ratio=video.aspect_ratio,
            published=video.published,
            created_at=video.created_at,
        )


async def _resolve_viewable_video(video_id: str, viewer_id: str | None) -> Video:
    """Return the video if the viewer may see it, else raise 404.

    The owner always may. Everyone else may only see it once it is *published*,
    and then only if they could view the source clip anyway
    (:func:`get_clip_for_streaming` enforces the clip's own visibility — private
    clips 404 for strangers). An unpublished, unowned video is an
    indistinguishable 404 so its existence never leaks.
    """
    video = await video_service.get_video_by_id(video_id)
    if video is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found.")
    if viewer_id is not None and str(video.user_id) == viewer_id:
        return video
    if not video.published:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found.")
    # Published: defer to the clip's visibility rules (may 404/403 for strangers).
    await get_clip_for_streaming(str(video.clip_id), viewer_id)
    return video


@router.post("/{video_id}/publish", response_model=VideoDetailResponse)
async def publish_video(
    video_id: str,
    current: CurrentUser = Depends(get_current_user),
) -> VideoDetailResponse:
    """Publish the owner's rendered video so it appears on the song detail page.

    Owner-scoped and idempotent: an unknown or unowned id is a 404 (never
    reveals another user's video), and re-publishing an already-published video
    simply returns its current state.
    """
    video = await video_service.publish_video(video_id, current.user_id)
    if video is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found.")
    return VideoDetailResponse.from_video(video)


@public_router.get("/for-clip/{clip_id}", response_model=VideoDetailResponse)
async def get_published_video_for_clip(
    clip_id: str,
    current: CurrentUser | None = Depends(get_current_user_optional),
) -> VideoDetailResponse:
    """Return the published video for a clip (backs the song page), else 404.

    Anonymous callers may reach it for a public/unlisted clip; a private-or-
    unknown clip is an indistinguishable 404, and a viewable clip with no
    published video is a 404 too (the page simply shows no video section).
    """
    viewer_id = current.user_id if current else None
    # Enforce the clip's own visibility first (404/403 for strangers on private).
    await get_clip_for_streaming(clip_id, viewer_id)
    video = await video_service.get_published_video_for_clip(clip_id)
    if video is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found.")
    return VideoDetailResponse.from_video(video)


@public_router.get("/{video_id}", response_model=VideoDetailResponse)
async def get_video(
    video_id: str,
    current: CurrentUser | None = Depends(get_current_user_optional),
) -> VideoDetailResponse:
    """Return a rendered video's metadata (owner always; others once published)."""
    video = await _resolve_viewable_video(video_id, current.user_id if current else None)
    return VideoDetailResponse.from_video(video)


@public_router.get("/{video_id}/stream", dependencies=[Depends(enforce_stream_rate_limit)])
async def stream_video(
    video_id: str,
    request: Request,
    download: bool = Query(default=False, description="Serve as a file download (Content-Disposition: attachment)."),
    current: CurrentUser | None = Depends(get_current_user_optional),
) -> Response:
    """Stream the rendered MP4 with seeking support (206 on Range), or download it.

    Same visibility rules as :func:`get_video`. Honors single- and multi-range
    requests so the ``<video>`` element can seek; ``?download=1`` forces a
    save-to-disk response for the Download button.
    """
    video = await _resolve_viewable_video(video_id, current.user_id if current else None)

    storage = get_storage_backend()
    try:
        data = await asyncio.to_thread(storage.download, video.storage_path)
    except FileNotFoundError:
        # The document exists but its object is gone — a data-integrity problem
        # worth logging, surfaced to the client as a plain 404.
        logger.warning("Video %s exists but its object %r is missing", video.id, video.storage_path)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video file not found.")

    cache_control = "public, max-age=3600" if video.published else "private, no-store"
    headers = {"Accept-Ranges": "bytes", "Cache-Control": cache_control}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="video-{video.id}.mp4"'

    range_header = request.headers.get("range")
    if range_header is not None:
        ranges = parse_range_header_multi(range_header, len(data))  # raises 416 if all unsatisfiable
        if ranges is not None and len(ranges) == 1:
            start, end = ranges[0]
            headers["Content-Range"] = f"bytes {start}-{end}/{len(data)}"
            return Response(
                content=data[start : end + 1],
                status_code=status.HTTP_206_PARTIAL_CONTENT,
                media_type=_VIDEO_MEDIA_TYPE,
                headers=headers,
            )
        if ranges is not None:
            boundary = secrets.token_hex(16)
            body, multipart_type = build_multipart_ranges_response(data, ranges, _VIDEO_MEDIA_TYPE, boundary)
            return Response(
                content=body,
                status_code=status.HTTP_206_PARTIAL_CONTENT,
                media_type=multipart_type,
                headers=headers,
            )

    return Response(content=data, media_type=_VIDEO_MEDIA_TYPE, headers=headers)
