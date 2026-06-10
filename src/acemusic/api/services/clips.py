"""Clip access service (US-9.3).

Resolves a clip for audio retrieval and enforces the visibility rules from
issue #77: a clip that does not exist (or has a malformed id) is 404; another
user's private clip is 403; the owner and any authenticated user (for public
clips) get the clip back.
"""

from beanie import PydanticObjectId
from fastapi import HTTPException, status

from ..models import Clip


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
