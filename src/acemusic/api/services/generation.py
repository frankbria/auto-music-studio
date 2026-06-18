"""Generation service layer (US-9.1).

Encapsulates the work behind ``POST /api/v1/generate``: resolving the user's
default workspace and persisting a queued :class:`Job`. Kept transport-agnostic
(it raises plain exceptions, never ``HTTPException``) like the other service
modules, so the router stays free of persistence concerns.
"""

from beanie import PydanticObjectId

from ..models import Job
from .jobs import create_job
from .routing import ComputeTarget

# get_or_create_default_workspace moved to the workspaces service (US-9.4); it is
# re-exported here because generation still uses it as a lazy fallback for
# accounts predating the registration-time bootstrap, and existing callers/tests
# import it from this module.
from .workspaces import DEFAULT_WORKSPACE_NAME, get_or_create_default_workspace  # noqa: F401

GENERATE_JOB_TYPE = "generate"


async def create_generation_job(
    *, user_id: PydanticObjectId, params: dict, compute_target: ComputeTarget | None = None
) -> Job:
    """Persist a queued generation job for ``user_id`` and dispatch it.

    ``params`` is the validated request snapshot, stored verbatim in
    ``input_params`` so the worker (US-9.2) has the full creative spec regardless
    of later schema changes. ``compute_target`` is the resolved routing target
    (US-11.1), recorded on the job (as its string value) for auditability and
    status reporting. Returns the saved :class:`Job` (with its id).
    """
    workspace = await get_or_create_default_workspace(user_id)
    return await create_job(
        user_id=user_id,
        workspace_id=workspace.id,
        job_type=GENERATE_JOB_TYPE,
        params=params,
        compute_target=compute_target,
    )
