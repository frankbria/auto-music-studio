"""Generation service layer (US-9.1).

Encapsulates the work behind ``POST /api/v1/generate``: resolving the user's
default workspace and persisting a queued :class:`Job`. Kept transport-agnostic
(it raises plain exceptions, never ``HTTPException``) like the other service
modules, so the router stays free of persistence concerns.
"""

from beanie import PydanticObjectId

from ..models import Job, JobStatus
from ..tasks import dispatch_job

# get_or_create_default_workspace moved to the workspaces service (US-9.4); it is
# re-exported here because generation still uses it as a lazy fallback for
# accounts predating the registration-time bootstrap, and existing callers/tests
# import it from this module.
from .workspaces import DEFAULT_WORKSPACE_NAME, get_or_create_default_workspace  # noqa: F401

GENERATE_JOB_TYPE = "generate"


async def create_generation_job(*, user_id: PydanticObjectId, params: dict, compute_target: str | None = None) -> Job:
    """Persist a queued generation job for ``user_id`` and dispatch it.

    ``params`` is the validated request snapshot, stored verbatim in
    ``input_params`` so the worker (US-9.2) has the full creative spec regardless
    of later schema changes. ``compute_target`` is the resolved routing target
    (US-11.1: ``"local"``/``"remote"``), recorded on the job for auditability and
    status reporting. Returns the saved :class:`Job` (with its id).
    """
    workspace = await get_or_create_default_workspace(user_id)
    job = Job(
        user_id=user_id,
        workspace_id=workspace.id,
        job_type=GENERATE_JOB_TYPE,
        compute_target=compute_target,
        status=JobStatus.QUEUED,
        input_params=params,
    )
    await job.insert()
    try:
        await dispatch_job(str(job.id))
    except BaseException:
        # Don't leave the job behind: the processor polls for QUEUED documents,
        # so an orphan would still run even though the caller saw a failure
        # (and, for generation, refunded the credits — US-9.6). BaseException
        # (not Exception) on purpose: asyncio.CancelledError must also clean up.
        await job.delete()
        raise
    return job
