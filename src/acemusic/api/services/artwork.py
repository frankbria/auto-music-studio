"""Cover-art service layer (US-13.1).

Owns the artwork business logic behind the ``/clips/{id}/artwork`` endpoints:
building the generation prompt from clip metadata, enqueuing the generation job,
selecting a generated option, and validating + storing a custom upload. Kept
transport-agnostic (plain exceptions, never ``HTTPException``) like the other
service modules — the router maps :class:`ArtworkNotFoundError` to 404 and
:class:`~acemusic.image_processing.ImageValidationError` to 422.
"""

from __future__ import annotations

import asyncio
import logging

from acemusic.constants import (
    ARTWORK_MAX_PIXELS,
    ARTWORK_MAX_UPLOAD_BYTES,
    ARTWORK_MIN_RESOLUTION,
    ARTWORK_PROMPT_MAX_LENGTH,
    VALID_IMAGE_FORMATS,
)
from acemusic.image_processing import ImageValidationError, validate_image
from acemusic.storage import get_storage_backend

from ..models import ArtworkOption, Clip, Job
from .common import coerce_object_id
from .jobs import create_job

logger = logging.getLogger(__name__)

ARTWORK_JOB_TYPE = "artwork"


class ArtworkNotFoundError(Exception):
    """A requested artwork option does not exist or is not owned by the caller."""


def build_artwork_prompt(clip: Clip, style_prompt: str | None = None) -> str:
    """Build the image prompt for ``clip``.

    An explicit ``style_prompt`` overrides the derived one outright (the musician
    knows best). Otherwise the prompt is composed from the clip's title and style
    tags — the metadata that visually characterises the track. Capped at
    ``ARTWORK_PROMPT_MAX_LENGTH`` so a long override can't bloat the job document.
    """
    if style_prompt and style_prompt.strip():
        return style_prompt.strip()[:ARTWORK_PROMPT_MAX_LENGTH]

    parts = ["Album cover art"]
    if clip.title:
        parts.append(f"for the track '{clip.title}'")
    if clip.style_tags:
        parts.append(f"in a {', '.join(clip.style_tags)} style")
    parts.append("professional, high quality, no text")
    return ", ".join(parts)[:ARTWORK_PROMPT_MAX_LENGTH]


async def create_artwork_job(*, clip: Clip, style_prompt: str | None = None) -> Job:
    """Persist a queued artwork-generation job for ``clip`` and dispatch it.

    The prompt is resolved here (not in the worker) so the job document carries
    everything generation needs, matching the other service modules.
    """
    return await create_job(
        user_id=clip.user_id,
        workspace_id=clip.workspace_id,
        job_type=ARTWORK_JOB_TYPE,
        params={"clip_id": str(clip.id), "prompt": build_artwork_prompt(clip, style_prompt)},
    )


async def select_artwork(clip: Clip, artwork_id: str) -> Clip:
    """Attach the generated option ``artwork_id`` to ``clip`` as its cover art.

    Raises :class:`ArtworkNotFoundError` if the option does not exist, belongs to
    another user, or was generated for a different clip — so a caller can never
    select someone else's artwork or cross-wire two clips.
    """
    oid = coerce_object_id(artwork_id)
    option = await ArtworkOption.get(oid) if oid is not None else None
    if option is None or option.user_id != clip.user_id or option.clip_id != clip.id:
        raise ArtworkNotFoundError("Artwork option not found.")
    clip.artwork_path = option.storage_path
    await clip.save()
    return clip


async def upload_custom_artwork(clip: Clip, data: bytes) -> Clip:
    """Validate ``data`` and store it as ``clip``'s custom cover art.

    Enforces the upload contract: under the size cap, an accepted raster format,
    not corrupt, and at least ``ARTWORK_MIN_RESOLUTION`` on both sides. Raises
    :class:`ImageValidationError` (mapped to 422) on any breach.
    """
    if len(data) > ARTWORK_MAX_UPLOAD_BYTES:
        raise ImageValidationError(
            f"Image is {len(data)} bytes; the maximum upload size is {ARTWORK_MAX_UPLOAD_BYTES} bytes."
        )
    # One decode does it all: format, integrity (load), pixel-bomb guard, and the
    # dimensions we need for the resolution check — no re-parsing.
    fmt, width, height = validate_image(data, max_pixels=ARTWORK_MAX_PIXELS)
    if fmt not in VALID_IMAGE_FORMATS:
        raise ImageValidationError(f"Unsupported image format {fmt!r}; use {', '.join(sorted(VALID_IMAGE_FORMATS))}.")
    if width < ARTWORK_MIN_RESOLUTION or height < ARTWORK_MIN_RESOLUTION:
        raise ImageValidationError(
            f"Image is {width}x{height}; at least {ARTWORK_MIN_RESOLUTION}x{ARTWORK_MIN_RESOLUTION} "
            "is required for distribution."
        )

    ext = "png" if fmt == "png" else "jpg"
    base = f"{clip.user_id}/{clip.workspace_id}/artwork/{clip.id}"
    path = f"{base}/upload.{ext}"
    storage = get_storage_backend()
    await asyncio.to_thread(storage.upload, path, data)
    # A prior upload in the *other* format would otherwise be orphaned. Deleting
    # only the sibling upload key (never a generated option's path, which an
    # ArtworkOption doc still references) is safe and idempotent.
    other = f"{base}/upload.{'jpg' if ext == 'png' else 'png'}"
    try:
        await asyncio.to_thread(storage.delete, other)
    except Exception:  # pragma: no cover - cleanup is best-effort, must not fail the upload
        logger.warning("Failed to delete prior upload %s while replacing artwork for clip %s", other, clip.id)
    clip.artwork_path = path
    await clip.save()
    return clip
