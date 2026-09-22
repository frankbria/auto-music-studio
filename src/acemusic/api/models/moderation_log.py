"""The admin moderation audit trail (US-27.3).

One entry per target an admin acted on, written by the action itself. Append-only:
nothing updates or deletes an entry.
"""

from datetime import datetime

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import DESCENDING, IndexModel

from .common import utcnow


class ModerationLogEntry(Document):
    actor_id: PydanticObjectId
    action: str
    target_type: str  # "clip", "user" or "screening_rules"
    target_id: str | None = None
    reason: str | None = None
    details: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "moderation_log"
        indexes = [IndexModel([("created_at", DESCENDING)])]
