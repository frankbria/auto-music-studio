"""Batch processing endpoints (US-10.5), mounted under ``/api/v1/batch``.

* ``POST /batch/stems``  → queue stem separation for many clips at once
* ``POST /batch/export`` → queue audio export (wav/wav32/flac/mp3) for many clips
* ``GET  /batch/{id}/status`` → overall progress + per-clip status

Each request fans out into one sub-job per clip (an ordinary ``stems`` or
``export`` job) tracked under a :class:`~acemusic.api.models.batch_job.BatchJob`.
A clip that fails validation (unknown/not-owned, or non-wav) is recorded as a
failed sub-job rather than rejecting the whole request, so individual failures
never halt the batch (partial success). The 50-clip cap is enforced by Pydantic,
so an over-large request is a 422 before any work is queued.

These operations are non-generative local CPU work, so — like the single-clip
extraction endpoints — no credits are deducted.
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from acemusic.audio import EXPORT_FORMATS
from acemusic.storage import get_storage_backend

from ..auth.dependencies import CurrentUser, get_current_user
from ..models import BatchJob, Job, JobStatus
from ..services import batch as batch_service
from ..services.common import coerce_object_id

logger = logging.getLogger(__name__)

# Per-request cap (issue #85): more than this many clips is a 422.
MAX_BATCH_CLIPS = 50

# Router-level dependency gates every route behind a valid Bearer token (mirrors
# the extraction/jobs routers), so unauthenticated requests get 401.
router = APIRouter(prefix="/batch", tags=["batch"], dependencies=[Depends(get_current_user)])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class _BatchRequest(BaseModel):
    """Shared clip-list validation for batch requests."""

    model_config = ConfigDict(extra="forbid")

    clip_ids: list[str] = Field(min_length=1, max_length=MAX_BATCH_CLIPS)

    @model_validator(mode="after")
    def _distinct_clip_ids(self) -> "_BatchRequest":
        if len(set(self.clip_ids)) != len(self.clip_ids):
            raise ValueError("clip_ids must be distinct")
        return self


class BatchStemsRequest(_BatchRequest):
    """Body for ``POST /batch/stems``."""


class BatchExportRequest(_BatchRequest):
    """Body for ``POST /batch/export``."""

    format: str

    @field_validator("format")
    @classmethod
    def _supported_format(cls, value: str) -> str:
        if value not in EXPORT_FORMATS:
            raise ValueError(f"unsupported format {value!r}; expected one of {sorted(EXPORT_FORMATS)}")
        return value


class BatchJobCreated(BaseModel):
    """The accepted-batch acknowledgement returned with HTTP 202."""

    batch_job_id: str
    sub_job_ids: list[str]


class SubJobStatus(BaseModel):
    """One clip's status within a batch (result fields populated when relevant)."""

    clip_id: str
    job_id: str | None = None
    status: str
    error: str | None = None
    # Stems sub-jobs produce stem clip ids; export sub-jobs produce a file URL.
    clip_ids: list[str] | None = None
    download_url: str | None = None


class BatchStatus(BaseModel):
    """Overall batch progress with a per-clip breakdown."""

    batch_job_id: str
    operation: str
    overall_status: str
    overall_progress: float
    total: int
    completed_count: int
    failed_count: int
    sub_jobs: list[SubJobStatus]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


def _created(batch: BatchJob) -> BatchJobCreated:
    return BatchJobCreated(
        batch_job_id=str(batch.id),
        sub_job_ids=[e.job_id for e in batch.entries if e.job_id is not None],
    )


@router.post("/stems", response_model=BatchJobCreated, status_code=status.HTTP_202_ACCEPTED)
async def batch_stems(
    request: BatchStemsRequest,
    current: CurrentUser = Depends(get_current_user),
) -> BatchJobCreated:
    """Queue stem separation for every clip in ``clip_ids``."""
    batch = await batch_service.create_batch(
        user_id=current.user_id,
        operation=batch_service.BATCH_STEMS_OPERATION,
        clip_ids=request.clip_ids,
    )
    return _created(batch)


@router.post("/export", response_model=BatchJobCreated, status_code=status.HTTP_202_ACCEPTED)
async def batch_export(
    request: BatchExportRequest,
    current: CurrentUser = Depends(get_current_user),
) -> BatchJobCreated:
    """Queue audio export of every clip in ``clip_ids`` to ``format``."""
    batch = await batch_service.create_batch(
        user_id=current.user_id,
        operation=batch_service.BATCH_EXPORT_OPERATION,
        clip_ids=request.clip_ids,
        format=request.format,
    )
    return _created(batch)


async def _sub_job_status(entry, operation: str) -> SubJobStatus:
    """Resolve one entry to its current status (live for real sub-jobs)."""
    if entry.job_id is None:
        # Request-time validation failure: terminal failure, no live job.
        return SubJobStatus(clip_id=entry.clip_id, status=JobStatus.FAILED.value, error=entry.error)

    job = await Job.get(coerce_object_id(entry.job_id))
    if job is None:
        # The sub-job vanished (e.g. owner-deleted); report it as failed rather
        # than crashing the whole status read.
        return SubJobStatus(
            clip_id=entry.clip_id,
            job_id=entry.job_id,
            status=JobStatus.FAILED.value,
            error="Sub-job no longer exists.",
        )

    sub = SubJobStatus(clip_id=entry.clip_id, job_id=entry.job_id, status=job.status.value)
    if job.status == JobStatus.FAILED:
        sub.error = job.error
    elif job.status == JobStatus.COMPLETED:
        result = job.result or {}
        if operation == batch_service.BATCH_EXPORT_OPERATION:
            export_path = result.get("export_path")
            if export_path:
                storage = get_storage_backend()
                sub.download_url = await asyncio.to_thread(storage.get_url, export_path)
        else:
            sub.clip_ids = list(result.get("clip_ids", []))
    return sub


def _overall_status(*, total: int, completed: int, failed: int) -> str:
    """Aggregate verdict: running wins, then all-completed / all-failed / mixed."""
    if completed + failed < total:
        return JobStatus.PROCESSING.value
    if failed == total:
        return JobStatus.FAILED.value
    if completed == total:
        return JobStatus.COMPLETED.value
    return "partial_success"


@router.get("/{batch_id}/status", response_model=BatchStatus, response_model_exclude_none=True)
async def get_batch_status(
    batch_id: str,
    current: CurrentUser = Depends(get_current_user),
) -> BatchStatus:
    """Return overall progress and per-clip status for ``batch_id`` (404 otherwise).

    Owner-scoped: a batch that does not exist *or* belongs to another user yields
    404, so the endpoint never reveals another user's batches.
    """
    oid = coerce_object_id(batch_id)
    batch = await BatchJob.get(oid) if oid is not None else None
    if batch is None or str(batch.user_id) != current.user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Batch not found.")

    sub_jobs = [await _sub_job_status(entry, batch.operation) for entry in batch.entries]
    total = len(sub_jobs)
    completed = sum(1 for s in sub_jobs if s.status == JobStatus.COMPLETED.value)
    failed = sum(1 for s in sub_jobs if s.status == JobStatus.FAILED.value)
    # Guard against an empty batch (not reachable via the API — min_length=1 —
    # but keeps the math total-safe).
    progress = (completed + failed) / total if total else 1.0

    return BatchStatus(
        batch_job_id=str(batch.id),
        operation=batch.operation,
        overall_status=_overall_status(total=total, completed=completed, failed=failed),
        overall_progress=progress,
        total=total,
        completed_count=completed,
        failed_count=failed,
        sub_jobs=sub_jobs,
    )
