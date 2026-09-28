"""Release package service layer (US-13.3).

Owns user-scoped release CRUD. Ownership failures and unknown/malformed ids
surface as 404 so the API never reveals another user's releases (mirrors
:mod:`acemusic.api.services.presets`). Required-metadata validation lives at the
Pydantic schema layer (422); this layer enforces clip ownership and the
post-submission edit lock (409).
"""

import logging

from beanie import PydanticObjectId
from beanie.operators import Eq
from fastapi import HTTPException, status
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from ..exceptions import DuplicateIdentifierError
from ..models import Clip, ModerationLogEntry, Release, ReleaseStatus
from ..models.common import utcnow
from ..models.distribution import VisibilityState
from ..settings import ApiSettings
from . import clips as clip_service, identifiers, screening, soundcloud as sc
from .common import coerce_object_id
from .mastering import APPROVED_GENERATION_MODE

logger = logging.getLogger(__name__)

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
    clip_service.ensure_not_removed(clip)
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
    for _ in range(_MAX_MINT_ATTEMPTS):
        minted = await identifiers.generate_isrc(settings)
        try:
            doc = await Clip.get_pymongo_collection().find_one_and_update(
                {"_id": clip.id, "isrc": None},
                {"$set": {"isrc": minted}},
                return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError:
            continue  # a manual override took this slot — mint the next (as for UPC)
        if doc is not None:
            return doc["isrc"]  # we won the claim
        # A concurrent creation already coded the clip — read back the canonical value.
        refreshed = await Clip.get(clip.id)
        return refreshed.isrc if refreshed and refreshed.isrc else minted
    raise DuplicateIdentifierError("isrc")


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
    try:
        await clip.set({"isrc": isrc})
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

    ``updates`` must come from a validated ``ReleaseUpdate`` dump — the ``$set``
    trusts its keys, so a raw dict could reassign identity fields like
    ``user_id`` (same contract as ``create_release``).
    """
    release = await get_owned_release(release_id, user_id)
    if release.status not in _EDITABLE_STATUSES:
        raise _state_error("Release metadata cannot be modified after submission")
    # Reject a duplicate UPC up front, so a clashing override can't re-code the
    # clip (below) and then have the release write roll back on the unique index.
    # With this pre-check both sequential failure directions stay clean: a UPC
    # clash 409s here before any write; an ISRC clash 409s in the clip sync below,
    # before the release write. The residual is a true-concurrency TOCTOU that only a
    # multi-doc transaction could close (unavailable on standalone MongoDB); the
    # unique indexes still guarantee no duplicate is ever persisted.
    if updates.get("upc") is not None:
        await _ensure_upc_unused(updates["upc"], release.id)
    # A manual ISRC *override* re-identifies the recording, so mirror it onto the
    # clip before persisting the release (so the two never diverge on a clash).
    # Clearing it (isrc=None) only drops the release's copy: the recording keeps
    # its permanent, never-reused code on the clip, so the mirror isn't synced.
    if updates.get("isrc") is not None:
        await _sync_isrc_to_clip(release.clip_id, user_id, updates["isrc"])
    try:
        # $set, not save(): a whole-document write would revert a moderation privatization (#538).
        await release.set({**updates, "updated_at": utcnow()})
    except DuplicateKeyError as exc:  # manual UPC already used by another release
        raise DuplicateIdentifierError(_duplicate_field(exc)) from exc
    return release


async def ensure_source_not_removed(release: Release) -> None:
    """403 when ``release``'s source clip was removed by moderation; a deleted clip passes."""
    clip = await clip_service.find_owned_clip(str(release.clip_id), str(release.user_id))
    if clip is not None:
        clip_service.ensure_not_removed(clip)


async def source_clip_visibility_update(release: Release, visibility: VisibilityState) -> dict:
    """The update that mirrors ``visibility`` onto ``release``'s source clip, for :func:`update_visibility`.

    Run before anything is shared: a clip removed by moderation refuses anything but private
    (US-27.3), and a clip going visible has its text screened (#531) — 403 / 422 respectively.
    A deleted source clip is tolerated (the release keeps its visibility).
    """
    fields = {"visibility": visibility.value, "is_public": visibility == VisibilityState.PUBLIC}
    clip = await clip_service.find_owned_clip(str(release.clip_id), str(release.user_id))
    if clip is None or visibility == VisibilityState.PRIVATE:
        return {"$set": fields}
    clip_service.ensure_not_removed(clip)
    return await clip_service.screened_update(clip, screening.clip_texts(clip), fields)


async def update_visibility(release: Release, visibility: VisibilityState, clip_update: dict) -> Release:
    """Set ``release``'s visibility and mirror it onto the source clip (US-13.6).

    Takes an already-owned ``release`` (the router has validated ownership), so it
    does not re-fetch. Visibility is a sharing preference, not part of the
    submission lifecycle, so it is editable in any state (unlike metadata, which
    locks after submission). The source clip's own ``visibility`` (US-20.7,
    which gates non-owner audio access) is mirrored to match, together with its
    ``is_public`` denormalization, via ``clip_update`` from :func:`source_clip_visibility_update`.
    """
    # One conditional update, not read-then-save: a save would write back a stale snapshot and
    # revert an admin removal landing in between. A deleted or removed clip simply matches nothing;
    # a removal that landed since the router's check refuses the release too, rather than leaving
    # it public over a private clip.
    result = await Clip.find_one({"_id": release.clip_id, "user_id": release.user_id, "removed_at": None}).update(
        clip_update
    )
    if not result.matched_count and visibility != VisibilityState.PRIVATE:
        await ensure_source_not_removed(release)

    await release.set({"visibility": visibility, "updated_at": utcnow()})
    return release


async def unshare_if_source_removed(
    clip_id: PydanticObjectId,
    user_id: PydanticObjectId | str,
    settings: ApiSettings,
    *,
    release_id: PydanticObjectId | None = None,
    track_id: str | None = None,
) -> None:
    """Undo a share if moderation removed the source clip meanwhile (#538), then 403.

    Called after a route has shared a release (``release_id``) or a bare track (``track_id``) out. A removal
    landing mid-request ran its own un-share before this request's SoundCloud call, so it's repeated here.
    A failure gets its own moderation log entry: the removal's entry was written without it.
    """
    clip = await clip_service.find_owned_clip(str(clip_id), str(user_id))
    if clip is None or clip.removed_at is None:
        return
    if release_id is not None:
        failed = (await unshare_releases({"_id": release_id}, settings))["soundcloud_unshare_failed"]
    else:
        error = await unshare_track(str(user_id), track_id, settings)
        failed = [] if error is None else [{"track_id": track_id, "error": error}]
    if failed:
        await ModerationLogEntry(
            actor_id=clip.user_id,
            action="soundcloud_unshare_failed",
            target_type="clip",
            target_id=str(clip.id),
            details={"soundcloud_unshare_failed": failed},
        ).insert()
    clip_service.ensure_not_removed(clip)


async def unshare_releases(query: dict, settings: ApiSettings) -> dict:
    """Make every release matching ``query`` private and best-effort un-share its SoundCloud track (#538).

    The local write always stands. A track that can't be reached (unlinked account, revoked grant,
    SoundCloud down) is returned in ``soundcloud_unshare_failed`` for the caller to surface.
    """
    # Write, then read: a track id recorded before the write is seen; one recorded after it is the
    # uploader's to un-share (unshare_if_source_removed).
    await Release.find(query).update({"$set": {"visibility": VisibilityState.PRIVATE.value, "updated_at": utcnow()}})
    releases = await Release.find(query).to_list()
    unshared: list[str] = []
    failed: list[dict] = []
    for release in releases:
        if not release.soundcloud_track_id:
            continue
        error = await unshare_track(str(release.user_id), release.soundcloud_track_id, settings)
        if error is None:
            unshared.append(release.soundcloud_track_id)
        else:
            failed.append({"track_id": release.soundcloud_track_id, "error": error})
    return {"releases_privatized": len(releases), "soundcloud_unshared": unshared, "soundcloud_unshare_failed": failed}


async def unshare_track(user_id: str, track_id: str, settings: ApiSettings) -> str | None:
    """Set a SoundCloud track private on ``user_id``'s account; the error message on failure, else ``None``."""
    try:
        connection = await sc.get_valid_connection(user_id, settings)
        await sc.update_track_sharing(connection.access_token, track_id, "private")
    except sc.SoundCloudError as exc:
        logger.warning("Un-sharing SoundCloud track %s failed: %s", track_id, exc)
        return str(exc)
    return None


# A submission can only be confirmed once the package is assembled, and re-confirmed
# for a further target after it has gone out — never from draft or a terminal state.
_CONFIRMABLE_STATUSES = {ReleaseStatus.READY, ReleaseStatus.SUBMITTED}


async def confirm_submission(release_id: str, user_id: str, target: str) -> Release:
    """Mark an owned release submitted to ``target`` (US-13.5).

    Transitions ``ready``/``submitted`` → ``submitted`` and records ``target`` in
    ``submitted_channels`` (deduped, so re-confirming the same target is a no-op).
    Raises 404 if not owned, 409 from ``draft`` or a terminal state.
    """
    release = await get_owned_release(release_id, user_id)
    await ensure_source_not_removed(release)
    if release.status not in _CONFIRMABLE_STATUSES:
        raise _state_error(f"Release cannot be submitted from status {release.status.value!r}")
    # Atomic $addToSet + guarded $set so concurrent confirmations of different
    # targets can't lose a channel via read-modify-write (same care the ISRC/UPC
    # claims take). The status filter re-checks the transition at write time.
    confirmable = [s.value for s in _CONFIRMABLE_STATUSES]
    doc = await Release.get_pymongo_collection().find_one_and_update(
        # user_id in the filter too: closes the TOCTOU gap between the ownership
        # read above and this write (the unique-claim helpers filter the same way).
        {"_id": release.id, "user_id": release.user_id, "status": {"$in": confirmable}},
        {
            "$addToSet": {"submitted_channels": target},
            "$set": {"status": ReleaseStatus.SUBMITTED.value, "updated_at": utcnow()},
        },
    )
    if doc is None:  # a concurrent transition moved it out of a confirmable state
        raise _state_error("Release is no longer in a submittable state")
    return await get_owned_release(release_id, user_id)
