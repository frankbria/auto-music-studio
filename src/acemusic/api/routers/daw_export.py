"""DAW-export endpoints (US-14.1), mounted under ``/api/v1/clips``.

* ``POST /clips/{id}/export/daw`` → enqueue a DAW bundle build (202, job id)
* ``GET  /clips/{id}/export/daw`` → download the assembled ZIP (404 until built)

The POST mirrors the editing/extraction async pattern: verify ownership, persist
a queued :class:`~acemusic.api.models.job.Job`, return 202. The build (stems +
MIDI resolution and ZIP assembly) runs in the background worker, which uploads
the bundle to a predictable per-clip key. The GET serves that object directly —
no job id needed — using the same owner-or-public visibility rule as the audio
download. Like editing/extraction, DAW export deducts no credits.
"""

import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from acemusic.daw_export import project_slug
from acemusic.storage import get_storage_backend

from ..auth.dependencies import CurrentUser, get_current_user, require_existing_user
from ..models import Clip
from ..services import clips as clip_service, daw_export as daw_export_service

logger = logging.getLogger(__name__)

# Router-level dependency gates every route behind a valid Bearer token
# (mirrors the clips/editing routers), so unauthenticated requests get 401.
router = APIRouter(prefix="/clips", tags=["daw-export"], dependencies=[Depends(get_current_user)])


class DawExportJobResponse(BaseModel):
    """The accepted-job acknowledgement returned with HTTP 202."""

    job_id: str
    status: Literal["queued"] = "queued"


def _export_path(clip: Clip) -> str:
    """Predictable per-clip storage key the worker writes and the GET serves."""
    return daw_export_service.export_storage_path(clip.user_id, clip.workspace_id, clip.id)


@router.post("/{clip_id}/export/daw", response_model=DawExportJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_daw_export(
    clip_id: str,
    current: CurrentUser = Depends(require_existing_user),
) -> DawExportJobResponse:
    """Enqueue a DAW bundle build for ``clip_id``; poll the job, then GET the ZIP."""
    clip = await clip_service.get_owned_clip(clip_id, current.user_id)
    # The bundle's full_mix (and any on-demand stem/MIDI extraction) round-trips
    # through wav; the server has no ffmpeg to transcode a compressed source, so
    # gate non-wav here with a clear 422 instead of a doomed queued job (mirrors
    # the editing and stems endpoints).
    fmt = clip_service.native_format(clip)
    if fmt != "wav":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"unsupported format {fmt!r} for DAW export; currently only wav is supported.",
        )
    job = await daw_export_service.create_daw_export_job(
        user_id=clip.user_id,
        workspace_id=clip.workspace_id,
        clip_id=clip.id,
    )
    return DawExportJobResponse(job_id=str(job.id))


@router.get("/{clip_id}/export/daw")
async def download_daw_export(
    clip_id: str,
    current: CurrentUser = Depends(get_current_user),
) -> Response:
    """Download the assembled DAW bundle ZIP; 404 until the export has been built."""
    clip = await clip_service.get_clip_for_audio_access(clip_id, current.user_id)
    storage = get_storage_backend()
    try:
        data = await asyncio.to_thread(storage.download, _export_path(clip))
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="DAW export not found. Trigger it with POST /clips/{id}/export/daw first.",
        )
    filename = f"{project_slug(clip)}_Export.zip"
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
