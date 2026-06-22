"""Release package document model (US-13.3).

A release bundles a source clip's mastered audio and cover art with the metadata
needed for distribution (title, artist, genre, ISRC, …). It is the input for the
distribution channels (US-13.2 SoundCloud, future stores). Validation warnings
(unmastered audio, missing artwork) are *computed* from the live clip at response
time rather than stored, so they resolve automatically once the clip is fixed —
see :func:`acemusic.api.services.releases.compute_warnings`.
"""

from datetime import datetime
from enum import Enum

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, DESCENDING, IndexModel

from .common import utcnow


class ReleaseStatus(str, Enum):
    """Lifecycle of a release package."""

    DRAFT = "draft"
    READY = "ready"
    SUBMITTED = "submitted"
    LIVE = "live"
    REJECTED = "rejected"


class Release(Document):
    """A distribution-ready package assembled from a clip plus metadata."""

    clip_id: PydanticObjectId
    user_id: PydanticObjectId
    status: ReleaseStatus = ReleaseStatus.DRAFT

    # Required metadata (enforced at the schema layer, so 422 on create).
    title: str
    artist: str
    genre: str
    release_date: datetime

    # Optional metadata.
    album_name: str | None = None
    description: str | None = None
    # Identifiers (US-13.4), auto-minted on create, overridable via PATCH. ``isrc``
    # mirrors the source recording's code and is *not* unique here — re-releases of
    # one recording legitimately share it (uniqueness is enforced on the clip).
    # ``upc`` identifies this release and is globally unique (partial index below).
    isrc: str | None = None
    upc: str | None = None
    copyright: str | None = None
    is_explicit: bool | None = None
    language: str | None = None
    credits: str | None = None

    # Distribution targets the owner has confirmed a manual submission to (US-13.5).
    # A release can go to more than one of LANDR/DistroKid/TuneCore, so this is a
    # list of target names while ``status`` stays a single ``submitted`` flag.
    submitted_channels: list[str] = Field(default_factory=list)

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime | None = None

    class Settings:
        name = "releases"
        indexes = [
            # Serves "this user's releases, newest first" from the index.
            IndexModel([("user_id", ASCENDING), ("created_at", DESCENDING)]),
            IndexModel([("clip_id", ASCENDING)]),
            # One UPC per release (US-13.4); partial filter skips releases without one.
            IndexModel(
                [("upc", ASCENDING)],
                unique=True,
                partialFilterExpression={"upc": {"$type": "string"}},
            ),
        ]
