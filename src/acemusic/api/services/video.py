"""Video-generation service layer (US-22.1).

Persists queued video-rendering jobs for the videos endpoint, mirroring
:func:`acemusic.api.services.mastering.create_mastering_job`. Kept
transport-agnostic (plain exceptions, never ``HTTPException``) like the other
service modules.
"""

from beanie import PydanticObjectId

from ..models import Job
from .common import coerce_object_id
from .jobs import create_job

VIDEO_JOB_TYPE = "video"


async def create_video_job(
    *,
    user_id: PydanticObjectId,
    workspace_id: PydanticObjectId,
    params: dict,
) -> Job:
    """Persist a queued video-rendering job and dispatch it.

    ``params`` holds the resolved rendering spec (clip_id, prompt, style/aspect/
    resolution options) so the worker never re-derives anything from the request.
    ``workspace_id`` is the source clip's workspace — the video lands next to its
    song. Returns the saved :class:`Job` (with its id).
    """
    return await create_job(
        user_id=user_id,
        workspace_id=workspace_id,
        job_type=VIDEO_JOB_TYPE,
        params=params,
    )


async def get_video_job(job_id: str, user_id: str) -> Job | None:
    """Return the owner's video job, or ``None`` for unknown/unowned/wrong-type.

    Owner- and type-scoped like :func:`mastering.get_mastering_job`: a missing
    id, another user's job, or a non-video job are all indistinguishable from
    "no such job".
    """
    oid = coerce_object_id(job_id)
    if oid is None:
        return None
    job = await Job.get(oid)
    if job is None or str(job.user_id) != user_id or job.job_type != VIDEO_JOB_TYPE:
        return None
    return job
