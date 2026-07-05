"""Clip access and CRUD service (US-9.3, US-9.4).

Resolves a clip for audio retrieval and enforces the visibility rules from
issue #77: a clip that does not exist (or has a malformed id) is 404; another
user's private clip is 403; the owner and any authenticated user (for public
clips) get the clip back.

CRUD (issue #78) is stricter: list/get/update/delete are owner-scoped, so
another user's clip — public or not — is a plain 404. Public visibility only
ever applies to the audio endpoint.
"""

import asyncio
import logging
import re
from pathlib import Path
from typing import Literal

from beanie import PydanticObjectId
from beanie.operators import In
from fastapi import HTTPException, status

from acemusic.storage import get_storage_backend

from ..models import ArtworkOption, Clip
from . import daw_export as daw_export_service, workspaces as workspace_service
from .common import coerce_object_id

logger = logging.getLogger(__name__)

# US-10.6: cap ancestry traversal so a corrupt/cyclic graph can never walk
# unboundedly. 50 levels is the documented maximum lineage depth.
MAX_LINEAGE_DEPTH = 50

# US-14.4: relative major/minor pairs ("C major" shares notes with "A minor"),
# so a clip in one key is musically similar to a clip in its relative. Stored
# both directions for an O(1) lookup; keys are compared lowercased.
RELATIVE_KEYS: dict[str, str] = {
    "c major": "a minor",
    "g major": "e minor",
    "d major": "b minor",
    "a major": "f# minor",
    "e major": "c# minor",
    "b major": "g# minor",
    "f# major": "d# minor",
    "db major": "bb minor",
    "ab major": "f minor",
    "eb major": "c minor",
    "bb major": "g minor",
    "f major": "d minor",
}
RELATIVE_KEYS.update({v: k for k, v in list(RELATIVE_KEYS.items())})

# US-14.4: a similar clip must share at least one style tag with the seed or sit
# within this fraction of its BPM (acceptance criteria). The same window gates
# the BPM scoring bonus.
BPM_PROXIMITY = 0.10


def keys_are_related(key1: str | None, key2: str | None) -> bool:
    """True if two musical keys are identical or a relative major/minor pair.

    None for either side means "unknown key" — not a match. Comparison is
    case-insensitive ("C major" == "c MAJOR").
    """
    if key1 is None or key2 is None:
        return False
    k1, k2 = key1.strip().lower(), key2.strip().lower()
    return k1 == k2 or RELATIVE_KEYS.get(k1) == k2


def compute_similarity_score(seed: Clip, candidate: Clip) -> int:
    """Score ``candidate`` against ``seed`` (US-14.4): higher = more similar.

    +1 per shared style tag (case-insensitive), +1 if BPM is within
    ``BPM_PROXIMITY``, +1 if the keys are related, +1 if model *and*
    generation_mode both match. Criteria where the seed's field is unset
    (None/empty) are skipped — they neither add nor subtract — so a sparsely
    tagged seed still ranks candidates by what it does have.
    """
    score = 0
    if seed.style_tags:
        seed_tags = {t.lower() for t in seed.style_tags}
        cand_tags = {t.lower() for t in candidate.style_tags}
        score += len(seed_tags & cand_tags)
    if seed.bpm and candidate.bpm is not None and abs(candidate.bpm - seed.bpm) <= seed.bpm * BPM_PROXIMITY:
        score += 1
    if keys_are_related(seed.key, candidate.key):
        score += 1
    if (
        seed.model
        and seed.generation_mode
        and seed.model == candidate.model
        and seed.generation_mode == candidate.generation_mode
    ):
        score += 1
    return score


