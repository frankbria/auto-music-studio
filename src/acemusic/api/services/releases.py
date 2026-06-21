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
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from ..exceptions import DuplicateIdentifierError
from ..models import Clip, Release, ReleaseStatus
from ..models.common import utcnow
from ..settings import ApiSettings
from . import clips as clip_service, identifiers
from .common import coerce_object_id
from .mastering import APPROVED_GENERATION_MODE

# Releases are editable only before they leave the user's hands.
_EDITABLE_STATUSES = {ReleaseStatus.DRAFT, ReleaseStatus.READY}

# Auto-minted UPCs come from an atomic counter and so never collide with each
# other; the only way an insert can hit the unique index is a manually-assigned
# code that already occupies this sequence slot. A few re-mints clear it.
_MAX_MINT_ATTEMPTS = 5


def _duplicate_field(exc: DuplicateKeyError) -> str:
    """Name the identifier a unique-index violation collided on.

    Reads the driver's structured ``keyPattern`` (stable across versions) rather
    than string-matching the message.
    """
    key_pattern = (exc.details or {}).get("keyPattern", {})
    return "isrc" if "isrc" in key_pattern else "upc"


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


async def create_release(user_id: str, clip_id: str, metadata: dict, settings: ApiSettings) -> Release:
    """Create a release for an owned clip, auto-minting its ISRC and UPC (US-13.4).

    ``metadata`` holds only release metadata fields (the router validates and
    dumps them), so identity/status/identifier fields cannot be injected through
    it. The ISRC identifies the *recording*: an already-coded clip keeps its code
    (reused, not overwritten), otherwise a fresh ISRC is minted and written back
    to the clip so the package and recording stay in sync. The UPC identifies the
    release and is globally unique. All required fields are enforced upstream by
    the schema, so a created release is immediately ``ready``.
    """
    clip = await clip_service.get_owned_clip(clip_id, user_id)
    isrc = await _claim_clip_isrc(clip, settings)

    for _ in range(_MAX_MINT_ATTEMPTS):
        release = Release(
            clip_id=PydanticObjectId(clip_id),
            user_id=PydanticObjectId(user_id),
            status=ReleaseStatus.READY,
            isrc=isrc,
            upc=await identifiers.generate_upc(settings),
            **metadata,
        )
        try:
            await release.insert()
        except DuplicateKeyError:
            continue  # UPC slot taken by a manual code — mint the next
        return release
    raise DuplicateIdentifierError("upc")


async def _claim_clip_isrc(clip: Clip, settings: ApiSettings) -> str:
    """Return the recording's ISRC, atomically minting and claiming one if absent.

    Concurrent creations for the same uncoded clip race on the claim: exactly one
    ``$set``-on-null wins and the losers read back its code, so every release
    mirrors a single recording ISRC instead of diverging.
    """
    if clip.isrc is not None:
        return clip.isrc
    minted = await identifiers.generate_isrc(settings)
    try:
        doc = await Clip.get_pymongo_collection().find_one_and_update(
            {"_id": clip.id, "isrc": None},
            {"$set": {"isrc": minted}},
            return_document=ReturnDocument.AFTER,
        )
    except DuplicateKeyError as exc:  # minted ISRC already on another recording (rare)
        raise DuplicateIdentifierError("isrc") from exc
    if doc is not None:
        return doc["isrc"]  # we won the claim
    # A concurrent creation already coded the clip — read back the canonical value.
    refreshed = await Clip.get(clip.id)
    return refreshed.isrc if refreshed and refreshed.isrc else minted


async def _ensure_upc_unused(upc: str, release_id: PydanticObjectId) -> None:
    """Raise 409 if a *different* release already holds ``upc``.

    Checked before any write so a clashing UPC override can never leave the clip
    re-coded while the release update itself rolls back on the unique index.
    """
    existing = await Release.find_one(Eq(Release.upc, upc))
    if existing is not None and existing.id != release_id:
        raise DuplicateIdentifierError("upc")


async def _sync_isrc_to_clip(clip_id: PydanticObjectId, user_id: str, isrc: str) -> None:
    """Mirror a release's ISRC onto its source recording (clip).

    A deleted source clip is tolerated (the release keeps its own code); a code
    already held by a different recording surfaces as a duplicate (409).
    """
    clip = await clip_service.find_owned_clip(str(clip_id), user_id)
    if clip is None or clip.isrc == isrc:
        return
    clip.isrc = isrc
    try:
        await clip.save()
    except DuplicateKeyError as exc:
        raise DuplicateIdentifierError("isrc") from exc


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
    # Reject a duplicate UPC up front, so a clashing override can't re-code the
    # clip (below) and then have the release write roll back on the unique index.
    # With this pre-check both sequential failure directions stay clean: a UPC
    # clash 409s here before any write; an ISRC clash 409s in the clip sync below,
    # before release.save(). The residual is a true-concurrency TOCTOU that only a
    # multi-doc transaction could close (unavailable on standalone MongoDB); the
    # unique indexes still guarantee no duplicate is ever persisted.
    if updates.get("upc") is not None:
        await _ensure_upc_unused(updates["upc"], release.id)
    for field, value in updates.items():
        setattr(release, field, value)
    release.updated_at = utcnow()
    # A manual ISRC *override* re-identifies the recording, so mirror it onto the
    # clip before persisting the release (so the two never diverge on a clash).
    # Clearing it (isrc=None) only drops the release's copy: the recording keeps
    # its permanent, never-reused code on the clip, so the mirror isn't synced.
    if updates.get("isrc") is not None:
        await _sync_isrc_to_clip(release.clip_id, user_id, updates["isrc"])
    try:
        await release.save()
    except DuplicateKeyError as exc:  # manual UPC already used by another release
        raise DuplicateIdentifierError(_duplicate_field(exc)) from exc
    return release
