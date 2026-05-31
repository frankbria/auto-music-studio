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
    status: JobStatus = JobStatus.QUEUED
    input_params: dict = Field(default_factory=dict)
    result: dict | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    class Settings:
        name = "jobs"
        indexes = [
            IndexModel([("user_id", ASCENDING)]),
            IndexModel([("status", ASCENDING)]),
        ]