async def find_similar_clips(
    clip_id: str,
    user_id: str,
    scope: Literal["mine", "public", "all"] = "all",
    limit: int = 20,
) -> tuple[list[Clip], int]:
    """Return clips similar to ``clip_id`` plus the total number of candidates.

    The seed is resolved with :func:`get_clip_for_audio_access`, so any clip the
    caller may see (their own, or a public one) can seed a radio queue (404
    unknown, 403 another user's private clip). ``scope`` limits the candidate
    pool to the caller's clips (``mine``), public clips (``public``), or both
    (``all``).

    Candidates must clear the base-similarity bar — share a style tag or fall
    within ``BPM_PROXIMITY`` of the seed's BPM — then are scored and sorted in
    Python (descending score, newest first as a tiebreak). A seed with neither
    tags nor BPM has no bar to match, so the result is empty.
    """
    seed = await get_clip_for_audio_access(clip_id, user_id)

    similarity_clauses: list[dict] = []
    if seed.style_tags:
        # Match tags case-insensitively so the DB filter agrees with the
        # case-insensitive scorer (and with list_clips' style filter). An
        # anchored IGNORECASE regex is an exact tag match ignoring case; $in
        # keeps a candidate if any of its tags matches any of the seed's.
        tag_patterns = [re.compile(f"^{re.escape(tag)}$", re.IGNORECASE) for tag in seed.style_tags]
        similarity_clauses.append({"style_tags": {"$in": tag_patterns}})
    if seed.bpm:
        similarity_clauses.append(
            {"bpm": {"$gte": seed.bpm * (1 - BPM_PROXIMITY), "$lte": seed.bpm * (1 + BPM_PROXIMITY)}}
        )
    if not similarity_clauses:
        return [], 0

    owner = PydanticObjectId(user_id)
    if scope == "mine":
        scope_clause: dict = {"user_id": owner}
    elif scope == "public":
        scope_clause = {"is_public": True}
    else:
        scope_clause = {"$or": [{"user_id": owner}, {"is_public": True}]}

    query = {
        "$and": [
            scope_clause,
            {"$or": similarity_clauses},
            {"_id": {"$ne": seed.id}},
        ]
    }
    candidates = await Clip.find(query).to_list()
    candidates.sort(key=lambda c: (compute_similarity_score(seed, c), c.created_at), reverse=True)
    return candidates[:limit], len(candidates)


async def get_clip_for_audio_access(clip_id: str, current_user_id: str) -> Clip:
    """Return ``clip_id``'s clip if ``current_user_id`` may retrieve its audio.

    Raises 404 for malformed/unknown ids and 403 for another user's private
    clip. Unlike jobs (which 404 to hide existence), clips deliberately
    distinguish 403 so sharing flows can tell "ask the owner" from "gone".
    """
    oid = coerce_object_id(clip_id)
    clip = await Clip.get(oid) if oid is not None else None
    if clip is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clip not found.")
    if str(clip.user_id) != current_user_id and not clip.is_public:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This clip is private.")
    return clip


async def get_clip_for_streaming(clip_id: str, current_user_id: str | None) -> Clip:
    """Resolve a clip for the public streaming endpoint (US-14.2).

    Authenticated requests follow :func:`get_clip_for_audio_access` (404 for
    unknown, 403 for another user's private clip). Anonymous requests
    (``current_user_id is None``) may only reach public clips; a private or
    unknown clip is an indistinguishable 404 so the endpoint never reveals a
    private clip's existence to a stranger.
    """
    if current_user_id is not None:
        return await get_clip_for_audio_access(clip_id, current_user_id)

    oid = coerce_object_id(clip_id)
    clip = await Clip.get(oid) if oid is not None else None
    if clip is None or not clip.is_public:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clip not found.")
    return clip


def _clip_not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clip not found.")


def native_format(clip: Clip) -> str:
    """The clip's stored audio format: the ``format`` field, falling back to
    the ``file_path`` suffix (legacy/imported documents may lack the field),
    then to wav."""
    return (clip.format or Path(clip.file_path).suffix.lstrip(".") or "wav").lower()


def _contains_regex(text: str) -> dict:
    """Case-insensitive substring matcher, with the needle treated literally."""
    return {"$regex": re.escape(text), "$options": "i"}


async def find_owned_clip(clip_id: str, user_id: str) -> Clip | None:
    """Return the clip if ``user_id`` owns it, else None (no raise).

    The non-raising sibling of :func:`get_owned_clip`, for callers that must
    handle an unknown/not-owned clip without aborting — e.g. batch processing
    (US-10.5), which records a per-clip failure and continues rather than failing
    the whole request.
    """
    oid = coerce_object_id(clip_id)
    clip = await Clip.get(oid) if oid is not None else None
    if clip is None or str(clip.user_id) != user_id:
        return None
    return clip


async def get_owned_clip(clip_id: str, user_id: str) -> Clip:
    """Return the clip if ``user_id`` owns it; 404 for unknown/malformed/not-owned ids."""
    clip = await find_owned_clip(clip_id, user_id)
    if clip is None:
        raise _clip_not_found()
    return clip


