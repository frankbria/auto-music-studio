"""Clip endpoints (US-9.3 audio retrieval, US-9.4 CRUD), mounted under ``/api/v1/clips``.

* ``GET    /clips``           → paginated list with search/filter/sort (US-9.4)
* ``GET    /clips/{id}``      → clip metadata (404 if missing/not owned)
* ``PATCH  /clips/{id}``      → rename (title is the only writable field)
* ``DELETE /clips/{id}``      → remove the record and its stored audio
* ``GET    /clips/{id}/audio``→ stream audio, byte ranges + ``?format=`` (US-9.3)

CRUD is owner-scoped; only the audio endpoint honors ``is_public``. Access and
filter rules live in :mod:`acemusic.api.services.clips`.
"""

import asyncio
import logging
import math
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from acemusic.storage import get_storage_backend

from ..auth.dependencies import CurrentUser, get_current_user, require_existing_user
from ..models import Clip
from ..services import clips as clip_service
from ..services.audio_conversion import convert_audio_format
from ..services.clips import get_clip_for_audio_access
from ..utils.media_types import get_audio_content_type
from ..utils.range_requests import parse_range_header

logger = logging.getLogger(__name__)

# Titles are stored verbatim and re-served on every list; cap them so one PATCH
# cannot bloat the document (mirrors the users router's field caps).
CLIP_TITLE_MAX_LENGTH = 200
PER_PAGE_DEFAULT = 20
PER_PAGE_MAX = 100

# Router-level dependency gates every route behind a valid Bearer token
# (mirrors the jobs/generation routers), so unauthenticated requests get 401.
router = APIRouter(prefix="/clips", tags=["clips"], dependencies=[Depends(get_current_user)])


class ClipSearchParams(BaseModel):
    """Query parameters for ``GET /clips`` (validated as one unit via Depends)."""

    workspace_id: str | None = None
    search: str | None = None
    style: str | None = None
    bpm_min: int | None = Field(default=None, ge=0)
    bpm_max: int | None = Field(default=None, ge=0)
    key: str | None = None
    model: str | None = None
    sort: Literal["newest", "oldest"] = "newest"
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=PER_PAGE_DEFAULT, ge=1, le=PER_PAGE_MAX)

    @model_validator(mode="after")
    def _check_bpm_range(self) -> "ClipSearchParams":
        # An inverted range can never match; reject it as the client error it
        # is instead of silently returning an empty page.
        if self.bpm_min is not None and self.bpm_max is not None and self.bpm_min > self.bpm_max:
            raise ValueError("bpm_min must not be greater than bpm_max.")
        return self


