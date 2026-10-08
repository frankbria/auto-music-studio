"""SoundCloud tracks waiting to be made private (#569).

A takedown (clip removal, ban, a removal racing a share, a dropped cover) never calls SoundCloud
inside the request. It queues one row per track here, and the SoundCloud poller drains the queue,
retrying with backoff until the track is private or the owner's grant is gone.
"""

from datetime import datetime

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, IndexModel

from .common import utcnow


class SoundCloudUnshare(Document):
    track_id: str
    user_id: PydanticObjectId
    clip_id: PydanticObjectId | None = None
    attempts: int = 0
    next_attempt_at: datetime = Field(default_factory=utcnow)
    last_error: str | None = None
    created_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "soundcloud_unshares"
        indexes = [
            # One row per track: queueing it again only makes it due now.
            IndexModel([("track_id", ASCENDING)], unique=True),
            IndexModel([("next_attempt_at", ASCENDING)]),
        ]
