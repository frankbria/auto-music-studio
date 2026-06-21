"""Cover-art generation job handler (US-13.1).

Runs the queued ``artwork`` job: build is done at enqueue (the prompt lives in
``job.input_params``), so the worker generates ``ARTWORK_OPTIONS_COUNT`` images via
the image client, upscales each 1024 image to the 3000x3000 distribution master,
stores them, and records one :class:`ArtworkOption` per option. A failure partway
through rolls back the options already stored, so a ``failed`` job never leaves
orphaned files or documents behind (mirrors the editing/mastering handlers).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from beanie import PydanticObjectId

from acemusic.constants import ARTWORK_FINAL_SIZE, ARTWORK_OPTIONS_COUNT
from acemusic.image_client import ImageGenerationClient
from acemusic.image_processing import upscale_image
from acemusic.storage import StorageBackend

from ..models import ArtworkOption, Job
from ..services.artwork import ARTWORK_JOB_TYPE
from .common import JobProcessingError, load_source_clip

if TYPE_CHECKING:
    from ..settings import ApiSettings

logger = logging.getLogger(__name__)


def get_image_client(settings: "ApiSettings") -> ImageGenerationClient | None:
    """Build the image client when artwork generation is configured, else None.

    None when no OpenAI key is set or the feature is kill-switched; the handler
    then fails a claimed job with a clear "not configured" message rather than
    crashing the worker (mirrors the mastering orchestrator factory).
    """
    if not settings.artwork_enabled:
        return None
    return ImageGenerationClient(api_key=settings.openai_api_key)


async def _rollback_artwork(storage: StorageBackend, stored_paths: list[str], option_ids: list[str]) -> None:
    """Best-effort removal of options already stored before a mid-batch failure."""
    for path in stored_paths:
        try:
            await asyncio.to_thread(storage.delete, path)
        except Exception:  # pragma: no cover - cleanup is best-effort
            logger.exception("Failed to delete orphaned artwork object %s during rollback", path)
    for option_id in option_ids:
        option = await ArtworkOption.get(PydanticObjectId(option_id))
        if option is not None:
            try:
                await option.delete()
            except Exception:  # pragma: no cover - cleanup is best-effort
                logger.exception("Failed to delete orphaned artwork option %s during rollback", option_id)


async def process_artwork_job(job: Job, *, storage: StorageBackend, client: ImageGenerationClient) -> dict[str, Any]:
    """Generate, upscale and store the clip's cover-art options.

    Returns ``{"artwork_option_ids": [<id>, ...]}``. Raises
    :class:`JobProcessingError` when the resolved prompt is missing; image-API and
    storage failures propagate (the processor records them as the job's failure).
    """
    clip = await load_source_clip(job)
    prompt = (job.input_params or {}).get("prompt")
    if not prompt:
        raise JobProcessingError("Artwork job is missing the resolved 'prompt' parameter")

    images = await asyncio.to_thread(client.generate_images, prompt, ARTWORK_OPTIONS_COUNT)

    option_ids: list[str] = []
    stored_paths: list[str] = []
    try:
        for idx, raw in enumerate(images):
            upscaled = await asyncio.to_thread(upscale_image, raw, ARTWORK_FINAL_SIZE)
            # Namespace by job id so regenerating for the same clip never overwrites
            # an earlier batch (and a failed regen's rollback only deletes its own
            # objects, not a previously selected cover sharing a path).
            path = f"{job.user_id}/{job.workspace_id}/artwork/{clip.id}/{job.id}/{idx}.png"
            await asyncio.to_thread(storage.upload, path, upscaled)
            stored_paths.append(path)
            option = ArtworkOption(
                clip_id=clip.id,
                user_id=job.user_id,
                job_id=job.id,
                storage_path=path,
                option_index=idx,
            )
            await option.insert()
            option_ids.append(str(option.id))
    except BaseException:
        # BaseException (not Exception): a shutdown CancelledError must also clean
        # up, else a requeued retry leaves earlier options orphaned.
        await _rollback_artwork(storage, stored_paths, option_ids)
        raise

    return {"artwork_option_ids": option_ids}


ARTWORK_JOB_HANDLERS = {ARTWORK_JOB_TYPE: process_artwork_job}
