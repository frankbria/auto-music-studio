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
    # US-22.4 basic editing: edits are non-destructive — each produces a new Video.
    # ``parent_video_id`` links it back to the version it was derived from (None for
    # an original render); ``edit`` records the operation (e.g. {"operation":"trim",
    # "start_seconds":5,"end_seconds":30}) so the version history can label it.
    parent_video_id: PydanticObjectId | None = None
    edit: dict | None = None
    # The rendered length of THIS version (seconds): the source song's duration
    # for an original render, ``end - start`` for a trim, otherwise the source
    # version's duration. Lets an edit-of-an-edit validate its range against the
    # actual video being edited rather than the full song. ``None`` for videos
    # rendered before this field existed (validation then falls back to the clip).
    duration: float | None = None
    created_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "videos"
        indexes = [
            # Serves "videos for this clip owned by this user" (the association
            # the status endpoint resolves and future delivery endpoints validate).
            IndexModel([("clip_id", ASCENDING), ("user_id", ASCENDING)]),
        ]
