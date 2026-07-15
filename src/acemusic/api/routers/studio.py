"""Studio export endpoints (US-19.6), mounted under ``/api/v1/studio``.

* ``POST /studio/mixdown``        → enqueue a mixed-audio render (202, job id)
* ``POST /studio/export/daw``     → enqueue a per-track DAW bundle build (202)
* ``GET  /studio/export/daw/{id}`` → download the assembled ZIP (404 until built)

The Studio has no backend arrangement persistence, so each POST body carries the
whole arrangement; the router validates workspace ownership and every referenced
clip's ownership up front (404 before any job is created), then enqueues an async
job. Mixdown status/result surface through the generic ``GET /jobs/{id}/status``
(the rendered clip id lands in ``result["clip_ids"]``); the DAW ZIP is served by
the GET here once its job completes, mirroring the DAW-export router's download
semantics. Both operations deduct no credits.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Literal

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from acemusic.storage import get_storage_backend
from acemusic.utils import make_slug

from ..auth.dependencies import CurrentUser, get_current_user, require_existing_user
from ..models import Job, JobStatus
from ..services import clips as clip_service, studio as studio_service, workspaces as workspace_service
from ..services.studio import (
    STUDIO_DAW_EXPORT_JOB_TYPE,
    StudioDawExportRequest,
    StudioMixdownRequest,
    clip_ids_in,
    studio_export_storage_path,
)

logger = logging.getLogger(__name__)

# Router-level dependency gates every route behind a valid Bearer token (mirrors
# the daw-export/mastering routers), so unauthenticated requests get 401.
router = APIRouter(prefix="/studio", tags=["studio-export"], dependencies=[Depends(get_current_user)])


class StudioJobResponse(BaseModel):
    """The accepted-job acknowledgement returned with HTTP 202."""

    job_id: str
    status: Literal["queued"] = "queued"


async def _validated_workspace_and_clips(workspace_id: str, tracks, user_id: str) -> PydanticObjectId:
    """Assert the caller owns the workspace and every referenced clip; return the workspace oid.

    A 404 here (unknown/unowned workspace or clip) happens before any job is
    created, so a rejected request never leaves a queued job behind.
    """
    workspace = await workspace_service.get_workspace(workspace_id, user_id)
    for clip_id in clip_ids_in(tracks):
        await clip_service.get_owned_clip(clip_id, user_id)
    return workspace.id


@router.post("/mixdown", response_model=StudioJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_mixdown(
    request: StudioMixdownRequest,
    current: CurrentUser = Depends(require_existing_user),
) -> StudioJobResponse:
    """Validate ownership and enqueue a studio mixdown; poll ``GET /jobs/{id}/status``."""
    workspace_oid = await _validated_workspace_and_clips(request.workspace_id, request.tracks, current.user_id)
    job = await studio_service.create_mixdown_job(
        user_id=PydanticObjectId(current.user_id),
        workspace_id=workspace_oid,
        params=request.model_dump(),
    )
    return StudioJobResponse(job_id=str(job.id))


@router.post("/export/daw", response_model=StudioJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_daw_export(
    request: StudioDawExportRequest,
    current: CurrentUser = Depends(require_existing_user),
) -> StudioJobResponse:
    """Validate ownership and enqueue a per-track DAW bundle build; poll, then GET the ZIP."""
    workspace_oid = await _validated_workspace_and_clips(request.workspace_id, request.tracks, current.user_id)
    job = await studio_service.create_daw_export_job(
        user_id=PydanticObjectId(current.user_id),
        workspace_id=workspace_oid,
        params=request.model_dump(),
    )
    return StudioJobResponse(job_id=str(job.id))


async def _owned_daw_job(job_id: str, user_id: str) -> Job:
    """Resolve the caller's studio DAW-export job, or 404 (unknown/unowned/wrong-type)."""
    try:
        oid = PydanticObjectId(job_id)
    except Exception:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Studio DAW export job not found.")
    job = await Job.get(oid)
    if job is None or str(job.user_id) != user_id or job.job_type != STUDIO_DAW_EXPORT_JOB_TYPE:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Studio DAW export job not found.")
    return job


@router.get("/export/daw/{job_id}")
async def download_daw_export(
    job_id: str,
    current: CurrentUser = Depends(require_existing_user),
) -> Response:
    """Download the assembled DAW bundle ZIP; 409 until the job completes, 404 if absent."""
    job = await _owned_daw_job(job_id, current.user_id)
    if job.status != JobStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Studio DAW export is not ready (status: {job.status.value}).",
        )
    storage = get_storage_backend()
    export_path = studio_export_storage_path(job.user_id, job.workspace_id, job.id)
    try:
        data = await asyncio.to_thread(storage.download, export_path)
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Studio DAW export not found.")
    project_name = (job.input_params or {}).get("project_name") or "studio-export"
    filename = f"{make_slug(project_name) or 'studio-export'}_Export.zip"
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
