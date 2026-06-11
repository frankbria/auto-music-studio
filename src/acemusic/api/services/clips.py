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
import re
from typing import Literal

from beanie import PydanticObjectId
from fastapi import HTTPException, status

from acemusic.storage import get_storage_backend

from ..models import Clip
from . import workspaces as workspace_service


def _coerce_object_id(value: str) -> PydanticObjectId | None:
    """Parse a path id, treating a malformed id as "no such clip" (caller → 404)."""
    try:
        return PydanticObjectId(value)
    except Exception:
        return None


async def get_clip_for_audio_access(clip_id: str, current_user_id: str) -> Clip:
    """Return ``clip_id``'s clip if ``current_user_id`` may retrieve its audio.

    Raises 404 for malformed/unknown ids and 403 for another user's private
    clip. Unlike jobs (which 404 to hide existence), clips deliberately
    distinguish 403 so sharing flows can tell "ask the owner" from "gone".
    """
    oid = _coerce_object_id(clip_id)
    clip = await Clip.get(oid) if oid is not None else None
    if clip is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clip not found.")
    if str(clip.user_id) != current_user_id and not clip.is_public:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This clip is private.")
    return clip


def _clip_not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clip not found.")


def _contains_regex(text: str) -> dict:
    """Case-insensitive substring matcher, with the needle treated literally."""
    return {"$regex": re.escape(text), "$options": "i"}


async def get_owned_clip(clip_id: str, user_id: str) -> Clip:
    """Return the clip if ``user_id`` owns it; 404 for unknown/malformed/not-owned ids."""
    oid = _coerce_object_id(clip_id)
    clip = await Clip.get(oid) if oid is not None else None
    if clip is None or str(clip.user_id) != user_id:
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


async def update_clip_title(clip_id: str, user_id: str, title: str) -> Clip:
    """Rename the clip (title is the only client-writable field, as in the CLI)."""
    clip = await get_owned_clip(clip_id, user_id)
    clip.title = title
    await clip.save()
    return clip


async def delete_clip(clip_id: str, user_id: str) -> None:
    """Delete the clip record and its stored audio (idempotent on the object)."""
    clip = await get_owned_clip(clip_id, user_id)
    # delete() does file/network I/O via the sync backend; keep it off the
    # event loop. Storage goes first so a crash between the two steps leaves a
    # re-deletable record rather than an orphaned file.
    await asyncio.to_thread(get_storage_backend().delete, clip.file_path)
    await clip.delete()
