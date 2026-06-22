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

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from ..auth.dependencies import CurrentUser, get_current_user, get_settings, require_existing_user
from ..models import DistributionStatus, Release, ReleaseStatus, VisibilityState
from ..models.distribution import GUIDED_CHANNELS, SOUNDCLOUD_CHANNEL
from ..services import (
    clips as clip_service,
    distribution as distribution_service,
    distribution_status as status_service,
    releases as release_service,
    soundcloud as sc,
)
from ..services.distribution import ChecklistItem, DistributionTarget
from ..services.identifiers import validate_isrc_format, validate_upc_check_digit
from ..settings import ApiSettings

logger = logging.getLogger(__name__)

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
    submitted_channels: list[str]
    # Per-channel distribution status + visibility (US-13.6), so a listing shows
    # where each release stands across all channels without a second call.
    channel_statuses: dict[str, DistributionStatus]
    visibility: VisibilityState
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
            submitted_channels=release.submitted_channels,
            channel_statuses=release.channel_statuses,
            visibility=release.visibility,
            created_at=release.created_at,
            updated_at=release.updated_at,
            **{field: getattr(release, field) for field in _METADATA_FIELDS},
        )


class ChannelStatus(BaseModel):
    channel: str
    status: DistributionStatus


class ReleaseStatusResponse(BaseModel):
    release_id: str
    title: str
    channels: list[ChannelStatus]
    visibility: VisibilityState
    # Surfaced only when the release is on SoundCloud (the auto-polled channel).
    soundcloud_last_polled: datetime | None = None

    @classmethod
    def from_release(cls, release: Release) -> "ReleaseStatusResponse":
        return cls(
            release_id=str(release.id),
            title=release.title,
            channels=[ChannelStatus(channel=ch, status=st) for ch, st in release.channel_statuses.items()],
            visibility=release.visibility,
            soundcloud_last_polled=release.soundcloud_last_polled,
        )


class StatusUpdateRequest(BaseModel):
    # Pydantic rejects an unknown status value with 422 automatically.
    model_config = ConfigDict(extra="forbid")

    status: DistributionStatus


class VisibilityUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: VisibilityState


class PrepareResponse(BaseModel):
    release_id: str
    target: DistributionTarget
    checklist: list[ChecklistItem]
    all_checks_passed: bool
    # Null until every checklist item passes; the package isn't bundled before then.
    bundle_url: str | None
    instructions: str


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


@router.post("/{release_id}/prepare/{target}", response_model=PrepareResponse)
async def prepare_release(
    release_id: str,
    target: DistributionTarget,
    current: CurrentUser = Depends(require_existing_user),
) -> PrepareResponse:
    """Validate a release for a distribution target and, if it passes, build a bundle.

    Always returns the checklist; ``bundle_url`` is null when any item fails. An
    unknown target is rejected by FastAPI's enum path validation (422).
    """
    release = await release_service.get_owned_release(release_id, current.user_id)
    checklist, bundle_url = await distribution_service.prepare_release(release, target)
    return PrepareResponse(
        release_id=str(release.id),
        target=target,
        checklist=checklist,
        all_checks_passed=distribution_service.is_release_ready(checklist),
        bundle_url=bundle_url,
        instructions=distribution_service.instructions_for(target),
    )


@router.post("/{release_id}/submit/{target}", response_model=ReleaseResponse)
async def submit_release(
    release_id: str,
    target: DistributionTarget,
    current: CurrentUser = Depends(require_existing_user),
) -> ReleaseResponse:
    """Confirm a manual submission to ``target`` — moves the release to ``submitted``."""
    release = await release_service.confirm_submission(release_id, current.user_id, target.value)
    return await _response_for(release)


@router.get("/{release_id}/status", response_model=ReleaseStatusResponse)
async def get_release_status(
    release_id: str,
    current: CurrentUser = Depends(require_existing_user),
) -> ReleaseStatusResponse:
    """Per-channel distribution status for a single release (US-13.6). 404 if not owned."""
    release = await release_service.get_owned_release(release_id, current.user_id)
    return ReleaseStatusResponse.from_release(release)


@router.patch("/{release_id}/channels/{channel}/status", response_model=ChannelStatus)
async def update_channel_status(
    release_id: str,
    channel: str,
    body: StatusUpdateRequest,
    current: CurrentUser = Depends(require_existing_user),
) -> ChannelStatus:
    """Manually update a *guided* channel's status (US-13.6).

    SoundCloud is automated (rejected with 400); an unknown channel is also 400.
    An out-of-sequence transition (e.g. draft → live) is 409.
    """
    if channel not in GUIDED_CHANNELS:
        detail = (
            "SoundCloud status is updated automatically and cannot be set manually."
            if channel == SOUNDCLOUD_CHANNEL
            else f"Unknown distribution channel: {channel}."
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)

    release = await release_service.get_owned_release(release_id, current.user_id)
    try:
        old_status = await status_service.apply_channel_status(release, channel, body.status)
    except status_service.InvalidStatusTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    # Notify only on a transition this request actually applied — a lost concurrent
    # race returns old == requested, so ``changed`` is False and we don't double-fire.
    changed = old_status != body.status
    if changed and status_service.should_notify(old_status, body.status):
        await status_service.create_status_notification(release, channel, body.status)
    return ChannelStatus(channel=channel, status=release.channel_statuses[channel])


@router.patch("/{release_id}/visibility", response_model=ReleaseStatusResponse)
async def update_visibility(
    release_id: str,
    body: VisibilityUpdateRequest,
    current: CurrentUser = Depends(require_existing_user),
    settings: ApiSettings = Depends(get_settings),
) -> ReleaseStatusResponse:
    """Change a release's visibility (US-13.6); sync SoundCloud sharing if it's uploaded there."""
    release = await release_service.get_owned_release(release_id, current.user_id)
    if release.soundcloud_track_id:
        await _sync_soundcloud_sharing(release, body.state, settings)
    release = await release_service.update_visibility(release, body.state)
    return ReleaseStatusResponse.from_release(release)


async def _sync_soundcloud_sharing(release: Release, state: VisibilityState, settings: ApiSettings) -> None:
    """Best-effort mirror of a release's visibility onto its SoundCloud track.

    SoundCloud only models public/private, so anything short of ``public`` maps to
    private. A missing link or a transient SoundCloud failure is logged and
    swallowed — the local visibility change still stands rather than failing the
    whole request on an external dependency.
    """
    sharing = "public" if state == VisibilityState.PUBLIC else "private"
    try:
        connection = await sc.get_valid_connection(str(release.user_id), settings)
        await sc.update_track_sharing(connection.access_token, release.soundcloud_track_id, sharing)
    except sc.SoundCloudError as exc:
        logger.warning("SoundCloud sharing sync for release %s failed: %s", release.id, exc)
