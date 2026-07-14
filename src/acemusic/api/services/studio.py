"""Studio export service layer (US-19.6).

The Studio has no backend arrangement persistence, so an export request carries
the whole arrangement (tracks + placements + per-track controls + bpm + markers).
This module owns the request models (field-validated so the router stays thin and
the shapes are unit-testable without the HTTP surface), the two job-type
constants, the ``create_*_job`` wrappers around
:func:`acemusic.api.services.jobs.create_job`, and the canonical storage key for a
DAW-export ZIP. Kept transport-agnostic (plain exceptions, never
``HTTPException``) like the other service modules.

Two job types share this arrangement payload:

* ``studio_mixdown`` renders one mixed audio file, stored as a ``generation_mode
  ="studio"`` child clip (so the web "Studio" badge lights up) auditionable via
  the generic job-status endpoint (``result["clip_ids"]``).
* ``studio_daw_export`` bounces per-track stems into a ZIP uploaded to
  :func:`studio_export_storage_path`, served by ``GET /studio/export/daw/{id}``.
"""

from __future__ import annotations

from typing import Any, Literal

from beanie import PydanticObjectId
from pydantic import BaseModel, Field, model_validator

from ..models import Job
from .jobs import create_job

STUDIO_MIXDOWN_JOB_TYPE = "studio_mixdown"
STUDIO_DAW_EXPORT_JOB_TYPE = "studio_daw_export"

# Per-track control bounds mirror the Studio UI (US-19.4): faders run -60..+6 dB
# and pan is a normalised -1 (hard left) .. +1 (hard right).
VOLUME_DB_MIN = -60.0
VOLUME_DB_MAX = 6.0

# Arrangement size caps: the worker downloads every referenced clip to local disk
# before mixing, so an unbounded request is a disk/memory exhaustion vector. Far
# above any real studio session, low enough to bound a hostile payload.
MAX_TRACKS = 64
MAX_PLACEMENTS_PER_TRACK = 256


class PlacementRequest(BaseModel):
    """A clip placed on a track's timeline at ``start_sec``, optionally trimmed."""

    clip_id: str = Field(min_length=1)
    start_sec: float = Field(ge=0.0)
    duration_sec: float | None = Field(default=None, gt=0.0)


class TrackRequest(BaseModel):
    """A studio track: its type, mix controls (US-19.4), and placements."""

    name: str
    track_type: str
    volume_db: float = Field(default=0.0, ge=VOLUME_DB_MIN, le=VOLUME_DB_MAX)
    pan: float = Field(default=0.0, ge=-1.0, le=1.0)
    muted: bool = False
    solo: bool = False
    placements: list[PlacementRequest] = Field(default_factory=list, max_length=MAX_PLACEMENTS_PER_TRACK)


class MarkerRequest(BaseModel):
    """A named position on the arrangement timeline (US-19.3)."""

    name: str
    time_sec: float = Field(ge=0.0)


class StudioArrangementRequest(BaseModel):
    """The arrangement payload shared by mixdown and DAW export.

    Rejects arrangements with nothing to export: the UI disables its buttons on an
    empty timeline, but a direct API call would otherwise 202 and "succeed" with a
    zero-length file.
    """

    workspace_id: str
    project_name: str = Field(min_length=1)
    bpm: float | None = Field(default=None, gt=0.0)
    markers: list[MarkerRequest] = Field(default_factory=list)
    tracks: list[TrackRequest] = Field(min_length=1, max_length=MAX_TRACKS)

    @model_validator(mode="after")
    def _require_placements(self) -> "StudioArrangementRequest":
        if not any(track.placements for track in self.tracks):
            raise ValueError("arrangement has no clip placements to export")
        return self


class StudioMixdownRequest(StudioArrangementRequest):
    """A studio mixdown: the arrangement plus the delivery ``format``."""

    format: Literal["wav", "flac", "mp3"] = "wav"


class StudioDawExportRequest(StudioArrangementRequest):
    """A DAW export: the same arrangement, minus ``format`` (stems are always WAV)."""


def clip_ids_in(tracks: list[TrackRequest]) -> list[str]:
    """The distinct clip ids referenced across every track's placements.

    Order-preserving (first occurrence wins) so ownership checks and lineage are
    deterministic. This is the exact set the router validates and the worker
    downloads.
    """
    seen: dict[str, None] = {}
    for track in tracks:
        for placement in track.placements:
            seen.setdefault(placement.clip_id, None)
    return list(seen)


def studio_export_storage_path(
    user_id: PydanticObjectId, workspace_id: PydanticObjectId, job_id: PydanticObjectId
) -> str:
    """Canonical storage key for a studio DAW-export ZIP.

    Keyed by *job* id, not a clip: a DAW export has no owning clip (it bundles many
    source clips), so the worker (which writes it) and the GET endpoint (which
    serves it) agree on this single key.
    """
    return f"{user_id}/{workspace_id}/exports/studio_{job_id}.zip"


async def create_mixdown_job(
    *,
    user_id: PydanticObjectId,
    workspace_id: PydanticObjectId,
    params: dict[str, Any],
) -> Job:
    """Persist a queued studio-mixdown job carrying the full arrangement and dispatch it."""
    return await create_job(
        user_id=user_id,
        workspace_id=workspace_id,
        job_type=STUDIO_MIXDOWN_JOB_TYPE,
        params=params,
        valid_types=(STUDIO_MIXDOWN_JOB_TYPE,),
    )


async def create_daw_export_job(
    *,
    user_id: PydanticObjectId,
    workspace_id: PydanticObjectId,
    params: dict[str, Any],
) -> Job:
    """Persist a queued studio DAW-export job carrying the full arrangement and dispatch it."""
    return await create_job(
        user_id=user_id,
        workspace_id=workspace_id,
        job_type=STUDIO_DAW_EXPORT_JOB_TYPE,
        params=params,
        valid_types=(STUDIO_DAW_EXPORT_JOB_TYPE,),
    )
