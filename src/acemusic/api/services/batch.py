"""Batch coordination service (US-10.5).

Fans a batch request out into one sub-job per clip and records the mapping in a
:class:`~acemusic.api.models.batch_job.BatchJob`. Each clip is resolved and
validated independently: an unknown/not-owned clip, or a non-wav source, becomes
a *failed entry* (``job_id=None`` with a reason) rather than aborting the whole
request — so one bad clip never halts the batch (partial success). Valid clips
get a real sub-:class:`~acemusic.api.models.job.Job` (an ordinary ``stems`` or
``export`` job that the existing :class:`JobProcessor` handles unchanged).

Kept transport-agnostic (plain exceptions, never ``HTTPException``) like the
other service modules: ownership is checked via the non-raising
:func:`acemusic.api.services.clips.find_owned_clip`.
"""

from beanie import PydanticObjectId

from ..models import BatchClipEntry, BatchJob
from . import clips as clip_service
from .clips import native_format
from .export import create_export_job
from .extraction import STEMS_JOB_TYPE, create_extraction_job

BATCH_STEMS_OPERATION = "stems"
BATCH_EXPORT_OPERATION = "export"

BATCH_OPERATIONS = (BATCH_STEMS_OPERATION, BATCH_EXPORT_OPERATION)


async def create_batch(
    *,
    user_id: str,
    operation: str,
    clip_ids: list[str],
    format: str | None = None,
) -> BatchJob:
    """Create one sub-job per clip and persist the batch mapping.

    ``operation`` is ``"stems"`` or ``"export"``; ``format`` is required for
    export and ignored for stems. Returns the saved :class:`BatchJob`.
    """
    if operation not in BATCH_OPERATIONS:
        raise ValueError(f"Unknown batch operation: {operation!r}")
    if operation == BATCH_EXPORT_OPERATION and format is None:
        raise ValueError("Export batches require a format.")

    entries: list[BatchClipEntry] = []
    for clip_id in clip_ids:
        clip = await clip_service.find_owned_clip(clip_id, user_id)
        if clip is None:
            entries.append(BatchClipEntry(clip_id=clip_id, error="Clip not found."))
            continue
        # Stems extraction (torchaudio / basic-pitch) needs a wav source; export
        # transcodes through ffmpeg, which reads any supported format, so the
        # wav-only gate applies to stems only (matches the single-clip endpoints).
        src_fmt = native_format(clip)
        if operation == BATCH_STEMS_OPERATION and src_fmt != "wav":
            entries.append(
                BatchClipEntry(
                    clip_id=clip_id,
                    error=f"unsupported format {src_fmt!r}; only wav is supported.",
                )
            )
            continue
        if operation == BATCH_STEMS_OPERATION:
            job = await create_extraction_job(
                user_id=clip.user_id,
                workspace_id=clip.workspace_id,
                job_type=STEMS_JOB_TYPE,
                clip_id=clip.id,
            )
        else:
            job = await create_export_job(
                user_id=clip.user_id,
                workspace_id=clip.workspace_id,
                clip_id=clip.id,
                format=format,
            )
        entries.append(BatchClipEntry(clip_id=clip_id, job_id=str(job.id)))

    batch = BatchJob(
        user_id=PydanticObjectId(user_id),
        operation=operation,
        format=format,
        entries=entries,
    )
    await batch.insert()
    return batch
