"""Extraction service layer (US-10.2).

Persists queued stem-separation and MIDI-extraction jobs for the extraction
endpoints, mirroring :func:`acemusic.api.services.editing.create_edit_job`.
Kept transport-agnostic (plain exceptions, never ``HTTPException``) like the
other service modules.
"""

import asyncio

from beanie import PydanticObjectId

from acemusic.storage import get_storage_backend

from ..models import Job, JobStatus
from .jobs import create_job

STEMS_JOB_TYPE = "stems"
MIDI_JOB_TYPE = "midi"

EXTRACTION_JOB_TYPES = (STEMS_JOB_TYPE, MIDI_JOB_TYPE)

# A job is still "in flight" (a worker may pick it up or already has) in these
# states; a second request for the same clip rides it rather than competing.
_ACTIVE_STATUSES = (JobStatus.QUEUED.value, JobStatus.PROCESSING.value)


async def resolve_midi_urls(midi_paths: dict[str, str]) -> dict[str, str]:
    """Resolve stored MIDI keys (label -> storage key) to retrievable URLs.

    URLs are generated fresh per call (S3 presigned URLs expire) and the raw
    keys are never exposed, mirroring how clip audio URLs are served. Shared by
    the MIDI retrieval endpoint and the job-status endpoint.
    """
    storage = get_storage_backend()
    urls: dict[str, str] = {}
    for label, key in midi_paths.items():
        # get_url may hit the network (S3 presign), so keep it off the event loop.
        urls[label] = await asyncio.to_thread(storage.get_url, key)
    return urls


async def _find_active_job(job_type: str, clip_id: PydanticObjectId) -> Job | None:
    """An already-queued/processing job of this type for this clip, if any."""
    return await Job.find_one(
        {
            "job_type": job_type,
            "status": {"$in": list(_ACTIVE_STATUSES)},
            "input_params.clip_id": str(clip_id),
        }
    )


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

    Extraction is idempotent per clip: if a job of the same type for this clip is
    already queued or processing, that job is returned instead of enqueuing a
    competitor — two concurrent workers would otherwise race (the second's
    stale-stem cleanup could delete the first's just-stored results).
    """
    if job_type not in EXTRACTION_JOB_TYPES:
        raise ValueError(f"Unknown extraction job type: {job_type!r}")
    active = await _find_active_job(job_type, clip_id)
    if active is not None:
        return active
    return await create_job(
        user_id=user_id,
        workspace_id=workspace_id,
        job_type=job_type,
        params={"clip_id": str(clip_id)},
    )
