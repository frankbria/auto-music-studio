"""Generation service layer (US-9.1).

Encapsulates the work behind ``POST /api/v1/generate``: resolving the user's
default workspace and persisting a queued :class:`Job`. Kept transport-agnostic
(it raises plain exceptions, never ``HTTPException``) like the other service
modules, so the router stays free of persistence concerns.
"""

from beanie import PydanticObjectId
from beanie.operators import Eq
from pymongo.errors import DuplicateKeyError

from ..models import Job, JobStatus, Workspace
from ..tasks import dispatch_job

GENERATE_JOB_TYPE = "generate"
DEFAULT_WORKSPACE_NAME = "My Workspace"


async def _find_default_workspace(user_id: PydanticObjectId) -> Workspace | None:
    return await Workspace.find_one(Eq(Workspace.user_id, user_id), Eq(Workspace.is_default, True))


async def get_or_create_default_workspace(user_id: PydanticObjectId) -> Workspace:
    """Return the user's default workspace, creating it on first use.

    A generation job must be attached to a workspace, but a freshly registered
    account has none yet — workspaces are created lazily here rather than at
    registration. The default workspace is created once and reused thereafter.

    The create path is race-safe: the unique partial index on
    ``(user_id, is_default=True)`` (see :class:`Workspace`) rejects a concurrent
    second insert with ``DuplicateKeyError``, which we resolve by re-reading the
    winner (mirroring ``users.get_or_create_user``).
    """
    workspace = await _find_default_workspace(user_id)
    if workspace is not None:
        return workspace
    workspace = Workspace(name=DEFAULT_WORKSPACE_NAME, user_id=user_id, is_default=True)
    try:
        await workspace.insert()
    except DuplicateKeyError:
        existing = await _find_default_workspace(user_id)
        if existing is None:
            raise
        return existing
    return workspace


async def create_generation_job(*, user_id: PydanticObjectId, params: dict) -> Job:
    """Persist a queued generation job for ``user_id`` and dispatch it.

    ``params`` is the validated request snapshot, stored verbatim in
    ``input_params`` so the worker (US-9.2) has the full creative spec regardless
    of later schema changes. Returns the saved :class:`Job` (with its id).
    """
    workspace = await get_or_create_default_workspace(user_id)
    job = Job(
        user_id=user_id,
        workspace_id=workspace.id,
        job_type=GENERATE_JOB_TYPE,
        status=JobStatus.QUEUED,
        input_params=params,
    )
    await job.insert()
    await dispatch_job(str(job.id))
    return job
