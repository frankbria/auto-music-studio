"""Clip document model (US-8.2).

Fields mirror the CLI's :class:`acemusic.models.Clip` so the API and CLI share a
consistent clip shape as the platform migrates from SQLite to MongoDB.
"""

from datetime import datetime
from typing import Any

from beanie import Document, PydanticObjectId
from pydantic import Field, model_validator
from pymongo import ASCENDING, DESCENDING, IndexModel

from .common import utcnow
from .distribution import VisibilityState


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
    # The request parameters that produced this clip (US-10.3 iterative
    # generation), stored verbatim so an operation can be reproduced from its
    # output. None for clips created before US-10.3 or by non-iterative paths.
    generation_params: dict | None = None
    # Extracted MIDI artifacts (US-10.2), keyed label -> storage key. MIDI files
    # are not clips, so the parent clip records them here; this is the cache and
    # retrieval source (the storage backend offers no list/exists). None until a
    # MIDI extraction job completes for this clip.
    midi_paths: dict[str, str] | None = None
    # Storage key of the selected/uploaded cover art (US-13.1). None until the
    # owner selects a generated option or uploads custom artwork; the binary is
    # served via ``GET /clips/{id}/artwork`` (file_path stays internal, like audio).
    artwork_path: str | None = None
    # International Standard Recording Code (US-13.4). Identifies this *recording*;
    # minted (or reused) when the clip is first packaged into a release and shared
    # with that release. Globally unique via the partial index below — a recording
    # gets exactly one ISRC, never reused — while clips without one stay None.
    isrc: str | None = None
    # US-20.7: visibility is the source of truth (private/unlisted/public).
    visibility: VisibilityState = VisibilityState.PRIVATE
    # ponytail: is_public is a stored denormalization synced from `visibility`
    # (see the validators below) purely so existing Mongo queries filtering on
    # {"is_public": True} keep matching without a data migration. Never set it
    # directly — set `visibility` instead.
    is_public: bool = False  # documents predating US-9.3 load as private
    created_at: datetime = Field(default_factory=utcnow)

    @model_validator(mode="before")
    @classmethod
    def _backfill_visibility_from_legacy_is_public(cls, data: Any) -> Any:
        # Documents written before US-20.7 have is_public but no visibility key
        # at all; without this they'd silently load as PRIVATE (the field
        # default) and a legacy public clip would regress to private.
        if isinstance(data, dict) and "visibility" not in data and "is_public" in data:
            data = dict(data)
            data["visibility"] = VisibilityState.PUBLIC if data["is_public"] else VisibilityState.PRIVATE
        return data

    @model_validator(mode="after")
    def _sync_is_public(self) -> "Clip":
        # Keeps the invariant on construction and on load (Beanie re-validates
        # query results). It does NOT fire on plain attribute assignment
        # (validate_assignment is False on beanie.Document), so writers must not
        # assign `visibility` directly — use `set_visibility` below.
        self.is_public = self.visibility == VisibilityState.PUBLIC
        return self

    def set_visibility(self, visibility: VisibilityState) -> None:
        # The only correct way to change visibility on an existing document.
        # Setting the field alone would leave the `is_public` denormalization
        # stale in stored BSON (the after-validator doesn't run on assignment),
        # which would leak unlisted/private clips into `{"is_public": True}`
        # server-side queries (search/explore/similar). Set both together.
        self.visibility = visibility
        self.is_public = visibility == VisibilityState.PUBLIC

    class Settings:
        name = "clips"
        indexes = [
            # Compound index serves the common "clips in a workspace, newest
            # first" query entirely from the index; its workspace_id prefix also
            # covers plain workspace_id lookups (US-8.2 AC).
            IndexModel([("workspace_id", ASCENDING), ("created_at", DESCENDING)]),
            IndexModel([("user_id", ASCENDING)]),
            IndexModel([("created_at", DESCENDING)]),
            # Multikey index over the parent list powers the children lookup
            # ("clips derived from this clip", US-10.6) without a collection scan.
            IndexModel([("parent_clip_ids", ASCENDING)]),
            # One ISRC per recording (US-13.4). Partial filter excludes the many
            # clips with no code so they don't collide on null.
            IndexModel(
                [("isrc", ASCENDING)],
                unique=True,
                partialFilterExpression={"isrc": {"$type": "string"}},
            ),
        ]
