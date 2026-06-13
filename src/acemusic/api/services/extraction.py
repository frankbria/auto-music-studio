"""Extraction service layer (US-10.2).

Persists queued stem-separation and MIDI-extraction jobs for the extraction
endpoints, mirroring :func:`acemusic.api.services.editing.create_edit_job`.
Kept transport-agnostic (plain exceptions, never ``HTTPException``) like the
other service modules.
"""

from beanie import PydanticObjectId

from ..models import Job, JobStatus
from ..tasks import dispatch_job

STEMS_JOB_TYPE = "stems"
MIDI_JOB_TYPE = "midi"

EXTRACTION_JOB_TYPES = (STEMS_JOB_TYPE, MIDI_JOB_TYPE)


async def create_extraction_job(
    *,
    user_id: PydanticObjectId,
    workspace_id: PydanticObjectId,
    job_type: str,
    clip_id: PydanticObjectId,
) -> Job:
    """Persist a queued extraction job and dispatch it.

    ``input_params`` carries only the source ``clip_id``; the worker re-reads
    everything else (audio bytes, BPM) from the clip document at run time.
    ``workspace_id`` is the source clip's workspace so derived stems land next
    to their parent. Returns the saved :class:`Job` (with its id).
    """
    if job_type not in EXTRACTION_JOB_TYPES:
        raise ValueError(f"Unknown extraction job type: {job_type!r}")
    job = Job(
        user_id=user_id,
        workspace_id=workspace_id,
        job_type=job_type,
        status=JobStatus.QUEUED,
        input_params={"clip_id": str(clip_id)},
    )
    await job.insert()
    try:
        await dispatch_job(str(job.id))
    except BaseException:
        # Don't leave the job behind: the processor polls for QUEUED documents,
        # so an orphan would still run even though the caller saw a failure.
        # BaseException (not Exception) on purpose: asyncio.CancelledError must
        # also clean up (mirrors create_edit_job).
        await job.delete()
        raise
    return job
