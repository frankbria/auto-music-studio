"""Generation service layer (US-9.1).

Encapsulates the work behind ``POST /api/v1/generate``: resolving the user's
default workspace and persisting a queued :class:`Job`. Kept transport-agnostic
(it raises plain exceptions, never ``HTTPException``) like the other service
modules, so the router stays free of persistence concerns.
"""

from beanie import PydanticObjectId
from beanie.operators import Eq

from ..models import Job, JobStatus, Workspace
from ..tasks import dispatch_job

GENERATE_JOB_TYPE = "generate"
DEFAULT_WORKSPACE_NAME = "My Workspace"


async def get_or_create_default_workspace(user_id: PydanticObjectId) -> Workspace:
    """Return the user's default workspace, creating it on first use.

    A generation job must be attached to a workspace, but a freshly registered
    account has none yet — workspaces are created lazily here rather than at
    registration. The default workspace is created once and reused thereafter.
    """
    workspace = await Workspace.find_one(Eq(Workspace.user_id, user_id), Eq(Workspace.is_default, True))
    if workspace is not None:
        return workspace
    workspace = Workspace(name=DEFAULT_WORKSPACE_NAME, user_id=user_id, is_default=True)
    await workspace.insert()
    return workspace


async def create_generation_job(*, user_id: str, params: dict) -> Job:
    """Persist a queued generation job for ``user_id`` and dispatch it.

    ``params`` is the validated request snapshot, stored verbatim in
    ``input_params`` so the worker (US-9.2) has the full creative spec regardless
    of later schema changes. Returns the saved :class:`Job` (with its id).
    """
    user_oid = PydanticObjectId(user_id)
    workspace = await get_or_create_default_workspace(user_oid)
    job = Job(
        user_id=user_oid,
        workspace_id=workspace.id,
        job_type=GENERATE_JOB_TYPE,
        status=JobStatus.QUEUED,
        input_params=params,
    )
    await job.insert()
    await dispatch_job(str(job.id))
    return job
