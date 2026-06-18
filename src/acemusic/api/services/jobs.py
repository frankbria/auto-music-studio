"""Shared job-creation factory for the service layer (US-0.1).

The per-domain service modules (editing, extraction, iterative, mastering,
generation) all persist a queued :class:`Job` and dispatch it through the same
``insert → dispatch → orphan-cleanup`` sequence. This factory owns that
sequence; each module keeps its own public ``create_*_job`` wrapper (and its
job-type constants) and delegates here. Kept transport-agnostic (plain
exceptions, never ``HTTPException``) like the other service modules.
"""

from typing import Any

from beanie import PydanticObjectId

from ..models import Job, JobStatus
from ..tasks import dispatch_job
from .routing import ComputeTarget


async def create_job(
    *,
    user_id: PydanticObjectId,
    workspace_id: PydanticObjectId,
    job_type: str,
    params: dict[str, Any],
    valid_types: tuple[str, ...] | None = None,
    compute_target: ComputeTarget | None = None,
) -> Job:
    """Persist a queued ``job_type`` job for ``user_id`` and dispatch it.

    When ``valid_types`` is given, ``job_type`` must be one of them (raises
    ``ValueError`` otherwise); pass ``None`` for domains with a single fixed
    type. ``compute_target`` (US-11.1) is recorded as its string value for
    routing/audit. Returns the saved :class:`Job` (with its id).

    On a failed dispatch the orphaned job is deleted before re-raising: the
    processor polls for QUEUED documents, so an orphan would still run even
    though the caller saw a failure. ``BaseException`` (not ``Exception``) on
    purpose — ``asyncio.CancelledError`` must also clean up.
    """
    if valid_types is not None and job_type not in valid_types:
        raise ValueError(f"Unknown job type {job_type!r}; expected one of {valid_types}")
    job = Job(
        user_id=user_id,
        workspace_id=workspace_id,
        job_type=job_type,
        compute_target=compute_target.value if compute_target is not None else None,
        status=JobStatus.QUEUED,
        input_params=params,
    )
    await job.insert()
    try:
        await dispatch_job(str(job.id))
    except BaseException:
        await job.delete()
        raise
    return job
