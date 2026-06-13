"""Clip document model (US-8.2).

Fields mirror the CLI's :class:`acemusic.models.Clip` so the API and CLI share a
consistent clip shape as the platform migrates from SQLite to MongoDB.
"""

from datetime import datetime

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, DESCENDING, IndexModel

from .common import utcnow


class Clip(Document):
    """A generated or imported audio clip with its metadata and lineage."""

    workspace_id: PydanticObjectId
    user_id: PydanticObjectId
    file_path: str
    title: str | None = None
    format: str | None = None
    duration: float | None = None
    bpm: int | None = None
    key: str | None = None
    style_tags: list[str] = Field(default_factory=list)
    lyrics: str | None = None
    vocal_language: str | None = None
    model: str | None = None
    seed: int | None = None
    inference_steps: int | None = None
    parent_clip_ids: list[PydanticObjectId] = Field(default_factory=list)
    generation_mode: str | None = None
    # Extracted MIDI artifacts (US-10.2), keyed label -> storage key. MIDI files
    # are not clips, so the parent clip records them here; this is the cache and
    # retrieval source (the storage backend offers no list/exists). None until a
    # MIDI extraction job completes for this clip.
    midi_paths: dict[str, str] | None = None
    is_public: bool = False  # documents predating US-9.3 load as private
    created_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "clips"
        indexes = [
            # Compound index serves the common "clips in a workspace, newest
            # first" query entirely from the index; its workspace_id prefix also
            # covers plain workspace_id lookups (US-8.2 AC).
            IndexModel([("workspace_id", ASCENDING), ("created_at", DESCENDING)]),
            IndexModel([("user_id", ASCENDING)]),
            IndexModel([("created_at", DESCENDING)]),
        ]
