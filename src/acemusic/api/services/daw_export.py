"""DAW-export service layer (US-14.1).

Persists the queued ``daw_export`` job for the DAW-export endpoint, mirroring
the other ``create_*_job`` wrappers (editing, extraction). Kept
transport-agnostic (plain exceptions, never ``HTTPException``).
"""

from beanie import PydanticObjectId

from ..models import Job
from .jobs import create_job

DAW_EXPORT_JOB_TYPE = "daw_export"


async def create_daw_export_job(
    *,
    user_id: PydanticObjectId,
    workspace_id: PydanticObjectId,
    clip_id: PydanticObjectId,
) -> Job:
    """Persist a queued DAW-export job for ``clip_id`` and dispatch it.

    ``params`` carries only the source ``clip_id``; the worker resolves (or
    extracts) stems and MIDI and assembles the bundle. Returns the saved
    :class:`Job` (with its id).
    """
    return await create_job(
        user_id=user_id,
        workspace_id=workspace_id,
        job_type=DAW_EXPORT_JOB_TYPE,
        params={"clip_id": str(clip_id)},
        valid_types=(DAW_EXPORT_JOB_TYPE,),
    )
