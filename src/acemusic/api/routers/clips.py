"""Clip audio retrieval endpoint (US-9.3), mounted under ``/api/v1/clips``.

``GET /api/v1/clips/{clip_id}/audio`` streams a clip's audio with the correct
Content-Type, supports single byte-range requests (206 Partial Content) for
seeking, and optionally converts to another format via ``?format=``. Access
rules live in :func:`acemusic.api.services.clips.get_clip_for_audio_access`.
"""

import asyncio
import logging
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from acemusic.storage import get_storage_backend

from ..auth.dependencies import CurrentUser, get_current_user
from ..services.audio_conversion import convert_audio_format
from ..services.clips import get_clip_for_audio_access
from ..utils.media_types import get_audio_content_type
from ..utils.range_requests import parse_range_header

logger = logging.getLogger(__name__)

# Router-level dependency gates every route behind a valid Bearer token
# (mirrors the jobs/generation routers), so unauthenticated requests get 401.
router = APIRouter(prefix="/clips", tags=["clips"], dependencies=[Depends(get_current_user)])


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

    headers = {"Accept-Ranges": "bytes"}
    media_type = get_audio_content_type(serve_format)

    # Byte ranges address the stored representation; conversion produces a
    # different byte layout, so Range only applies to unconverted responses.
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
