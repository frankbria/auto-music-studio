"""Playback queue document model (US-14.3).

One :class:`PlaybackQueue` document per user holds the server-side listening
session: the ordered clip ids, the current position, and the repeat/shuffle
modes. Shuffle uses ``shuffle_history`` (the indices visited, in order) so
"previous" walks back through what was actually played.
"""

from datetime import datetime
from enum import Enum

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, IndexModel

from .common import utcnow


class RepeatMode(str, Enum):
    NONE = "none"
    ONE = "one"
    ALL = "all"


class PlaybackQueue(Document):
    """A user's persisted playback queue (one per user)."""

    user_id: PydanticObjectId
    clips: list[PydanticObjectId] = Field(default_factory=list)
    # None means "nothing playing" — distinct from index 0 on an empty queue.
    current_index: int | None = None
    repeat_mode: RepeatMode = RepeatMode.NONE
    shuffle_enabled: bool = False
    # Indices (into ``clips``) already played this shuffle session, in order.
    shuffle_history: list[int] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime | None = None

    class Settings:
        name = "playback_queues"
        indexes = [
            # One queue per user; the unique index makes get-or-create race-safe
            # (a concurrent double-insert fails rather than creating two queues).
            IndexModel([("user_id", ASCENDING)], unique=True),
        ]
