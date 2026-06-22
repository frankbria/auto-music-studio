"""Release package CRUD router (US-13.3), mounted under ``/api/v1/releases``.

Endpoints (all require a valid Bearer access token and operate only on the
authenticated user's releases):

* ``POST  /releases``      → create from an owned clip (201; 404 if clip not owned)
* ``GET   /releases``      → list the user's releases
* ``GET   /releases/{id}`` → single release with computed warnings (404 if missing/not owned)
* ``PATCH /releases/{id}`` → partial metadata update (409 once submitted)

A release *is* the package: its metadata is inline in the response, ``clip_id``
resolves to the mastered audio and cover art, and ``warnings`` flags any missing
piece (computed live from the clip). Persistence lives in
:mod:`acemusic.api.services.releases`.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from ..auth.dependencies import CurrentUser, get_current_user, get_settings, require_existing_user
from ..models import Release, ReleaseStatus
from ..services import clips as clip_service, releases as release_service
from ..services.identifiers import validate_isrc_format, validate_upc_check_digit
from ..settings import ApiSettings

router = APIRouter(prefix="/releases", tags=["releases"], dependencies=[Depends(get_current_user)])

# Metadata fields carried on create/update/response (everything except identity,
# status, clip_id, and timestamps).
_METADATA_FIELDS: tuple[str, ...] = (
    "title",
    "artist",
    "genre",
    "release_date",
    "album_name",
    "description",
    "isrc",
    "upc",
    "copyright",
    "is_explicit",
    "language",
    "credits",
)


class ReleaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clip_id: str
    # Required metadata (missing → 422).
    title: str
    artist: str
    genre: str
    release_date: datetime
    # Optional metadata. ISRC/UPC are not accepted here — they are auto-minted on
    # create (US-13.4) and only overridable via PATCH.
    album_name: str | None = None
    description: str | None = None
    copyright: str | None = None
    is_explicit: bool | None = None
    language: str | None = None
    credits: str | None = None


# Required metadata cannot be cleared on update — clearing one would persist a
# release that can no longer be serialized by ReleaseResponse.
_REQUIRED_METADATA_FIELDS: tuple[str, ...] = ("title", "artist", "genre", "release_date")


class ReleaseUpdate(BaseModel):
    """Partial update — only explicitly-sent fields are applied. ``clip_id`` and
    status are not editable here, and the required fields cannot be cleared."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    artist: str | None = None
    genre: str | None = None
    release_date: datetime | None = None
    album_name: str | None = None
    description: str | None = None
    isrc: str | None = None
    upc: str | None = None
    copyright: str | None = None
    is_explicit: bool | None = None
    language: str | None = None
    credits: str | None = None

    @field_validator("isrc")
    @classmethod
    def _check_isrc(cls, value: str | None) -> str | None:
        """Reject a malformed manual ISRC (422); None clears it."""
        if value is not None and not validate_isrc_format(value):
            raise ValueError("isrc must match the format CC-XXX-YY-NNNNN (e.g. US-A1B-26-00001)")
        return value

    @field_validator("upc")
    @classmethod
    def _check_upc(cls, value: str | None) -> str | None:
        """Reject a non-EAN-13 manual UPC (422); None clears it."""
        # validate_upc_check_digit already enforces the 13-digit shape.
        if value is not None and not validate_upc_check_digit(value):
            raise ValueError("upc must be a valid 13-digit EAN-13 with a correct check digit")
        return value

    @model_validator(mode="after")
    def _reject_clearing_required(self) -> "ReleaseUpdate":
        cleared = [
            field
            for field in _REQUIRED_METADATA_FIELDS
            if field in self.model_fields_set and getattr(self, field) is None
        ]
        if cleared:
            raise ValueError(f"Required fields cannot be cleared: {', '.join(cleared)}")
        return self


class ReleaseResponse(BaseModel):
    id: str
    clip_id: str
    status: ReleaseStatus
    warnings: list[str]
    created_at: datetime
    updated_at: datetime | None

    title: str
    artist: str
    genre: str
    release_date: datetime
    album_name: str | None
    description: str | None
    isrc: str | None
    upc: str | None
    copyright: str | None
    is_explicit: bool | None
    language: str | None
    credits: str | None

    @classmethod
    def from_release(cls, release: Release, warnings: list[str]) -> "ReleaseResponse":
        return cls(
            id=str(release.id),
            clip_id=str(release.clip_id),
            status=release.status,
            warnings=warnings,
            created_at=release.created_at,
            updated_at=release.updated_at,
            **{field: getattr(release, field) for field in _METADATA_FIELDS},
        )


class ReleaseListResponse(BaseModel):
    releases: list[ReleaseResponse]
    total: int


async def _response_for(release: Release) -> ReleaseResponse:
    """Build a response, computing warnings from the source clip.

    The clip may have been deleted after the release was assembled; the release
    keeps its own metadata, so a missing clip is tolerated (surfaced as a warning)
    rather than making the package — or a whole list containing it — unreadable.
    """
    clip = await clip_service.find_owned_clip(str(release.clip_id), str(release.user_id))
    return ReleaseResponse.from_release(release, release_service.compute_warnings(clip))


@router.post("", response_model=ReleaseResponse, status_code=status.HTTP_201_CREATED)
async def create_release(
    body: ReleaseCreate,
    current: CurrentUser = Depends(require_existing_user),
    settings: ApiSettings = Depends(get_settings),
) -> ReleaseResponse:
    metadata = body.model_dump(exclude={"clip_id"})
    release = await release_service.create_release(current.user_id, body.clip_id, metadata, settings)
    return await _response_for(release)


@router.get("", response_model=ReleaseListResponse)
async def list_releases(current: CurrentUser = Depends(require_existing_user)) -> ReleaseListResponse:
    releases = await release_service.list_releases(current.user_id)
    return ReleaseListResponse(
        releases=[await _response_for(r) for r in releases],
        total=len(releases),
    )


@router.get("/{release_id}", response_model=ReleaseResponse)
async def get_release(
    release_id: str,
    current: CurrentUser = Depends(require_existing_user),
) -> ReleaseResponse:
    release = await release_service.get_owned_release(release_id, current.user_id)
    return await _response_for(release)


@router.patch("/{release_id}", response_model=ReleaseResponse)
async def update_release(
    release_id: str,
    body: ReleaseUpdate,
    current: CurrentUser = Depends(require_existing_user),
) -> ReleaseResponse:
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        release = await release_service.get_owned_release(release_id, current.user_id)
    else:
        release = await release_service.update_release(release_id, current.user_id, updates)
    return await _response_for(release)