async def list_clips(
    user_id: str,
    *,
    workspace_id: str | None = None,
    search: str | None = None,
    style: str | None = None,
    bpm_min: int | None = None,
    bpm_max: int | None = None,
    key: str | None = None,
    model: str | None = None,
    sort: Literal["newest", "oldest"] = "newest",
    page: int = 1,
    per_page: int = 20,
) -> tuple[list[Clip], int]:
    """Return one page of the user's clips plus the total match count.

    Filters mirror the CLI's ``search_clips`` (US-4.2): ``style`` and ``search``
    are case-insensitive substring matches (``search`` over title *or* style
    tags), BPM is a closed range, ``key``/``model`` are exact. A ``workspace_id``
    filter is validated for ownership first and raises 404 like any other
    workspace access.
    """
    query: dict = {"user_id": PydanticObjectId(user_id)}
    if workspace_id is not None:
        workspace = await workspace_service.get_workspace(workspace_id, user_id)
        query["workspace_id"] = workspace.id
    if style is not None:
        query["style_tags"] = _contains_regex(style)
    if search is not None:
        needle = _contains_regex(search)
        query["$or"] = [{"title": needle}, {"style_tags": needle}]
    if bpm_min is not None or bpm_max is not None:
        bpm_range: dict = {}
        if bpm_min is not None:
            bpm_range["$gte"] = bpm_min
        if bpm_max is not None:
            bpm_range["$lte"] = bpm_max
        query["bpm"] = bpm_range
    if key is not None:
        query["key"] = key
    if model is not None:
        query["model"] = model

    total = await Clip.find(query).count()
    direction = -1 if sort == "newest" else 1
    # _id tiebreak keeps pagination stable when created_at values collide.
    items = (
        await Clip.find(query)
        .sort(("created_at", direction), ("_id", direction))
        .skip((page - 1) * per_page)
        .limit(per_page)
        .to_list()
    )
    return items, total


def _enforce_publish_guard(clip: Clip) -> None:
    """Reject going public until the clip is presentable (US-17.6).

    A public clip needs a real title and at least one style tag; publishing a
    half-finished clip by accident is the failure this guards against. Fail-closed
    with a 422 that names exactly what's missing so the UI can prompt for it.
    Unpublishing is never guarded (see ``update_clip_fields``).
    """
    missing: list[str] = []
    if not (clip.title and clip.title.strip()):
        missing.append("a title")
    if not clip.style_tags:
        missing.append("at least one style tag")
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Publishing requires {' and '.join(missing)}.",
        )


async def update_clip_fields(
    clip_id: str,
    user_id: str,
    *,
    title: str | None = None,
    is_public: bool | None = None,
) -> Clip:
    """Apply the client-writable clip fields — title (rename) and/or is_public
    (the US-17.6 publish toggle). ``None`` leaves a field unchanged. A title
    supplied in the same call is applied before the publish guard runs, so a
    rename-and-publish request is validated against the new title."""
    clip = await get_owned_clip(clip_id, user_id)
    if title is not None:
        clip.title = title
    if is_public:
        _enforce_publish_guard(clip)
    if is_public is not None:
        clip.is_public = is_public
    if title is not None or is_public is not None:
        await clip.save()
    return clip


async def delete_clip(clip_id: str, user_id: str) -> None:
    """Delete the clip record and its stored audio (idempotent on the object).

    Also removes any extracted MIDI objects (US-10.2 ``midi_paths``), cover-art
    artifacts (US-13.1: the selected ``artwork_path`` plus every generated
    ``ArtworkOption`` and its image), and the DAW-export bundle (US-14.1), which
    live under their own storage keys rather than ``file_path`` and would
    otherwise be orphaned with the parent clip.
    """
    clip = await get_owned_clip(clip_id, user_id)
    storage = get_storage_backend()
    # delete() does file/network I/O via the sync backend; keep it off the
    # event loop. Storage goes first so a crash between the two steps leaves a
    # re-deletable record rather than an orphaned file.
    await asyncio.to_thread(storage.delete, clip.file_path)
    # MIDI cleanup is best-effort per key: one failing delete must not strand the
    # remaining objects or block the clip-record deletion (matches the defensive
    # cleanup in the extraction task handlers).
    for midi_key in (clip.midi_paths or {}).values():
        try:
            await asyncio.to_thread(storage.delete, midi_key)
        except Exception:  # pragma: no cover - cleanup is best-effort
            logger.warning("Failed to delete MIDI object %s while deleting clip %s", midi_key, clip.id)
    await _delete_artwork(storage, clip)
    # DAW-export bundle (US-14.1): the predictable per-clip ZIP the export worker
    # writes under its own key, orphaned otherwise. Best-effort and idempotent
    # (a never-exported clip has no object to remove), like the MIDI cleanup.
    export_key = daw_export_service.export_storage_path(clip.user_id, clip.workspace_id, clip.id)
    try:
        await asyncio.to_thread(storage.delete, export_key)
    except Exception:  # pragma: no cover - cleanup is best-effort
        logger.warning("Failed to delete DAW export object %s while deleting clip %s", export_key, clip.id)
    await clip.delete()


