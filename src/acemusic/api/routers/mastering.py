"""Mastering job submission endpoint (US-12.1).

``POST /api/v1/mastering/jobs`` accepts a source clip, a mastering profile, and
an optional service/format, then enqueues a credit-bearing mastering job and
returns 202 with a trackable job id.

The credit-gate flow mirrors the generation/iterative endpoints (these are paid
operations): the source clip is validated for ownership first (404 before any
charge), the per-service cost is deducted atomically (the concurrency guard), a
job-creation failure refunds, and the ledger write is best-effort. The actual
mastering work is a future ticket — the processor only claims registered
``job_type``s, so submitted jobs queue safely until then.
"""

import asyncio
import logging
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, model_validator

from acemusic.storage import get_storage_backend

from ..auth.dependencies import CurrentUser, get_current_user
from ..models import Clip, JobStatus
from ..services import (
    clips as clip_service,
    credits as credits_service,
    mastering as mastering_service,
    users as user_service,
)
from ..services.common import coerce_object_id

logger = logging.getLogger(__name__)

# Custom LUFS targets share the remaster bounds: anything above -5 or below -70
# is a client error, not a master (see editing.RemasterRequest).
_CUSTOM_LUFS_MIN = -70.0
_CUSTOM_LUFS_MAX = -5.0

router = APIRouter(prefix="/mastering", tags=["mastering"], dependencies=[Depends(get_current_user)])


class MasteringRequest(BaseModel):
    """A mastering submission: a source clip plus a target profile.

    ``extra="forbid"`` rejects unknown keys with 422 (a client typo surfaces
    instead of being silently dropped). ``target_lufs`` is required for the
    ``custom`` profile and forbidden for the standard profiles, which own their
    own loudness target.
    """

    model_config = ConfigDict(extra="forbid")

    clip_id: str
    profile: Literal["streaming", "soundcloud", "club", "vinyl", "custom"]
    service: Literal["dolby", "landr", "bakuage"] = "dolby"
    format: Literal["wav", "mp3", "flac"] = "wav"
    target_lufs: float | None = None

    @model_validator(mode="after")
    def _check_target_lufs(self) -> "MasteringRequest":
        if self.profile == "custom":
            if self.target_lufs is None:
                raise ValueError("target_lufs is required when profile is 'custom'")
            if not (_CUSTOM_LUFS_MIN <= self.target_lufs <= _CUSTOM_LUFS_MAX):
                raise ValueError(f"target_lufs must be between {_CUSTOM_LUFS_MIN} and {_CUSTOM_LUFS_MAX} dB")
        elif self.target_lufs is not None:
            raise ValueError("target_lufs is only allowed when profile is 'custom'")
        return self


class MasteringJobResponse(BaseModel):
    """The accepted-job acknowledgement returned with HTTP 202."""

    job_id: str
    status: Literal["queued"] = "queued"


