"""Rendered music-video document model (US-22.1).

Each completed video-generation job produces one rendered MP4; a ``Video``
records where it is stored and which song (clip) it belongs to. A permanent
record with its own id — rather than a field on the job result — mirrors
:class:`~acemusic.api.models.artwork.ArtworkOption`: the delivery/publish
endpoints (US-22.3+) need a stable id and a ``user_id`` for ownership checks,
and a ``Clip`` is the wrong shape (it is audio-specific: bpm/key/lyrics feed
the streaming and search surfaces).
"""

from datetime import datetime

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, IndexModel

from .common import utcnow


class Video(Document):
    """One rendered music video for a source clip."""

    clip_id: PydanticObjectId
    user_id: PydanticObjectId
    job_id: PydanticObjectId
    storage_path: str
    resolution: str
    aspect_ratio: str
    # US-22.3: a rendered video is private to its owner until published, at which
    # point it becomes visible on the (public) song detail page.
    published: bool = False
    created_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "videos"
        indexes = [
            # Serves "videos for this clip owned by this user" (the association
            # the status endpoint resolves and future delivery endpoints validate).
            IndexModel([("clip_id", ASCENDING), ("user_id", ASCENDING)]),
        ]
