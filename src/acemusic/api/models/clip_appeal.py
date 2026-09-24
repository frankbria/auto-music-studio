"""A creator's appeal of a moderation decision on their clip (US-27.4).

An appeal targets one moderation action: the ``ModerationLogEntry`` that removed or flagged
the clip. The unique ``action_id`` index is what makes "one appeal per decision" hold under
concurrent submits; a later removal is a new log entry, so it can be appealed afresh.
"""

from datetime import datetime
from typing import Literal

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, DESCENDING, IndexModel

from .common import utcnow

AppealStatus = Literal["pending", "info_requested", "upheld", "reversed"]
AppealedAction = Literal["remove", "flag"]
OPEN_APPEAL_STATUSES: tuple[AppealStatus, ...] = ("pending", "info_requested")


class ClipAppeal(Document):
    clip_id: PydanticObjectId
    user_id: PydanticObjectId
    action_id: PydanticObjectId
    action: AppealedAction
    reason: str
    context: str | None = None
    status: AppealStatus = "pending"
    admin_note: str | None = None
    decided_by: PydanticObjectId | None = None
    decided_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "clip_appeals"
        indexes = [
            IndexModel([("action_id", ASCENDING)], unique=True),
            IndexModel([("status", ASCENDING), ("created_at", DESCENDING)]),
            IndexModel([("user_id", ASCENDING), ("created_at", DESCENDING)]),
            IndexModel([("clip_id", ASCENDING), ("created_at", DESCENDING)]),
        ]
