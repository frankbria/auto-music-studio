"""Shared task-layer helpers for the job handlers (US-0.2).

Every job-type module (editing, extraction, mastering, export, iterative) runs
the same clip lifecycle: resolve the source clip, download its audio, store a
derived clip with rollback-on-failure. These helpers are that lifecycle, factored
out of the per-module copies so a new job type reuses them instead of cloning.

:class:`JobProcessingError` is the single failure type every handler raises; the
:class:`~acemusic.api.tasks.processor.JobProcessor` records its message as the
job's failure (it lived in ``processor`` before US-0.2 and is re-exported there).
"""

from __future__ import annotations

import asyncio
import logging

from beanie import PydanticObjectId

from acemusic.storage import StorageBackend

from ..models import Clip, Job

logger = logging.getLogger(__name__)


class JobProcessingError(Exception):
    """A job could not be processed (missing source, audio/ML/service failure)."""


async def load_clip(clip_id: object) -> Clip:
    """Resolve a source clip by id, or fail the job with a clear error.

    The clip may legitimately vanish between enqueue and processing (the owner
    can DELETE it while the job is queued), so a miss is a job failure, not a
    crash.
    """
    try:
        oid = PydanticObjectId(clip_id)
    except Exception as exc:
        raise JobProcessingError(f"Job has an invalid source clip id: {clip_id!r}") from exc
    clip = await Clip.get(oid)
    if clip is None:
        raise JobProcessingError(f"Source clip {clip_id} no longer exists")
    return clip


async def load_source_clip(job: Job) -> Clip:
    """Resolve the clip referenced by ``job.input_params['clip_id']``."""
    return await load_clip((job.input_params or {}).get("clip_id"))


async def download_clip(storage: StorageBackend, clip: Clip) -> bytes:
    """Download a clip's audio bytes, failing the job if the object is missing."""
    try:
        return await asyncio.to_thread(storage.download, clip.file_path)
    except FileNotFoundError as exc:
        raise JobProcessingError(f"Source clip {clip.id} audio object {clip.file_path!r} is missing") from exc


async def store_clip(storage: StorageBackend, clip: Clip, data: bytes) -> Clip:
    """Upload ``data`` to ``clip.file_path`` and insert ``clip``.

    Rolls the just-uploaded object back if the insert fails, so a job that ends up
    ``failed`` never leaves an orphaned storage object behind.
    """
    await asyncio.to_thread(storage.upload, clip.file_path, data)
    try:
        await clip.insert()
    except BaseException:
        # BaseException (not Exception): a shutdown CancelledError must also clean
        # up the just-uploaded object, else a requeued retry leaves it orphaned.
        try:
            await asyncio.to_thread(storage.delete, clip.file_path)
        except Exception:  # pragma: no cover - cleanup is best-effort
            logger.exception("Failed to delete orphaned storage object %s during rollback", clip.file_path)
        raise
    return clip


async def rollback_clips(storage: StorageBackend, clip_ids: list[str]) -> None:
    """Best-effort removal of child clips (docs + audio objects) already stored.

    Used by multi-output modes so a failure partway through the batch does not
    leave earlier children behind for a job that ends up ``failed``.
    """
    for clip_id in clip_ids:
        clip = await Clip.get(PydanticObjectId(clip_id))
        if clip is None:  # pragma: no cover - already gone
            continue
        try:
            await asyncio.to_thread(storage.delete, clip.file_path)
        except Exception:  # pragma: no cover - cleanup is best-effort
            logger.exception("Failed to delete orphaned storage object %s during rollback", clip.file_path)
        try:
            await clip.delete()
        except Exception:  # pragma: no cover - cleanup is best-effort
            # Best-effort: a delete error here must not mask the original job failure
            # (callers re-raise that after rollback returns).
            logger.exception("Failed to delete orphaned clip doc %s during rollback", clip_id)
