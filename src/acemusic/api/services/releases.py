"""Release package service layer (US-13.3).

Owns user-scoped release CRUD. Ownership failures and unknown/malformed ids
surface as 404 so the API never reveals another user's releases (mirrors
:mod:`acemusic.api.services.presets`). Required-metadata validation lives at the
Pydantic schema layer (422); this layer enforces clip ownership and the
post-submission edit lock (409).
"""

from beanie import PydanticObjectId
from beanie.operators import Eq
from fastapi import HTTPException, status

from ..models import Clip, Release, ReleaseStatus
from ..models.common import utcnow
from . import clips as clip_service
from .common import coerce_object_id
from .mastering import APPROVED_GENERATION_MODE

# Releases are editable only before they leave the user's hands.
_EDITABLE_STATUSES = {ReleaseStatus.DRAFT, ReleaseStatus.READY}


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Release not found.")


def _state_error(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


async def get_owned_release(release_id: str, user_id: str) -> Release:
    """Return the release if ``user_id`` owns it; 404 for unknown/malformed/not-owned ids."""
    oid = coerce_object_id(release_id)
    release = await Release.get(oid) if oid is not None else None
    if release is None or str(release.user_id) != user_id:
        raise _not_found()
    return release


async def list_releases(user_id: str) -> list[Release]:
    """Return all of ``user_id``'s releases, newest first.

    The ``_id`` tiebreak keeps ordering stable when ``created_at`` values collide
    (same reason the clips listing does it).
    """
    return (
        await Release.find(Eq(Release.user_id, PydanticObjectId(user_id)))
        .sort(("created_at", -1), ("_id", -1))
        .to_list()
    )


async def create_release(user_id: str, clip_id: str, metadata: dict) -> Release:
    """Create a release for an owned clip. Raises 404 if the clip is unknown/not-owned.

    ``metadata`` holds only release metadata fields (the router validates and
    dumps them), so identity/status fields cannot be injected through it. All
    required fields are enforced upstream by the schema, so a created release is
    immediately ``ready`` — the soft blocks (unmastered audio, missing art) are
    surfaced as computed warnings, not status.
    """
    await clip_service.get_owned_clip(clip_id, user_id)
    release = Release(
        clip_id=PydanticObjectId(clip_id),
        user_id=PydanticObjectId(user_id),
        status=ReleaseStatus.READY,
        **metadata,
    )
    await release.insert()
    return release


def compute_warnings(clip: Clip | None) -> list[str]:
    """Soft-block warnings for a release's source clip (not stored; computed per response).

    ``clip`` is ``None`` when the source clip has since been deleted: the release
    still holds its own metadata and stays readable, so we surface the gap as a
    warning rather than letting the package become unretrievable.
    """
    if clip is None:
        return ["Source clip is no longer available"]
    warnings: list[str] = []
    if clip.generation_mode != APPROVED_GENERATION_MODE:
        warnings.append("Audio has not been mastered")
    if clip.artwork_path is None:
        warnings.append("Cover art has not been added")
    return warnings


async def update_release(release_id: str, user_id: str, updates: dict) -> Release:
    """Apply ``updates`` to an owned release. Raises 404 if not owned, 409 once submitted.

    ``updates`` must come from a validated ``ReleaseUpdate`` dump — the setattr
    loop trusts its keys, so a raw dict could reassign identity fields like
    ``user_id`` (same contract as ``create_release``).
    """
    release = await get_owned_release(release_id, user_id)
    if release.status not in _EDITABLE_STATUSES:
        raise _state_error("Release metadata cannot be modified after submission")
    for field, value in updates.items():
        setattr(release, field, value)
    release.updated_at = utcnow()
    await release.save()
    return release
