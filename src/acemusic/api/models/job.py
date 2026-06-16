"""Job document model (US-8.2).

Tracks async generation/processing tasks. The status lifecycle matches the
job-queue contract used by the Generation API (US-9.2):
``queued -> processing -> completed | failed``.
"""

from datetime import datetime
from enum import Enum

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, IndexModel

from .common import utcnow


class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Job(Document):
    """An async task record (generation, edit, export, …)."""

    user_id: PydanticObjectId
    workspace_id: PydanticObjectId
    job_type: str
    # Resolved compute target for this job (US-11.1): "local" or "remote", set by
    # the routing engine at enqueue time. None for jobs created before routing
    # existed or by paths that do not route (e.g. edits/exports).
    compute_target: str | None = None
    status: JobStatus = JobStatus.QUEUED
    input_params: dict = Field(default_factory=dict)
    result: dict | None = None
    error: str | None = None
    # Human-readable progress for long, multi-step jobs (US-10.4 full-song writes
    # "Processing section N of M" per section). None for single-step jobs.
    progress: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    class Settings:
        name = "jobs"
        indexes = [
            IndexModel([("user_id", ASCENDING)]),
            # Serves the processor's claim/requeue queries (US-9.2): filter by
            # (status, job_type) and sort by created_at, so a worker claims the
            # oldest queued job from the index rather than scanning the
            # collection. The (status) prefix also covers plain status lookups.
            IndexModel([("status", ASCENDING), ("job_type", ASCENDING), ("created_at", ASCENDING)]),
        ]
