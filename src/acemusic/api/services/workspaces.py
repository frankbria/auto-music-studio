"""Workspace service layer (US-9.4).

Owns workspace CRUD and the default-workspace bootstrap (moved here from the
generation service, which now imports it back — workspaces are this module's
domain). Ownership failures and unknown/malformed ids surface as 404 so the
API never reveals whether another user's workspace exists, mirroring
:mod:`acemusic.api.services.clips`.
"""

import asyncio

from beanie import PydanticObjectId
from beanie.operators import Eq
from fastapi import HTTPException, status
from pymongo.errors import DuplicateKeyError

from acemusic.storage import get_storage_backend

from ..models import Clip, Workspace
from ..models.common import utcnow
from .common import coerce_object_id

DEFAULT_WORKSPACE_NAME = "My Workspace"


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")


def _name_conflict(name: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=f"A workspace named {name!r} already exists.",
    )


async def _find_default_workspace(user_id: PydanticObjectId) -> Workspace | None:
    return await Workspace.find_one(Eq(Workspace.user_id, user_id), Eq(Workspace.is_default, True))


async def get_or_create_default_workspace(user_id: PydanticObjectId) -> Workspace:
    """Return the user's default workspace, creating it on first use.

    Called at registration (US-9.4: the OAuth callback bootstraps every new
    account with a default workspace) and kept as a lazy fallback in the
    generation service for accounts that predate that hook.

    The create path is race-safe: the unique partial index on
    ``(user_id, is_default=True)`` (see :class:`Workspace`) rejects a concurrent
    second insert with ``DuplicateKeyError``, which we resolve by re-reading the
    winner (mirroring ``users.get_or_create_user``).
    """
    workspace = await _find_default_workspace(user_id)
    if workspace is not None:
        return workspace
    workspace = Workspace(name=DEFAULT_WORKSPACE_NAME, user_id=user_id, is_default=True)
    try:
        await workspace.insert()
    except DuplicateKeyError:
        existing = await _find_default_workspace(user_id)
        if existing is not None:
            return existing
        # No default exists, so the collision came from the unique
        # (user_id, name) index: the user already owns a non-default workspace
        # named "My Workspace" (created via the API before this bootstrap ran).
        # Promote it rather than failing the login with a 500.
        named = await Workspace.find_one(Eq(Workspace.user_id, user_id), Eq(Workspace.name, DEFAULT_WORKSPACE_NAME))
        if named is None:
            raise
        named.is_default = True
        named.updated_at = utcnow()
        try:
            await named.save()
        except DuplicateKeyError:
            # Lost a race to a concurrent bootstrap; the winner holds the
            # default flag now.
            winner = await _find_default_workspace(user_id)
            if winner is None:
                raise
            return winner
        return named
    return workspace


async def create_workspace(user_id: str, name: str) -> Workspace:
    """Create a workspace for ``user_id``. Raises 409 if the name is taken.

    The insert always carries ``is_default=False``, so a ``DuplicateKeyError``
    here can only come from the unique ``(user_id, name)`` index — the partial
    default-workspace index never matches non-default documents.
    """
    workspace = Workspace(name=name, user_id=PydanticObjectId(user_id))
    try:
        await workspace.insert()
    except DuplicateKeyError as exc:
        raise _name_conflict(name) from exc
    return workspace


async def list_workspaces(user_id: str) -> list[tuple[Workspace, int]]:
    """Return all of ``user_id``'s workspaces (oldest first) with clip counts."""
    user_oid = PydanticObjectId(user_id)
    workspaces = await Workspace.find(Eq(Workspace.user_id, user_oid)).sort("+created_at").to_list()
    # One aggregation for all counts instead of a count query per workspace.
    rows = await Clip.aggregate(
        [
            {"$match": {"user_id": user_oid}},
            {"$group": {"_id": "$workspace_id", "count": {"$sum": 1}}},
        ]
    ).to_list()
    counts = {row["_id"]: row["count"] for row in rows}
    return [(workspace, counts.get(workspace.id, 0)) for workspace in workspaces]


async def get_workspace(workspace_id: str, user_id: str) -> Workspace:
    """Return the workspace if ``user_id`` owns it; 404 for unknown/malformed/not-owned ids."""
    oid = coerce_object_id(workspace_id)
    workspace = await Workspace.get(oid) if oid is not None else None
    if workspace is None or str(workspace.user_id) != user_id:
        raise _not_found()
    return workspace


async def count_clips(workspace: Workspace) -> int:
    """Number of clips stored in ``workspace``."""
    return await Clip.find(Eq(Clip.workspace_id, workspace.id)).count()


async def update_workspace(workspace_id: str, user_id: str, name: str) -> Workspace:
    """Rename the workspace. Raises 404 if not owned, 409 if the name is taken."""
    workspace = await get_workspace(workspace_id, user_id)
    workspace.name = name
    workspace.updated_at = utcnow()
    try:
        await workspace.save()
    except DuplicateKeyError as exc:
        raise _name_conflict(name) from exc
    return workspace


async def delete_workspace(workspace_id: str, user_id: str, *, force: bool) -> None:
    """Delete the workspace, cascading to its clips when ``force`` is set.

    * 404 — unknown/malformed id or not owned by ``user_id``
    * 400 — it is the user's last workspace (force does not override; every
      account keeps at least one workspace, matching the CLI rule)
    * 409 — the workspace still holds clips and ``force`` is false

    A forced delete removes each clip's stored audio (idempotent — a missing
    object is not an error) before the clip documents and the workspace itself,
    so a crash mid-cascade leaves re-deletable records rather than orphaned files.
    """
    workspace = await get_workspace(workspace_id, user_id)

    remaining = await Workspace.find(Eq(Workspace.user_id, workspace.user_id)).count()
    if remaining <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your last workspace.",
        )

    clip_count = await count_clips(workspace)
    if clip_count and not force:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Workspace contains {clip_count} clip(s). Pass force=true to delete it and its clips.",
        )

    if clip_count:
        storage = get_storage_backend()
        async for clip in Clip.find(Eq(Clip.workspace_id, workspace.id)):
            # delete() does file/network I/O via the sync backend; keep it off
            # the event loop.
            await asyncio.to_thread(storage.delete, clip.file_path)
        await Clip.find(Eq(Clip.workspace_id, workspace.id)).delete()

    await workspace.delete()
