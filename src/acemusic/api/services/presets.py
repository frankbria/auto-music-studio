"""Preset service layer (US-9.5).

Owns user-scoped preset CRUD. Ownership failures and unknown/malformed ids
surface as 404 so the API never reveals whether another user's preset exists,
mirroring :mod:`acemusic.api.services.workspaces`.
"""

from beanie import PydanticObjectId
from beanie.operators import Eq
from fastapi import HTTPException, status
from pymongo.errors import DuplicateKeyError

from ..models import Preset
from ..models.common import utcnow


def _coerce_object_id(value: str) -> PydanticObjectId | None:
    """Parse a path id, treating a malformed id as "no such preset" (→ 404)."""
    try:
        return PydanticObjectId(value)
    except Exception:
        return None


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preset not found.")


def _name_conflict(name: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=f"A preset named {name!r} already exists.",
    )


async def create_preset(user_id: str, name: str, params: dict) -> Preset:
    """Create a preset for ``user_id``. Raises 409 if the name is taken.

    ``params`` holds only generation parameter fields (the router validates
    and dumps them), so identity fields cannot be injected through it.
    """
    preset = Preset(name=name, user_id=PydanticObjectId(user_id), **params)
    try:
        await preset.insert()
    except DuplicateKeyError as exc:
        raise _name_conflict(name) from exc
    return preset


async def list_presets(user_id: str) -> list[Preset]:
    """Return all of ``user_id``'s presets, oldest first."""
    return await Preset.find(Eq(Preset.user_id, PydanticObjectId(user_id))).sort("+created_at").to_list()


async def get_preset(preset_id: str, user_id: str) -> Preset:
    """Return the preset if ``user_id`` owns it; 404 for unknown/malformed/not-owned ids."""
    oid = _coerce_object_id(preset_id)
    preset = await Preset.get(oid) if oid is not None else None
    if preset is None or str(preset.user_id) != user_id:
        raise _not_found()
    return preset


async def update_preset(preset_id: str, user_id: str, updates: dict) -> Preset:
    """Apply ``updates`` (explicitly-sent fields only, may include ``None`` to
    clear a parameter). Raises 404 if not owned, 409 on a name collision."""
    preset = await get_preset(preset_id, user_id)
    for field, value in updates.items():
        setattr(preset, field, value)
    preset.updated_at = utcnow()
    try:
        await preset.save()
    except DuplicateKeyError as exc:
        raise _name_conflict(preset.name) from exc
    return preset


async def delete_preset(preset_id: str, user_id: str) -> None:
    """Delete the preset. Raises 404 for unknown/malformed/not-owned ids."""
    preset = await get_preset(preset_id, user_id)
    await preset.delete()
