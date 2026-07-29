"""Video-generation service layer (US-22.1).

Persists queued video-rendering jobs for the videos endpoint, mirroring
:func:`acemusic.api.services.mastering.create_mastering_job`. Kept
transport-agnostic (plain exceptions, never ``HTTPException``) like the other
service modules.
"""

from beanie import PydanticObjectId

from ..models import Job, Video
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


# ---------------------------------------------------------------------------
# US-22.3 delivery: the rendered ``Video`` documents (playback/download/publish)
# ---------------------------------------------------------------------------


async def get_video_by_id(video_id: str) -> Video | None:
    """Return the rendered video by id, or ``None`` for a missing/malformed id.

    Ownership and publish-visibility are the caller's (the router's) to enforce —
    this is the raw lookup shared by the owner-scoped and public delivery paths.
    """
    oid = coerce_object_id(video_id)
    if oid is None:
        return None
    return await Video.get(oid)


async def get_owned_video(video_id: str, user_id: str) -> Video | None:
    """Return the video only if ``user_id`` owns it, else ``None``.

    A missing id or another user's video are both indistinguishable from "no
    such video" — the owner-scoped counterpart of :func:`get_video_job`.
    """
    video = await get_video_by_id(video_id)
    if video is None or str(video.user_id) != user_id:
        return None
    return video


async def publish_video(video_id: str, user_id: str) -> Video | None:
    """Mark the owner's video published (visible on the song page); idempotent.

    Returns the updated video, or ``None`` if it does not exist or is not owned
    by ``user_id`` (the router maps that to 404).
    """
    video = await get_owned_video(video_id, user_id)
    if video is None:
        return None
    if not video.published:
        video.published = True
        await video.save()
    return video


async def get_published_video_for_clip(clip_id: str) -> Video | None:
    """Return the most recently created *published* video for a clip, if any.

    Backs the song detail page's "Music video" section. Visibility of the clip
    itself is enforced by the caller before this runs.
    """
    oid = coerce_object_id(clip_id)
    if oid is None:
        return None
    return (
        await Video.find(Video.clip_id == oid, Video.published == True)  # noqa: E712 - Beanie needs == for the query
        .sort(-Video.created_at)
        .first_or_none()
    )
