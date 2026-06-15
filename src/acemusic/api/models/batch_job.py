"""Batch-job document model (US-10.5).

A :class:`BatchJob` groups the per-clip sub-jobs spawned by a single batch
request (``POST /batch/stems`` or ``POST /batch/export``) so their overall
progress can be tracked. It lives in its own ``batch_jobs`` collection — never
the ``jobs`` collection — because the :class:`~acemusic.api.tasks.processor.JobProcessor`
claims any queued document in ``jobs`` whose ``job_type`` is registered, and a
batch parent has no handler and must not be claimed.

Each :class:`BatchClipEntry` records one requested clip. ``job_id`` points at the
real sub-:class:`~acemusic.api.models.job.Job` created for that clip; it is
``None`` when the clip failed request-time validation (unknown/not-owned, or a
non-wav source), in which case ``error`` explains why. Live sub-job status is
read from the referenced ``Job`` at status-check time, so only the immutable
mapping is stored here.
"""

from datetime import datetime

from beanie import Document, PydanticObjectId
from pydantic import BaseModel, Field
from pymongo import ASCENDING, IndexModel

from .common import utcnow


class BatchClipEntry(BaseModel):
    """One clip in a batch: its sub-job id, or a request-time failure reason."""

    clip_id: str
    job_id: str | None = None
    error: str | None = None


class BatchJob(Document):
    """A batch of per-clip sub-jobs (stems extraction or audio export)."""

    user_id: PydanticObjectId
    operation: str  # "stems" | "export"
    # Target format for export batches; None for stems.
    format: str | None = None
    entries: list[BatchClipEntry] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "batch_jobs"
        indexes = [
            IndexModel([("user_id", ASCENDING)]),
        ]
