"""Video-generation job handler (US-22.1).

Runs the queued ``video`` job: downloads the source song's audio, submits it
with the resolved rendering options to the external video provider, polls the
provider to completion (surfacing state/progress/ETA on ``job.progress_detail``
for the status endpoint), then stores the rendered MP4 and records a
:class:`Video` document associating it with the song. A failure after the
upload rolls the stored object back, so a ``failed`` job never leaves orphaned
files behind (mirrors the artwork/mastering handlers).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from acemusic.storage import StorageBackend
from acemusic.video_client import (
    COMPLETE,
    FAILED,
    HttpVideoClient,
    VideoGenerationError,
    VideoGenerationService,
)

from ..models import Job, Video
from ..services import clips as clip_service
from ..services.video import VIDEO_JOB_TYPE
from .common import JobProcessingError, download_clip, load_source_clip

if TYPE_CHECKING:
    from ..settings import ApiSettings

logger = logging.getLogger(__name__)

POLL_INTERVAL_S = 5.0
# Poll budget for the provider render. Note the handler's worst-case wall time
# (submit + this poll budget + download) can exceed the processor's stale-requeue
# window (poll_timeout + 300s, 900s by default). The stale sweep only runs at
# process START, so a single-process deployment is safe (a restart killed the old
# worker anyway); only a multi-process deployment starting a sibling mid-render
# could re-queue a live job. Acceptable for now — revisit if video ever runs
# multi-process (raise stale_after for this job type).
POLL_TIMEOUT_S = 600.0

# One failed status poll must not kill a paid render that is still progressing on
# the provider side (connection blips over a minutes-long poll window are
# expected). Only this many consecutive failures fail the job.
_MAX_CONSECUTIVE_POLL_FAILURES = 3


def get_video_client(settings: "ApiSettings") -> VideoGenerationService | None:
    """Build the video client when video generation is configured, else None.

    None when no provider URL/key is set; the handler then fails a claimed job
    with a clear "not configured" message rather than crashing the worker
    (mirrors the mastering orchestrator and image client factories).
    """
    if not settings.video_enabled:
        return None
    return HttpVideoClient(base_url=settings.video_api_url, api_key=settings.video_api_key)


async def _set_progress(job: Job, state: str, progress: int | None, eta_seconds: float | None) -> None:
    """Record one provider update on the job for the status endpoint to serve."""
    detail: dict[str, Any] = {"state": state}
    if progress is not None:
        detail["progress"] = max(0, min(100, progress))
    if eta_seconds is not None:
        detail["eta_seconds"] = eta_seconds
    await job.set({Job.progress_detail: detail})


async def process_video_job(
    job: Job,
    *,
    storage: StorageBackend,
    client: VideoGenerationService,
    poll_interval: float = POLL_INTERVAL_S,
    poll_timeout: float = POLL_TIMEOUT_S,
) -> dict[str, Any]:
    """Render, store and associate the song's music video.

    Returns ``{"video_ids": [<id>], "storage_path": <path>}``. Raises
    :class:`JobProcessingError` on provider failure/timeout; the processor
    records the message as the job's failure. Transient (5xx) provider errors
    are already retried inside the client (shared ``_http`` policy, 3 retries).
    """
    clip = await load_source_clip(job)
    audio = await download_clip(storage, clip)
    params = dict(job.input_params or {})
    params.pop("clip_id", None)  # provider gets the audio itself, not our id
    filename = f"{clip.id}.{clip_service.native_format(clip)}"

    try:
        provider_job_id = await asyncio.to_thread(client.submit, audio, filename, params)
    except VideoGenerationError as exc:
        raise JobProcessingError(f"Video provider submission failed: {exc}") from exc

    deadline = time.monotonic() + poll_timeout
    poll_failures = 0
    while True:
        update = None
        try:
            update = await asyncio.to_thread(client.get_status, provider_job_id)
        except VideoGenerationError as exc:
            poll_failures += 1
            if poll_failures >= _MAX_CONSECUTIVE_POLL_FAILURES:
                raise JobProcessingError(f"Video provider status poll failed: {exc}") from exc
        if update is not None:
            poll_failures = 0
            await _set_progress(job, update.state, update.progress, update.eta_seconds)
            if update.state == COMPLETE:
                break
            if update.state == FAILED:
                raise JobProcessingError(f"Video rendering failed: {update.error or 'provider reported failure'}")
        if time.monotonic() >= deadline:
            raise JobProcessingError(f"Video rendering timed out after {poll_timeout:.0f}s")
        await asyncio.sleep(poll_interval)

    try:
        data = await asyncio.to_thread(client.download, provider_job_id)
    except VideoGenerationError as exc:
        raise JobProcessingError(f"Video download failed: {exc}") from exc

    # Namespace by job id so re-rendering the same song never overwrites an
    # earlier video (and a failed job's rollback only deletes its own object).
    path = f"{job.user_id}/{job.workspace_id}/videos/{clip.id}/{job.id}.mp4"
    await asyncio.to_thread(storage.upload, path, data)
    video = Video(
        clip_id=clip.id,
        user_id=job.user_id,
        job_id=job.id,
        storage_path=path,
        resolution=str(params.get("resolution", "")),
        aspect_ratio=str(params.get("aspect_ratio", "")),
    )
    try:
        await video.insert()
    except BaseException:
        # BaseException (not Exception): a shutdown CancelledError must also clean
        # up the just-uploaded object, else a requeued retry leaves it orphaned.
        try:
            await asyncio.to_thread(storage.delete, path)
        except Exception:  # pragma: no cover - cleanup is best-effort
            logger.exception("Failed to delete orphaned video object %s during rollback", path)
        raise

    await _set_progress(job, COMPLETE, 100, None)
    return {"video_ids": [str(video.id)], "storage_path": path}


VIDEO_JOB_HANDLERS = {VIDEO_JOB_TYPE: process_video_job}
