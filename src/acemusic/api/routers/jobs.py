"""Job status endpoint (US-9.2), mounted under ``/api/v1/jobs``.

``GET /api/v1/jobs/{job_id}/status`` returns a job's current lifecycle state so a
client can poll while generation runs asynchronously. The route is owner-scoped:
a job that does not exist *or* belongs to another user yields 404, so the
endpoint never reveals the existence of another user's jobs.
"""

import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from acemusic.song_structure import SONG_STRUCTURE
from acemusic.storage import get_storage_backend

from ..auth.dependencies import CurrentUser, get_current_user
from ..models import Clip, Job, JobStatus
from ..services.common import coerce_object_id
from ..services.editing import EDIT_JOB_TYPES
from ..services.export import EXPORT_JOB_TYPES
from ..services.extraction import EXTRACTION_JOB_TYPES, MIDI_JOB_TYPE, resolve_midi_urls
from ..services.iterative import FULL_SONG_JOB_TYPE, ITERATIVE_JOB_TYPES, SAMPLE_JOB_TYPE
from .generation import GenerationRequest, estimate_seconds

logger = logging.getLogger(__name__)

# Editing jobs (crop/speed/remaster, US-10.1) are quick local CPU work, so a
# small flat estimate replaces the duration-scaled generation heuristic.
_EDIT_ESTIMATE_SECONDS = 5

# Extraction jobs (stems/MIDI, US-10.2) run heavy ML models (demucs / basic-pitch)
# on CPU, so they take far longer than an edit; a flat minute-ish estimate is a
# reasonable advisory floor without modelling per-clip duration.
_EXTRACTION_ESTIMATE_SECONDS = 60

# Iterative generation jobs (US-10.3) each run one ACE-Step task; the flat
# estimate mirrors the iterative router's create-response heuristic so status
# polling and the enqueue response agree (sample scales by num_clips).
_ITERATIVE_ESTIMATE_SECONDS = 45

# Router-level dependency gates every route behind a valid Bearer token (mirrors
# the generation router), so an unauthenticated request is rejected with 401.
router = APIRouter(prefix="/jobs", tags=["jobs"], dependencies=[Depends(get_current_user)])


class JobStatusResponse(BaseModel):
    """A job's current state. Result fields are populated by lifecycle phase.

    ``response_model_exclude_none`` drops the optional fields until they apply:
    ``clip_ids``/``audio_urls`` appear only when completed, ``error`` only when
    failed.
    """

    job_id: str
    status: JobStatus
    created_at: datetime
    estimated_time_seconds: int
    # Per-step progress for long multi-step jobs (US-10.4 full-song); only set
    # while the job is queued/processing, dropped once it completes or fails.
    progress: str | None = None
    clip_ids: list[str] | None = None
    audio_urls: list[str] | None = None
    # MIDI extraction jobs (US-10.2) produce files, not clips; their results
    # surface here as label -> download URL (resolved fresh, like ``audio_urls``).
    midi_download_urls: dict[str, str] | None = None
    error: str | None = None


def _estimate_for(job: Job) -> int:
    """Advisory estimate per job type.

    Editing jobs get a flat per-type constant — their ``input_params`` are an
    edit spec, not a :class:`GenerationRequest`, so the generation heuristic
    would (mis)report them as 0. Generation jobs reuse the generation router's
    heuristic so the status and create responses agree; a snapshot that no
    longer validates (e.g. a schema change) falls back to 0 rather than failing
    the status read.
    """
    if job.job_type in EDIT_JOB_TYPES or job.job_type in EXPORT_JOB_TYPES:
        # Export (US-10.5) is quick local transcode work, like an edit.
        return _EDIT_ESTIMATE_SECONDS
    if job.job_type in EXTRACTION_JOB_TYPES:
        return _EXTRACTION_ESTIMATE_SECONDS
    if job.job_type in ITERATIVE_JOB_TYPES:
        if job.job_type == SAMPLE_JOB_TYPE:
            return _ITERATIVE_ESTIMATE_SECONDS * int((job.input_params or {}).get("num_clips", 1))
        if job.job_type == FULL_SONG_JOB_TYPE:
            # One extend per section; scale by the planned section count so the
            # status estimate matches the enqueue response.
            structure = (job.input_params or {}).get("structure_plan") or SONG_STRUCTURE
            return _ITERATIVE_ESTIMATE_SECONDS * len(structure)
        return _ITERATIVE_ESTIMATE_SECONDS
    try:
        return estimate_seconds(GenerationRequest(**job.input_params))
    except Exception:
        return 0


async def _resolve_audio_urls(clip_ids: list[str]) -> list[str]:
    """Map a completed job's clip ids to retrievable audio URLs via storage."""
    if not clip_ids:
        return []
    storage = get_storage_backend()
    urls: list[str] = []
    for clip_id in clip_ids:
        clip = await Clip.get(clip_id)
        if clip is None:
            # The processor inserts clips atomically with the job result, so a
            # missing one signals a data inconsistency worth surfacing.
            logger.warning("Clip %s referenced by a completed job is missing", clip_id)
            continue
        # get_url may hit the network (S3 presign), so keep it off the event loop.
        urls.append(await asyncio.to_thread(storage.get_url, clip.file_path))
    return urls


@router.get("/{job_id}/status", response_model=JobStatusResponse, response_model_exclude_none=True)
async def get_job_status(
    job_id: str,
    current: CurrentUser = Depends(get_current_user),
) -> JobStatusResponse:
    """Return the current status of ``job_id`` for its owner (404 otherwise)."""
    oid = coerce_object_id(job_id)
    job = await Job.get(oid) if oid is not None else None
    if job is None or str(job.user_id) != current.user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")

    response = JobStatusResponse(
        job_id=str(job.id),
        status=job.status,
        created_at=job.created_at,
        estimated_time_seconds=_estimate_for(job),
    )
    if job.status in (JobStatus.QUEUED, JobStatus.PROCESSING):
        # Progress is in-flight state; a terminal job exposes its result/error instead.
        response.progress = job.progress
    if job.status == JobStatus.COMPLETED:
        if job.job_type == MIDI_JOB_TYPE:
            # MIDI jobs record ``midi_paths`` (label -> storage key), not clips.
            response.midi_download_urls = await resolve_midi_urls((job.result or {}).get("midi_paths", {}))
        else:
            clip_ids = list((job.result or {}).get("clip_ids", []))
            response.clip_ids = clip_ids
            response.audio_urls = await _resolve_audio_urls(clip_ids)
    elif job.status == JobStatus.FAILED:
        response.error = job.error
    return response
