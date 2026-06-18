"""Mastering job handler (US-12.2): Dolby.io Music Mastering integration.

Runs one claimed mastering :class:`~acemusic.api.models.job.Job` end to end against
Dolby.io: load the source clip, download its audio from our storage, upload it to
Dolby's input storage, submit a master *preview* job, poll to completion, read the
mastering metrics (loudness / EQ / stereo image), download each mastered preview,
and store it back as a lineage-tagged child :class:`~acemusic.api.models.clip.Clip`.

Each mastered preview becomes a derived clip (``generation_mode="mastering"``,
``parent_clip_ids=[source]``) so it is immediately auditionable through the existing
job-status endpoint, which resolves audio URLs from ``result["clip_ids"]``. The
A/B selection / approval UX is a separate story (US-12.4). The mastering metrics
ride along in ``result["metrics"]`` so the status endpoint can surface them.

Like the iterative handlers, this needs an external client in addition to storage,
so :class:`~acemusic.api.tasks.processor.JobProcessor` adapts it onto the registry
through ``_run_mastering_handler`` which injects ``storage`` and the Dolby client
(``None`` when credentials are absent — the handler then fails the job with a clear
"not configured" message rather than crashing the app).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from beanie import PydanticObjectId

from acemusic.dolby_client import DolbyClient, DolbyError, master_output_config
from acemusic.storage import StorageBackend

from ..models import Clip, Job
from ..services import credits as credits_service
from ..services.clips import native_format
from ..services.mastering import MASTERING_JOB_TYPE
from .common import JobProcessingError, download_clip, load_source_clip, rollback_clips, store_clip

if TYPE_CHECKING:  # pragma: no cover - import only for typing
    from ..settings import ApiSettings

logger = logging.getLogger(__name__)

# US-12.2 implements the Dolby.io backend only; ``landr``/``bakuage`` are accepted
# by the submission endpoint (US-12.1) but handled by later stories.
_SUPPORTED_SERVICE = "dolby"


async def _refund_unperformed(job: Job, service: str) -> None:
    """Refund the credits charged at enqueue when no mastering work was performed.

    The submission endpoint (US-12.1) charges per service up front. When the worker
    rejects a job before any Dolby work begins — an unsupported service, or a
    deployment with no Dolby credentials — the user must not be left paying for a
    master that was never produced. Best-effort (mirrors the full-song refund): a
    refund failure is logged but never masks the original processing error.
    """
    try:
        cost = credits_service.get_mastering_cost(service)
    except ValueError:  # pragma: no cover - service already validated by the router
        return
    try:
        await credits_service.refund_credits(job.user_id, cost)
    except Exception:  # pragma: no cover - refund is best-effort; never mask the cause
        logger.exception("Failed to refund mastering job %s after a pre-flight rejection", job.id)


def get_dolby_client(settings: "ApiSettings") -> DolbyClient | None:
    """Build a :class:`DolbyClient` from settings, or ``None`` when creds are absent.

    Returning ``None`` (rather than raising) lets the processor register the
    handler unconditionally: a mastering job submitted on a Dolby-less deployment
    is claimed and fails with a clear message, satisfying the "missing credentials
    disable the service (not crash the app)" requirement.
    """
    if not settings.dolby_enabled:
        return None
    return DolbyClient(api_key=settings.dolby_api_key, api_secret=settings.dolby_api_secret)


async def _store_master_clip(
    job: Job,
    source: Clip,
    storage: StorageBackend,
    data: bytes,
    fmt: str,
) -> str:
    """Upload one mastered preview and insert its lineage-tagged child Clip."""
    clip_id = PydanticObjectId()
    clip = Clip(
        id=clip_id,
        user_id=job.user_id,
        workspace_id=job.workspace_id,
        file_path=f"{job.user_id}/{job.workspace_id}/clips/{clip_id}.{fmt}",
        format=fmt,
        # Mastering is loudness/EQ work: duration, tempo and key are preserved.
        duration=source.duration,
        bpm=source.bpm,
        key=source.key,
        style_tags=list(source.style_tags),
        parent_clip_ids=[source.id],
        generation_mode=job.job_type,
        generation_params=dict(job.input_params or {}),
    )
    await store_clip(storage, clip, data)
    return str(clip_id)


async def process_mastering_job(job: Job, *, storage: StorageBackend, client: DolbyClient | None) -> dict[str, Any]:
    """Master the source clip via Dolby.io and store each preview as a child clip.

    Returns ``{"clip_ids": [...], "metrics": {...}, "service": "dolby",
    "target_lufs": <float>}``. ``metrics`` is the loudness / EQ / stereo analysis
    from Dolby. Raises :class:`JobProcessingError` (which the processor records
    as the job's failure) when the service is unsupported, credentials are missing,
    or Dolby reports an error.
    """
    params = dict(job.input_params or {})
    service = params.get("service", _SUPPORTED_SERVICE)
    # Pre-flight rejections refund the credits charged at enqueue (US-12.1): no
    # Dolby work is performed, so the user must not pay for the failed job.
    if service != _SUPPORTED_SERVICE:
        await _refund_unperformed(job, service)
        raise JobProcessingError(
            f"Mastering service {service!r} is not yet implemented; only {_SUPPORTED_SERVICE!r} is available"
        )
    if client is None:
        await _refund_unperformed(job, service)
        raise JobProcessingError(
            "Dolby.io mastering is not configured: set ACEMUSIC_API_DOLBY_API_KEY and ACEMUSIC_API_DOLBY_API_SECRET"
        )

    source = await load_source_clip(job)
    # target_lufs is resolved and stored by the submission endpoint (US-12.1); a
    # job missing it (e.g. a legacy/re-queued doc) fails clearly instead of KeyError.
    if params.get("target_lufs") is None:
        raise JobProcessingError("Mastering job is missing the resolved 'target_lufs' parameter")
    target_lufs = float(params["target_lufs"])
    profile = params.get("profile", "custom")
    fmt = params.get("format") or native_format(source)

    source_bytes = await download_clip(storage, source)

    # Key Dolby's input/output objects by *job* id, not just the source clip, so
    # concurrent masters (or a retry) on the same clip never overwrite or download
    # each other's audio.
    try:
        input_url = await asyncio.to_thread(client.upload, source_bytes, f"{source.id}-{job.id}.{fmt}")
        destination = f"dlb://{source.id}-{job.id}-master.{fmt}"
        outputs = [master_output_config(profile, target_lufs, destination)]
        dolby_job_id = await asyncio.to_thread(client.submit_preview, input_url, outputs)
        status_payload = await asyncio.to_thread(client.wait_for_completion, dolby_job_id)
        # Pass the already-polled terminal payload so get_results reuses it instead
        # of issuing a second status request for the same job.
        results = await asyncio.to_thread(client.get_results, dolby_job_id, status_payload)
    except DolbyError as exc:
        raise JobProcessingError(f"Dolby mastering failed: {exc}") from exc

    preview_handles = [out.get("preview") for out in results.get("outputs", []) if out.get("preview")]
    if not preview_handles:
        raise JobProcessingError("Dolby mastering completed but returned no preview outputs")

    clip_ids: list[str] = []
    try:
        for handle in preview_handles:
            try:
                preview_bytes = await asyncio.to_thread(client.download, handle)
            except DolbyError as exc:
                raise JobProcessingError(f"Dolby preview download failed: {exc}") from exc
            clip_ids.append(await _store_master_clip(job, source, storage, preview_bytes, fmt))
    except BaseException:
        # BaseException (not Exception): a shutdown CancelledError must also roll
        # back, else a requeued retry duplicates the stored previews.
        await rollback_clips(storage, clip_ids)
        raise

    return {
        "clip_ids": clip_ids,
        "service": service,
        "target_lufs": target_lufs,
        "metrics": results.get("metrics", {}),
    }


MASTERING_JOB_HANDLERS = {MASTERING_JOB_TYPE: process_mastering_job}
