"""Helpers shared across the API service modules."""

from beanie import PydanticObjectId


def coerce_object_id(value: str) -> PydanticObjectId | None:
    """Parse a path id, treating a malformed id as "no such document" (→ 404).

    Used by the ownership-checked lookups (clips, workspaces, presets) so a
    malformed id is indistinguishable from a missing or not-owned one.
    """
    try:
        return PydanticObjectId(value)
    except Exception:
        return None