class ClipUpdate(BaseModel):
    """Rename payload. ``extra="forbid"`` rejects any non-title field with 422."""

    model_config = ConfigDict(extra="forbid")

    title: Annotated[str, Field(min_length=1, max_length=CLIP_TITLE_MAX_LENGTH)] | None = None

    @field_validator("title")
    @classmethod
    def _check_title(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("Clip title must not be blank.")
        return value


class ClipResponse(BaseModel):
    # ``file_path`` is deliberately absent: storage keys are internal, and
    # clients retrieve audio through ``GET /clips/{id}/audio``.
    id: str
    workspace_id: str
    title: str | None
    format: str | None
    duration: float | None
    bpm: int | None
    key: str | None
    style_tags: list[str]
    lyrics: str | None
    vocal_language: str | None
    model: str | None
    seed: int | None
    inference_steps: int | None
    parent_clip_ids: list[str]
    generation_mode: str | None
    is_public: bool
    created_at: datetime

    @classmethod
    def from_clip(cls, clip: Clip) -> "ClipResponse":
        return cls(
            id=str(clip.id),
            workspace_id=str(clip.workspace_id),
            title=clip.title,
            format=clip.format,
            duration=clip.duration,
            bpm=clip.bpm,
            key=clip.key,
            style_tags=clip.style_tags,
            lyrics=clip.lyrics,
            vocal_language=clip.vocal_language,
            model=clip.model,
            seed=clip.seed,
            inference_steps=clip.inference_steps,
            parent_clip_ids=[str(pid) for pid in clip.parent_clip_ids],
            generation_mode=clip.generation_mode,
            is_public=clip.is_public,
            created_at=clip.created_at,
        )


class ClipListResponse(BaseModel):
    clips: list[ClipResponse]
    total: int
    page: int
    per_page: int
    total_pages: int


@router.get("", response_model=ClipListResponse)
async def list_clips(
    # Annotated[..., Query()] (not plain Depends) makes FastAPI validate the
    # model as one unit, so the cross-field bpm validator surfaces as 422.
    params: Annotated[ClipSearchParams, Query()],
    current: CurrentUser = Depends(require_existing_user),
) -> ClipListResponse:
    items, total = await clip_service.list_clips(
        current.user_id,
        workspace_id=params.workspace_id,
        search=params.search,
        style=params.style,
        bpm_min=params.bpm_min,
        bpm_max=params.bpm_max,
        key=params.key,
        model=params.model,
        sort=params.sort,
        page=params.page,
        per_page=params.per_page,
    )
    return ClipListResponse(
        clips=[ClipResponse.from_clip(clip) for clip in items],
        total=total,
        page=params.page,
        per_page=params.per_page,
        total_pages=math.ceil(total / params.per_page),
    )


@router.get("/{clip_id}", response_model=ClipResponse)
async def get_clip(clip_id: str, current: CurrentUser = Depends(require_existing_user)) -> ClipResponse:
    clip = await clip_service.get_owned_clip(clip_id, current.user_id)
    return ClipResponse.from_clip(clip)


@router.patch("/{clip_id}", response_model=ClipResponse)
async def update_clip(
    clip_id: str,
    body: ClipUpdate,
    current: CurrentUser = Depends(require_existing_user),
) -> ClipResponse:
    """Rename the clip; an empty body is a no-op returning the current state."""
    if body.title is None:
        clip = await clip_service.get_owned_clip(clip_id, current.user_id)
    else:
        clip = await clip_service.update_clip_title(clip_id, current.user_id, body.title)
    return ClipResponse.from_clip(clip)


@router.delete("/{clip_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_clip(clip_id: str, current: CurrentUser = Depends(require_existing_user)) -> Response:
    await clip_service.delete_clip(clip_id, current.user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{clip_id}/audio")
async def get_clip_audio(
    clip_id: str,
    request: Request,
    format: Literal["wav", "flac", "mp3"] | None = Query(
        default=None,
        description="Convert to this format on the fly (default: the clip's stored format).",
    ),
    current: CurrentUser = Depends(get_current_user),
) -> Response:
    """Return the clip's audio — full (200) or a requested byte range (206)."""
    clip = await get_clip_for_audio_access(clip_id, current.user_id)

    storage = get_storage_backend()
    try:
        # download() does file/network I/O via the sync backend; keep it off
        # the event loop.
        audio = await asyncio.to_thread(storage.download, clip.file_path)
    except FileNotFoundError:
        # The clip document exists but its object is gone — a data integrity
        # problem worth logging, surfaced to the client as a plain 404.
        logger.warning("Clip %s exists but its audio object %r is missing", clip.id, clip.file_path)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audio file not found.")

    native_format = (clip.format or Path(clip.file_path).suffix.lstrip(".") or "wav").lower()
    serve_format = native_format
    converted = False
    if format is not None and format != native_format:
        try:
            audio = await asyncio.to_thread(convert_audio_format, audio, native_format, format)
        except Exception as exc:
            logger.exception("Format conversion of clip %s (%s -> %s) failed", clip.id, native_format, format)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Could not convert audio to {format}.",
            ) from exc
        serve_format = format
        converted = True

    # Byte ranges address the stored representation; conversion produces a
    # different byte layout, so Range (and the Accept-Ranges advertisement)
    # only applies to unconverted responses.
    headers = {} if converted else {"Accept-Ranges": "bytes"}
    media_type = get_audio_content_type(serve_format)

    range_header = request.headers.get("range")
    if range_header is not None and not converted:
        byte_range = parse_range_header(range_header, len(audio))
        if byte_range is not None:
            start, end = byte_range
            headers["Content-Range"] = f"bytes {start}-{end}/{len(audio)}"
            return Response(
                content=audio[start : end + 1],
                status_code=status.HTTP_206_PARTIAL_CONTENT,
                media_type=media_type,
                headers=headers,
            )

    return Response(content=audio, media_type=media_type, headers=headers)
