"""DAW-export service layer (US-14.1).

Persists the queued ``daw_export`` job for the DAW-export endpoint, mirroring
the other ``create_*_job`` wrappers (editing, extraction). Kept
transport-agnostic (plain exceptions, never ``HTTPException``).
"""

from beanie import PydanticObjectId

from ..models import Job
from .jobs import create_job

DAW_EXPORT_JOB_TYPE = "daw_export"


def export_storage_path(user_id, workspace_id, clip_id) -> str:
    """Canonical storage key for a clip's DAW-export ZIP.

    The single source of truth shared by the worker (which writes it), the GET
    endpoint (which serves it), and clip deletion (which removes it) — so the
    three can never drift and silently orphan a bundle.
    """
    return f"{user_id}/{workspace_id}/exports/{clip_id}_daw.zip"


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
