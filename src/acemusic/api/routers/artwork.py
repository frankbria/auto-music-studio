"""Cover-art endpoints (US-13.1), mounted under ``/api/v1/clips``.

* ``POST /clips/{id}/artwork/generate`` → enqueue generation of 4 options (202)
* ``POST /clips/{id}/artwork``          → select a generated option as the cover
* ``PUT  /clips/{id}/artwork/upload``   → upload custom artwork (JPG/PNG, >=3000²)
* ``GET  /clips/{id}/artwork``          → stream the selected/uploaded cover art

Generation is async (returns 202 with a job id trackable via
``GET /api/v1/jobs/{id}/status``, which lists the generated options as URLs).
Selection and upload are synchronous and return the resolved artwork URL. The
storage key stays internal — the binary is served through the GET endpoint, like
clip audio.
"""

import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field

from acemusic.constants import ARTWORK_MAX_UPLOAD_BYTES, ARTWORK_PROMPT_MAX_LENGTH
from acemusic.image_processing import ImageValidationError
from acemusic.storage import get_storage_backend

from ..auth.dependencies import CurrentUser, get_current_user, require_existing_user
from ..models import Clip
from ..services import artwork as artwork_service, clips as clip_service
from ..services.artwork import ArtworkNotFoundError
from ..services.clips import get_clip_for_audio_access

logger = logging.getLogger(__name__)

# Router-level dependency gates every route behind a valid Bearer token (mirrors
# the clips/editing routers), so unauthenticated requests get 401.
router = APIRouter(prefix="/clips", tags=["artwork"], dependencies=[Depends(get_current_user)])

_CONTENT_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}


class ArtworkGenerateRequest(BaseModel):
    """Optional override for the auto-derived generation prompt."""

    model_config = ConfigDict(extra="forbid")

    style_prompt: str | None = Field(default=None, max_length=ARTWORK_PROMPT_MAX_LENGTH)


class ArtworkJobResponse(BaseModel):
    """The accepted-job acknowledgement returned with HTTP 202."""

    job_id: str
    status: Literal["queued"] = "queued"


class ArtworkSelectRequest(BaseModel):
    """Selects one generated option by its id."""

    model_config = ConfigDict(extra="forbid")

    artwork_id: str


class ArtworkResponse(BaseModel):
    """The clip's resolved cover-art URL after a select or upload."""

    clip_id: str
    artwork_url: str


async def _artwork_response(clip: Clip) -> ArtworkResponse:
    storage = get_storage_backend()
    # get_url may hit the network (S3 presign), so keep it off the event loop.
    url = await asyncio.to_thread(storage.get_url, clip.artwork_path)
    return ArtworkResponse(clip_id=str(clip.id), artwork_url=url)


@router.post("/{clip_id}/artwork/generate", response_model=ArtworkJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def generate_artwork(
    clip_id: str,
    request: ArtworkGenerateRequest,
    current: CurrentUser = Depends(require_existing_user),
) -> ArtworkJobResponse:
    """Enqueue cover-art generation for ``clip_id``; poll the job for the options."""
    clip = await clip_service.get_owned_clip(clip_id, current.user_id)
    job = await artwork_service.create_artwork_job(clip=clip, style_prompt=request.style_prompt)
    return ArtworkJobResponse(job_id=str(job.id))


@router.post("/{clip_id}/artwork", response_model=ArtworkResponse)
async def select_artwork(
    clip_id: str,
    request: ArtworkSelectRequest,
    current: CurrentUser = Depends(require_existing_user),
) -> ArtworkResponse:
    """Attach a generated option to ``clip_id`` as its cover art."""
    clip = await clip_service.get_owned_clip(clip_id, current.user_id)
    try:
        clip = await artwork_service.select_artwork(clip, request.artwork_id)
    except ArtworkNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return await _artwork_response(clip)


@router.put("/{clip_id}/artwork/upload", response_model=ArtworkResponse)
async def upload_artwork(
    clip_id: str,
    file: UploadFile = File(...),
    current: CurrentUser = Depends(require_existing_user),
) -> ArtworkResponse:
    """Upload custom cover art (JPG/PNG, >=3000x3000) for ``clip_id``."""
    clip = await clip_service.get_owned_clip(clip_id, current.user_id)
    # Reject oversized uploads before buffering the whole body, when the size is
    # known; the service re-checks the actual byte length as the authority.
    if file.size is not None and file.size > ARTWORK_MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Image exceeds the maximum upload size of {ARTWORK_MAX_UPLOAD_BYTES} bytes.",
        )
    data = await file.read()
    try:
        clip = await artwork_service.upload_custom_artwork(clip, data)
    except ImageValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return await _artwork_response(clip)


@router.get("/{clip_id}/artwork")
async def get_artwork(
    clip_id: str,
    current: CurrentUser = Depends(get_current_user),
) -> Response:
    """Return the clip's cover-art bytes (404 if none is set)."""
    # Honors is_public like the audio endpoint: a public clip's art is viewable.
    clip = await get_clip_for_audio_access(clip_id, current.user_id)
    if not clip.artwork_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="This clip has no cover art.")

    storage = get_storage_backend()
    try:
        image = await asyncio.to_thread(storage.download, clip.artwork_path)
    except FileNotFoundError:
        logger.warning("Clip %s has artwork_path %r but the object is missing", clip.id, clip.artwork_path)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cover art file not found.")

    ext = clip.artwork_path.rsplit(".", 1)[-1].lower()
    return Response(content=image, media_type=_CONTENT_TYPES.get(ext, "application/octet-stream"))
