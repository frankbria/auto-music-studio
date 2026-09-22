"""A listener's report of a clip (US-27.2).

Reports feed the admin moderation queue. The unique (clip, reporter) index is what
makes "one report per user per clip" hold under concurrent submits.
"""

from datetime import datetime
from typing import Literal

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, DESCENDING, IndexModel

from .common import utcnow

ReportCategory = Literal["inappropriate", "copyright", "spam", "other"]


class ClipReport(Document):
    clip_id: PydanticObjectId
    reporter_id: PydanticObjectId
    category: ReportCategory
    details: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    #: US-27.3: an admin acted on the clip. Kept for history; only open reports are queued.
    resolved_at: datetime | None = None

    class Settings:
        name = "clip_reports"
        indexes = [
            IndexModel([("clip_id", ASCENDING), ("reporter_id", ASCENDING)], unique=True),
            IndexModel([("created_at", DESCENDING)]),
            IndexModel([("resolved_at", ASCENDING), ("clip_id", ASCENDING)]),
        ]
