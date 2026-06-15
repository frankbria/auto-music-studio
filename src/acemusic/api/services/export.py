"""Export service layer (US-10.5).

Persists queued audio-export jobs for batch export, mirroring
:func:`acemusic.api.services.extraction.create_extraction_job`. Kept
transport-agnostic (plain exceptions, never ``HTTPException``) like the other
service modules. ``input_params`` carries the source ``clip_id`` and the target
``format``; the worker re-reads the audio bytes from the clip at run time.
"""

from beanie import PydanticObjectId

from ..models import Job, JobStatus
from ..tasks import dispatch_job

EXPORT_JOB_TYPE = "export"

EXPORT_JOB_TYPES = (EXPORT_JOB_TYPE,)


async def create_export_job(
    *,
    user_id: PydanticObjectId,
    workspace_id: PydanticObjectId,
    clip_id: PydanticObjectId,
    format: str,
) -> Job:
    """Persist a queued export job and dispatch it.

    ``workspace_id`` is the source clip's workspace so the exported file lands
    next to its source. Returns the saved :class:`Job` (with its id).
    """
    job = Job(
        user_id=user_id,
        workspace_id=workspace_id,
        job_type=EXPORT_JOB_TYPE,
        status=JobStatus.QUEUED,
        input_params={"clip_id": str(clip_id), "format": format},
    )
    await job.insert()
    try:
        await dispatch_job(str(job.id))
    except BaseException:
        # Don't leave the job behind: the processor polls for QUEUED documents,
        # so an orphan would still run even though the caller saw a failure.
        # BaseException (not Exception) on purpose: asyncio.CancelledError must
        # also clean up (mirrors create_extraction_job).
        await job.delete()
        raise
    return job
