"""Iterative generation service layer (US-10.3).

Persists queued iterative-generation jobs (extend, cover, remix, repaint,
mashup, sample, add-vocal) for the iterative endpoints, mirroring
:func:`acemusic.api.services.editing.create_edit_job`. Kept transport-agnostic
(plain exceptions, never ``HTTPException``) like the other service modules.

Each mode wraps the corresponding CLI iterative command as an async ACE-Step (or
ElevenLabs) job; the worker handlers live in
:mod:`acemusic.api.tasks.iterative`.
"""

from beanie import PydanticObjectId

from ..models import Job
from .jobs import create_job

EXTEND_JOB_TYPE = "extend"
COVER_JOB_TYPE = "cover"
REMIX_JOB_TYPE = "remix"
REPAINT_JOB_TYPE = "repaint"
MASHUP_JOB_TYPE = "mashup"
SAMPLE_JOB_TYPE = "sample"
ADD_VOCAL_JOB_TYPE = "add_vocal"
# US-10.4: full-song assembly chains several extends into one long job.
FULL_SONG_JOB_TYPE = "full_song"

ITERATIVE_JOB_TYPES = (
    EXTEND_JOB_TYPE,
    COVER_JOB_TYPE,
    REMIX_JOB_TYPE,
    REPAINT_JOB_TYPE,
    MASHUP_JOB_TYPE,
    SAMPLE_JOB_TYPE,
    ADD_VOCAL_JOB_TYPE,
    FULL_SONG_JOB_TYPE,
)


async def create_iterative_job(
    *,
    user_id: PydanticObjectId,
    workspace_id: PydanticObjectId,
    job_type: str,
    params: dict,
) -> Job:
    """Persist a queued iterative-generation job and dispatch it.

    ``params`` holds the resolved request spec — the source ``clip_id`` (or
    ``clip_ids`` for mashup) plus the mode's parameters — so the worker re-reads
    nothing from the request. ``workspace_id`` is the (primary) source clip's
    workspace, so the derived clip lands next to its parent. Returns the saved
    :class:`Job` (with its id). Mirrors
    :func:`acemusic.api.services.editing.create_edit_job`.
    """
    return await create_job(
        user_id=user_id,
        workspace_id=workspace_id,
        job_type=job_type,
        params=params,
        valid_types=ITERATIVE_JOB_TYPES,
    )