async def _delete_artwork(storage, clip: Clip) -> None:
    """Best-effort removal of a clip's cover art and all generated options."""
    options = await ArtworkOption.find(ArtworkOption.clip_id == clip.id).to_list()
    # The selected artwork may be an upload (no ArtworkOption row), so delete it
    # explicitly too; options cover the generated batch. De-dup so a selected
    # option's object is not deleted twice.
    paths = {opt.storage_path for opt in options}
    if clip.artwork_path:
        paths.add(clip.artwork_path)
    for path in paths:
        try:
            await asyncio.to_thread(storage.delete, path)
        except Exception:  # pragma: no cover - cleanup is best-effort
            logger.warning("Failed to delete artwork object %s while deleting clip %s", path, clip.id)
    for opt in options:
        try:
            await opt.delete()
        except Exception:  # pragma: no cover - cleanup is best-effort
            logger.warning("Failed to delete artwork option %s while deleting clip %s", opt.id, clip.id)


async def get_lineage(
    clip_id: str,
    user_id: str,
    *,
    max_depth: int = MAX_LINEAGE_DEPTH,
) -> tuple[list[tuple[Clip, int]], bool]:
    """Return the clip's ancestry tree as ``(clip, depth)`` pairs, plus a
    ``truncated`` flag (US-10.6).

    The subject clip is depth 0; its ``parent_clip_ids`` are depth 1, their
    parents depth 2, and so on up to the original generation. Traversal walks the
    graph breadth-first, resolving one whole depth level per query
    (``In(Clip.id, …)``), so a 20-level chain costs ~20 indexed ``_id`` lookups
    rather than one round-trip per node.

    Ownership-scoped to ``user_id`` (matching CRUD): the subject 404s if not
    owned, and an ancestor owned by someone else (e.g. a public clip derived
    from) is simply absent from the tree rather than leaked. A ``visited`` set
    collapses diamond lineage (shared ancestors via multi-parent mashups) to a
    single node and guards against cycles. ``truncated`` is True when ancestors
    remain beyond ``max_depth``.
    """
    subject = await get_owned_clip(clip_id, user_id)
    owner = PydanticObjectId(user_id)

    nodes: list[tuple[Clip, int]] = [(subject, 0)]
    visited: set[PydanticObjectId] = {subject.id}
    frontier: set[PydanticObjectId] = {pid for pid in subject.parent_clip_ids if pid not in visited}

    truncated = False
    depth = 1
    while frontier:
        if depth > max_depth:
            # Ancestors still reachable past the cap — report it rather than
            # silently dropping them.
            truncated = True
            break
        level = await Clip.find(In(Clip.id, list(frontier)), Clip.user_id == owner).to_list()
        # Stable ordering keeps the response deterministic regardless of how the
        # database returns the batch (oldest first, then id as a tiebreak).
        level.sort(key=lambda c: (c.created_at, c.id))
        next_frontier: set[PydanticObjectId] = set()
        for clip in level:
            if clip.id in visited:
                continue
            visited.add(clip.id)
            nodes.append((clip, depth))
            next_frontier.update(pid for pid in clip.parent_clip_ids if pid not in visited)
        frontier = next_frontier
        depth += 1

    return nodes, truncated


async def get_children(clip_id: str, user_id: str) -> tuple[Clip, list[Clip]]:
    """Return the clip plus the clips directly derived from it (US-10.6).

    A child is any owned clip that lists ``clip_id`` among its
    ``parent_clip_ids`` — covers single-source ops (extend/cover/remix/stems/…)
    and multi-source mashups alike. Owner-scoped like the rest of clip CRUD;
    newest-first for a stable, useful order.

    Returns the full child set unpaginated: a clip's direct children are bounded
    by how many times the user has derived from it. If a frequently-sampled clip
    ever makes this unbounded, add pagination here (mirroring ``list_clips``).
    """
    clip = await get_owned_clip(clip_id, user_id)
    children = (
        await Clip.find(
            In(Clip.parent_clip_ids, [clip.id]),
            Clip.user_id == PydanticObjectId(user_id),
        )
        .sort(("created_at", -1), ("_id", -1))
        .to_list()
    )
    return clip, children
