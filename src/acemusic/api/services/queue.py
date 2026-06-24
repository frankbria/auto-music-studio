"""Playback queue service layer (US-14.3).

Business logic for the per-user playback queue. Every operation is scoped to a
``user_id`` (one queue per user, enforced by the unique index on
:class:`PlaybackQueue`), so cross-user access is impossible by construction.

Shuffle is history-based: ``go_next`` records where it came from in
``shuffle_history`` and picks a random unplayed clip; ``go_previous`` walks back
through that trail. This matches common player behaviour and keeps state simple.

Each mutation is a read-modify-write that ``save()``s the whole document
(last-write-wins), the same pattern as ``workspaces``/``clips``. The queue is
driven by a single user's player, so concurrent writes (e.g. two tabs) are rare
and only ever cost a lost playback-state update, not data integrity — optimistic
concurrency would be needless machinery here. Revisit with ``use_revision`` if
multi-device simultaneous editing ever becomes a real workflow.
"""

import random

from beanie import PydanticObjectId
from beanie.operators import Eq
from fastapi import HTTPException, status
from pymongo.errors import DuplicateKeyError

from ..models import PlaybackQueue, RepeatMode
from ..models.common import utcnow
from .common import coerce_object_id


def _bad_clip_id(value: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid clip id: {value!r}.")


def _not_in_queue() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clip not in queue.")


async def get_or_create_queue(user_id: str) -> PlaybackQueue:
    """Return the user's queue, creating an empty one on first use.

    Race-safe: the unique index on ``user_id`` rejects a concurrent second
    insert with ``DuplicateKeyError``, which we resolve by re-reading the winner
    (mirroring ``workspaces.get_or_create_default_workspace``).
    """
    user_oid = PydanticObjectId(user_id)
    queue = await PlaybackQueue.find_one(Eq(PlaybackQueue.user_id, user_oid))
    if queue is not None:
        return queue
    queue = PlaybackQueue(user_id=user_oid)
    try:
        await queue.insert()
    except DuplicateKeyError:
        existing = await PlaybackQueue.find_one(Eq(PlaybackQueue.user_id, user_oid))
        if existing is None:
            raise
        return existing
    return queue


def _shift_index(idx: int, old: int, new: int) -> int:
    """Map ``idx`` after the element at ``old`` moves to ``new`` in a list."""
    if idx == old:
        return new
    if old < idx <= new:
        return idx - 1
    if new <= idx < old:
        return idx + 1
    return idx


async def add_clips(user_id: str, clip_ids: list[str], position: int | None) -> PlaybackQueue:
    """Insert ``clip_ids`` at ``position`` (append if None/beyond end, clamp negatives)."""
    new_clips: list[PydanticObjectId] = []
    for raw in clip_ids:
        oid = coerce_object_id(raw)
        if oid is None:
            raise _bad_clip_id(raw)
        new_clips.append(oid)

    queue = await get_or_create_queue(user_id)
    if position is None or position > len(queue.clips):
        position = len(queue.clips)
    elif position < 0:
        position = 0

    was_empty = not queue.clips
    queue.clips[position:position] = new_clips
    if queue.current_index is None:
        # Start "playing" the first clip only when the queue was empty, so a GET
        # returns a sensible current clip. A queue that *stopped* (reached the
        # end under repeat=none) keeps current_index None — adding clips must not
        # silently restart playback.
        if was_empty:
            queue.current_index = 0
    elif position <= queue.current_index:
        queue.current_index += len(new_clips)
    queue.shuffle_history = [h + len(new_clips) if h >= position else h for h in queue.shuffle_history]
    queue.updated_at = utcnow()
    await queue.save()
    return queue


async def remove_clip(user_id: str, clip_id: str) -> PlaybackQueue:
    """Remove ``clip_id`` from the queue (404 if absent), adjusting current/history."""
    oid = coerce_object_id(clip_id)
    queue = await get_or_create_queue(user_id)
    if oid is None or oid not in queue.clips:
        raise _not_in_queue()

    removed = queue.clips.index(oid)
    queue.clips.pop(removed)

    if not queue.clips:
        queue.current_index = None
    elif queue.current_index is not None:
        if removed < queue.current_index:
            queue.current_index -= 1
        elif removed == queue.current_index and queue.current_index >= len(queue.clips):
            # Removed the current (last) clip: clamp to the new last clip.
            queue.current_index = len(queue.clips) - 1

    queue.shuffle_history = [h - 1 if h > removed else h for h in queue.shuffle_history if h != removed]
    queue.updated_at = utcnow()
    await queue.save()
    return queue


async def go_next(user_id: str) -> PlaybackQueue:
    """Advance to the next clip, honouring repeat and shuffle modes."""
    queue = await get_or_create_queue(user_id)
    if not queue.clips:
        return queue
    if queue.current_index is None:
        queue.current_index = 0
    elif queue.repeat_mode == RepeatMode.ONE:
        pass  # repeat-one loops the current clip
    elif queue.shuffle_enabled:
        played = set(queue.shuffle_history) | {queue.current_index}
        remaining = [i for i in range(len(queue.clips)) if i not in played]
        queue.shuffle_history.append(queue.current_index)
        if remaining:
            queue.current_index = random.choice(remaining)
        elif queue.repeat_mode == RepeatMode.ALL:
            queue.shuffle_history = []
            queue.current_index = random.choice(range(len(queue.clips)))
        else:
            queue.current_index = None
    else:
        if queue.current_index + 1 < len(queue.clips):
            queue.current_index += 1
        elif queue.repeat_mode == RepeatMode.ALL:
            queue.current_index = 0
        else:
            queue.current_index = None

    queue.updated_at = utcnow()
    await queue.save()
    return queue


async def go_previous(user_id: str) -> PlaybackQueue:
    """Go back to the previous clip, honouring repeat and shuffle modes."""
    queue = await get_or_create_queue(user_id)
    if not queue.clips:
        return queue
    if queue.repeat_mode == RepeatMode.ONE:
        pass  # repeat-one loops the current clip
    elif queue.shuffle_enabled:
        if queue.shuffle_history:
            queue.current_index = queue.shuffle_history.pop()
    elif queue.current_index is None:
        queue.current_index = len(queue.clips) - 1
    elif queue.current_index - 1 >= 0:
        queue.current_index -= 1
    elif queue.repeat_mode == RepeatMode.ALL:
        queue.current_index = len(queue.clips) - 1

    queue.updated_at = utcnow()
    await queue.save()
    return queue


async def reorder_clip(user_id: str, clip_id: str, new_position: int) -> PlaybackQueue:
    """Move ``clip_id`` to ``new_position`` (clamped), 404 if not in the queue."""
    oid = coerce_object_id(clip_id)
    queue = await get_or_create_queue(user_id)
    if oid is None or oid not in queue.clips:
        raise _not_in_queue()

    old = queue.clips.index(oid)
    new = max(0, min(new_position, len(queue.clips) - 1))
    if new != old:
        queue.clips.insert(new, queue.clips.pop(old))
        if queue.current_index is not None:
            queue.current_index = _shift_index(queue.current_index, old, new)
        queue.shuffle_history = [_shift_index(h, old, new) for h in queue.shuffle_history]

    queue.updated_at = utcnow()
    await queue.save()
    return queue


async def clear_queue(user_id: str) -> PlaybackQueue:
    """Empty the queue, preserving repeat/shuffle mode settings."""
    queue = await get_or_create_queue(user_id)
    queue.clips = []
    queue.current_index = None
    queue.shuffle_history = []
    queue.updated_at = utcnow()
    await queue.save()
    return queue


async def update_modes(
    user_id: str,
    repeat_mode: RepeatMode | None,
    shuffle_enabled: bool | None,
) -> PlaybackQueue:
    """Update repeat and/or shuffle mode; toggling shuffle resets its history."""
    queue = await get_or_create_queue(user_id)
    if repeat_mode is not None:
        queue.repeat_mode = repeat_mode
    if shuffle_enabled is not None:
        queue.shuffle_enabled = shuffle_enabled
        queue.shuffle_history = []
    queue.updated_at = utcnow()
    await queue.save()
    return queue