@router.post("/jobs", response_model=MasteringJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_mastering_job(
    request: MasteringRequest,
    # The router-level dependency already gates auth; declaring it here too gives
    # the handler the resolved CurrentUser. FastAPI dedupes by callable per
    # request, so get_current_user runs once (mirrors the iterative router).
    current: CurrentUser = Depends(get_current_user),
) -> MasteringJobResponse:
    """Validate the clip, charge credits, and enqueue a queued mastering job.

    Pydantic returns 422 for invalid bodies and the router dependency returns 401
    for missing/invalid tokens — both before this runs. Raises 404 (stale token
    or unknown/unowned clip) and 402 (insufficient credits).
    """
    user = await user_service.get_user_by_id(current.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    # Validate ownership before charging: an unknown/unowned clip yields a clean
    # 404 with no credit movement. The clip's workspace is where the master lands.
    clip = await clip_service.get_owned_clip(request.clip_id, current.user_id)

    cost = credits_service.get_mastering_cost(request.service)
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
        # Everything after the deduction lives inside the refund guard so the
        # "charged ⇒ either a job exists or the credit is returned" invariant
        # holds structurally, not just because resolve_target_lufs happens to be
        # unreachable today (the Literal profile is Pydantic-validated upstream).
        target_lufs = mastering_service.resolve_target_lufs(request.profile, request.target_lufs)
        params = {
            "clip_id": str(clip.id),
            "profile": request.profile,
            "service": request.service,
            "format": request.format,
            "target_lufs": target_lufs,
        }
        job = await mastering_service.create_mastering_job(
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
            action_type=mastering_service.MASTERING_JOB_TYPE,
            job_id=str(job.id),
            balance_after=balance_after,
        )
    except Exception:
        # The charge is taken and the job dispatched; failing here would invite a
        # retry that double-charges. The ledger row is best-effort history.
        logger.exception("Credit ledger write failed for job %s (user %s)", job.id, user.id)
    return MasteringJobResponse(job_id=str(job.id))


# ---------------------------------------------------------------------------
# Preview / A/B comparison and approval (US-12.4)
#
# The mastering pipeline produces ONE mastered clip per job (US-12.2), so a source
# clip's "previews" are the mastered children of its completed mastering jobs (one
# per job). The detail endpoint exposes a single job; the previews endpoint
# aggregates every candidate for the source for side-by-side comparison against
# the original; approval promotes a chosen candidate to the final master.
# ---------------------------------------------------------------------------


# The musician auditions a bounded set (US-12.4: "up to 5 preview variants"); a
# frequently-remastered source can have more completed candidates, so the previews
# view shows the most recent few. Approval still accepts any historical candidate.
_MAX_PREVIEW_VARIANTS = 5


def _job_not_found() -> HTTPException:
    """A mastering job that is missing, not owned, or not a mastering job (→ 404)."""
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mastering job not found.")


def _loudness_delta(metrics: dict | None, original_metrics: dict | None) -> float | None:
    """Mastered-minus-original integrated loudness (dB), or None if either is absent.

    The one metric measurable on both sides (the source has no per-band EQ/stereo
    analysis), so it is the A/B "metrics diff" the comparison view can report.
    """
    if not metrics or not original_metrics:
        return None
    mastered = metrics.get("loudness")
    original = original_metrics.get("loudness")
    if mastered is None or original is None:
        return None
    return round(mastered - original, 2)


class MasteringJobDetailResponse(BaseModel):
    """A mastering job's status and (once complete) its mastered output + metrics.

    ``response_model_exclude_none`` drops the result fields until the job
    completes: ``mastered_clip_id``/``metrics`` appear only when there is a master.
    """

    job_id: str
    status: JobStatus
    source_clip_id: str | None = None
    profile: str | None = None
    service: str | None = None
    target_lufs: float | None = None
    created_at: datetime
    completed_at: datetime | None = None
    mastered_clip_id: str | None = None
    metrics: dict | None = None
    error: str | None = None


class PreviewItem(BaseModel):
    """One mastered candidate: its audio URL and the backend's loudness/EQ metrics."""

    preview_id: str
    audio_url: str
    profile: str | None = None
    service: str | None = None
    metrics: dict | None = None
    # Mastered-minus-original integrated loudness (dB); the A/B metrics diff. None
    # when either side's loudness is unavailable.
    loudness_delta: float | None = None


class PreviewsResponse(BaseModel):
    """A/B comparison set: the original plus every mastered candidate for the source.

    ``original_metrics`` is the source's on-demand loudness measurement (``loudness``
    only — the unmastered source has no per-band EQ/stereo analysis).
    """

    source_clip_id: str | None = None
    original_audio_url: str | None = None
    # ``None`` when the source is missing/unowned or its loudness can't be measured;
    # otherwise ``{"loudness": <LUFS>}`` (loudness-only by design).
    original_metrics: dict | None = None
    previews: list[PreviewItem]


class ApproveRequest(BaseModel):
    """Approval body: the preview (mastered clip) id to promote to the final master."""

    model_config = ConfigDict(extra="forbid")

    preview_id: str


class ApproveResponse(BaseModel):
    """The promoted master's clip id and a retrievable audio URL."""

    clip_id: str
    audio_url: str


@router.get(
    "/jobs/{job_id}",
    response_model=MasteringJobDetailResponse,
    response_model_exclude_none=True,
)
async def get_mastering_job_detail(
    job_id: str,
    current: CurrentUser = Depends(get_current_user),
) -> MasteringJobDetailResponse:
    """Return a mastering job's status, parameters, and (when complete) its master."""
    job = await mastering_service.get_mastering_job(job_id, current.user_id)
    if job is None:
        raise _job_not_found()
    params = job.input_params or {}
    result = job.result or {}
    clip_ids = result.get("clip_ids") or []
    return MasteringJobDetailResponse(
        job_id=str(job.id),
        status=job.status,
        source_clip_id=params.get("clip_id"),
        profile=params.get("profile"),
        # The service that actually ran (a fallback may differ from the request).
        service=result.get("service") or params.get("service"),
        target_lufs=params.get("target_lufs"),
        created_at=job.created_at,
        completed_at=job.completed_at,
        mastered_clip_id=clip_ids[0] if clip_ids else None,
        metrics=result.get("metrics"),
        error=job.error,
    )


@router.get("/jobs/{job_id}/previews", response_model=PreviewsResponse)
async def get_mastering_previews(
    job_id: str,
    current: CurrentUser = Depends(get_current_user),
) -> PreviewsResponse:
    """A/B data for the job's source: original audio + loudness, and every candidate."""
    job = await mastering_service.get_mastering_job(job_id, current.user_id)
    if job is None:
        raise _job_not_found()
    source_clip_id = (job.input_params or {}).get("clip_id")
    storage = get_storage_backend()

    original_audio_url: str | None = None
    original_metrics: dict | None = None
    oid = coerce_object_id(source_clip_id) if source_clip_id else None
    source = await Clip.get(oid) if oid is not None else None
    if source is not None and str(source.user_id) == current.user_id:
        original_audio_url = await asyncio.to_thread(storage.get_url, source.file_path)
        loudness = await mastering_service.measure_clip_loudness(storage, source)
        # Omit the metrics object entirely when unmeasurable rather than emitting a
        # partial ``{"loudness": null}`` — callers see "no original metrics", not a
        # present-but-null interior field.
        original_metrics = {"loudness": loudness} if loudness is not None else None

    previews: list[PreviewItem] = []
    candidate_jobs = await mastering_service.list_source_previews(source_clip_id, current.user_id)
    # list_source_previews is oldest-first; show the most recent variants.
    for candidate_job in candidate_jobs[-_MAX_PREVIEW_VARIANTS:]:
        result = candidate_job.result or {}
        clip_ids = result.get("clip_ids") or []
        if not clip_ids:
            continue
        clip_oid = coerce_object_id(clip_ids[0])
        clip = await Clip.get(clip_oid) if clip_oid is not None else None
        if clip is None:
            continue
        metrics = result.get("metrics")
        previews.append(
            PreviewItem(
                preview_id=clip_ids[0],
                audio_url=await asyncio.to_thread(storage.get_url, clip.file_path),
                profile=(candidate_job.input_params or {}).get("profile"),
                service=result.get("service"),
                metrics=metrics,
                loudness_delta=_loudness_delta(metrics, original_metrics),
            )
        )

    return PreviewsResponse(
        source_clip_id=source_clip_id,
        original_audio_url=original_audio_url,
        original_metrics=original_metrics,
        previews=previews,
    )


@router.post("/jobs/{job_id}/approve", response_model=ApproveResponse)
async def approve_mastering_preview(
    job_id: str,
    request: ApproveRequest,
    current: CurrentUser = Depends(get_current_user),
) -> ApproveResponse:
    """Promote a preview to the final master; returns its clip id and audio URL."""
    job = await mastering_service.get_mastering_job(job_id, current.user_id)
    if job is None:
        raise _job_not_found()
    try:
        clip = await mastering_service.approve_preview(job, request.preview_id, current.user_id)
    except mastering_service.PreviewNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    audio_url = await asyncio.to_thread(get_storage_backend().get_url, clip.file_path)
    return ApproveResponse(clip_id=str(clip.id), audio_url=audio_url)
