"""Editing service layer (US-10.1).

Persists queued editing jobs (crop, speed, remaster) for the audio editing
endpoints, mirroring :func:`acemusic.api.services.generation.create_generation_job`.
Kept transport-agnostic (plain exceptions, never ``HTTPException``) like the
other service modules.
"""

from beanie import PydanticObjectId

from ..models import Job
from .jobs import create_job

CROP_JOB_TYPE = "crop"
SPEED_JOB_TYPE = "speed"
REMASTER_JOB_TYPE = "remaster"

EDIT_JOB_TYPES = (CROP_JOB_TYPE, SPEED_JOB_TYPE, REMASTER_JOB_TYPE)


async def create_edit_job(
    *,
    user_id: PydanticObjectId,
    workspace_id: PydanticObjectId,
    job_type: str,
    params: dict,
) -> Job:
    """Persist a queued editing job and dispatch it.

    ``params`` holds the *resolved* edit spec (millisecond bounds, final
    multiplier, …) plus the source ``clip_id``, so the worker (Step 3) never
    re-derives anything from the request strings. ``workspace_id`` is the source
    clip's workspace — the derived clip lands next to its parent. Returns the
    saved :class:`Job` (with its id).
    """
    return await create_job(
        user_id=user_id,
        workspace_id=workspace_id,
        job_type=job_type,
        params=params,
        valid_types=EDIT_JOB_TYPES,
    )
