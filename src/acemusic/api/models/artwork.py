"""Cover-art option document model (US-13.1).

Each artwork-generation job produces a batch of options; one ``ArtworkOption`` per
option records where its image is stored and who owns it. A permanent record (like
:class:`~acemusic.api.models.clip.Clip`) — rather than an array embedded in the
job result — gives each option a stable id for selection and a ``user_id`` for the
ownership check the select endpoint enforces.
"""

from datetime import datetime

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, IndexModel

from .common import utcnow


class ArtworkOption(Document):
    """One generated cover-art option for a clip."""

    clip_id: PydanticObjectId
    user_id: PydanticObjectId
    job_id: PydanticObjectId
    storage_path: str
    option_index: int
    created_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "artwork_options"
        indexes = [
            # Serves "options for this clip owned by this user" (the listing the
            # job-status endpoint resolves and the select endpoint validates).
            IndexModel([("clip_id", ASCENDING), ("user_id", ASCENDING)]),
        ]
