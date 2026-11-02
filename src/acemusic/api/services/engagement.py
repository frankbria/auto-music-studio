"""Plays, likes and shares of public clips, and the staff picks (#656).

Owner decisions (2026-11-01): a play counts after 30 s of listening (the client reports it then), once per listener
per clip per hour; a like is signed-in only, one per user, undoable; a share is a Share click or link copy, once per
user per clip per day. The unique index on :class:`ClipEngagement` enforces each "once": an insert that succeeds is
one more count, and the clip's counter moves only then.
"""

from datetime import datetime, timezone

from beanie import PydanticObjectId
from fastapi import HTTPException, status
from pymongo.errors import DuplicateKeyError

from ..models import Clip, ClipEngagement, EngagementKind
from .clips import public_clip_filter
from .common import coerce_object_id

_COUNTER: dict[EngagementKind, str] = {"play": "play_count", "like": "like_count", "share": "share_count"}
_BUCKET_FORMAT: dict[EngagementKind, str] = {"play": "%Y-%m-%dT%H", "share": "%Y-%m-%d", "like": ""}


async def _public_clip_id(clip_id: str) -> PydanticObjectId:
    oid = coerce_object_id(clip_id)
    if oid is None or not await Clip.find_one({"_id": oid, **await public_clip_filter()}):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clip not found.")
    return oid


async def _count_once(clip_id: PydanticObjectId, kind: EngagementKind, actor: str) -> bool:
    bucket = datetime.now(timezone.utc).strftime(_BUCKET_FORMAT[kind])
    try:
        await ClipEngagement(clip_id=clip_id, kind=kind, actor=actor, bucket=bucket).insert()
    except DuplicateKeyError:
        return False
    await Clip.find({"_id": clip_id}).update({"$inc": {_COUNTER[kind]: 1}})
    return True


async def record_play(clip_id: str, actor: str) -> bool:
    """Count a play of a public clip; False when this listener's play this hour already counted."""
    return await _count_once(await _public_clip_id(clip_id), "play", actor)


async def record_share(clip_id: str, actor: str) -> bool:
    """Count a share of a public clip; False when this user's share today already counted."""
    return await _count_once(await _public_clip_id(clip_id), "share", actor)


async def set_like(clip_id: str, user_id: str, liked: bool) -> int:
    """Like or unlike a public clip for ``user_id``; return its like count. Repeating either is a no-op."""
    oid = await _public_clip_id(clip_id)
    if liked:
        await _count_once(oid, "like", user_id)
    else:
        removed = await ClipEngagement.get_pymongo_collection().delete_one(
            {"clip_id": oid, "kind": "like", "actor": user_id, "bucket": ""}
        )
        if removed.deleted_count:
            await Clip.find({"_id": oid}).update({"$inc": {"like_count": -1}})
    clip = await Clip.get(oid)
    return clip.like_count if clip else 0


async def liked_clip_ids(user_id: str | None, clip_ids: list[PydanticObjectId]) -> set[str]:
    """Which of ``clip_ids`` ``user_id`` has liked, for one page of cards."""
    if not user_id or not clip_ids:
        return set()
    rows = ClipEngagement.get_pymongo_collection().find(
        {"clip_id": {"$in": clip_ids}, "kind": "like", "actor": user_id, "bucket": ""}, {"clip_id": 1}
    )
    return {str(row["clip_id"]) async for row in rows}


async def get_clip(clip_id: str) -> Clip:
    """Any clip by id, for an admin; 404 when unknown."""
    oid = coerce_object_id(clip_id)
    clip = await Clip.get(oid) if oid else None
    if clip is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clip not found.")
    return clip


async def set_staff_pick(clip_id: str, picked: bool) -> datetime | None:
    """Mark or unmark a clip as a staff pick; return its pick date (None when unmarked). 404 for an unknown clip."""
    oid = coerce_object_id(clip_id)
    picked_at = datetime.now(timezone.utc) if picked else None
    result = await Clip.find({"_id": oid}).update({"$set": {"staff_picked_at": picked_at}}) if oid else None
    if result is None or not result.matched_count:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clip not found.")
    return picked_at


async def backfill_counters() -> int:
    """Give clips written before #656 zeroed counters, so the play-count keyset compares numbers; return how many.

    shortcut: scans clips missing the field on every startup; drop it once every deployment has run it.
    """
    result = await Clip.get_pymongo_collection().update_many(
        {"play_count": {"$exists": False}}, {"$set": {"play_count": 0, "like_count": 0, "share_count": 0}}
    )
    return result.modified_count
