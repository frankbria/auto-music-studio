"""Mastering job handler (US-12.2 + US-12.3 fallback integrations).

Runs one claimed mastering :class:`~acemusic.api.models.job.Job` end to end:
load the source clip, download its audio from our storage, hand it to the
:class:`~acemusic.mastering_orchestrator.MasteringOrchestrator` which runs the
requested backend (Dolby.io / LANDR / Bakuage) and falls back across the
configured services on failure, then store the mastered audio back as a
lineage-tagged child :class:`~acemusic.api.models.clip.Clip`.

The mastered clip (``generation_mode="mastering"``,
``parent_clip_ids=[source]``) is immediately auditionable through the existing
job-status endpoint, which resolves audio URLs from ``result["clip_ids"]``. The
mastering metrics ride along in ``result["metrics"]`` and the backend that
actually ran in ``result["service"]`` (which may differ from the requested
service when a fallback succeeded). The A/B selection / approval UX is a
separate story (US-12.4).

Each backend implements the shared
:class:`~acemusic.mastering_protocol.MasteringService` contract behind a single
``master()`` entrypoint, so this handler is backend-agnostic: it only knows the
orchestrator's ``master_with_fallback`` call. An explicitly requested service
that is not configured raises :class:`ServiceNotConfiguredError`, which the
handler turns into a refunded pre-flight rejection (no mastering work performed,
so the user must not pay). Like the iterative handlers, the orchestrator needs
to be injected alongside storage.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from beanie import PydanticObjectId

from acemusic.mastering_orchestrator import MasteringOrchestrator, ServiceNotConfiguredError
from acemusic.storage import StorageBackend

from ..models import Clip, Job
from ..services import credits as credits_service
from ..services.clips import native_format
from ..services.mastering import MASTERING_JOB_TYPE
from .common import JobProcessingError, download_clip, load_source_clip, store_clip

if TYPE_CHECKING:  # pragma: no cover - import only for typing
    from ..settings import ApiSettings

logger = logging.getLogger(__name__)


async def _refund_unperformed(job: Job, service: str) -> None:
    """Refund the credits charged at enqueue when no mastering work was performed.

    The submission endpoint (US-12.1) charges per service up front. When the worker
    rejects a job before any mastering work begins — a service requested without
    configured credentials, or a deployment with no mastering backend at all — the
    user must not be left paying for a master that was never produced. Best-effort
    (mirrors the full-song refund): a refund failure is logged but never masks the
    original processing error.
    """
    try:
        cost = credits_service.get_mastering_cost(service)
    except ValueError:  # pragma: no cover - service already validated by the router
        return
    try:
        await credits_service.refund_credits(job.user_id, cost)
    except Exception:  # pragma: no cover - refund is best-effort; never mask the cause
        logger.exception("Failed to refund mastering job %s after a pre-flight rejection", job.id)


def get_mastering_orchestrator(settings: "ApiSettings") -> MasteringOrchestrator:
    """Build the :class:`MasteringOrchestrator` from the configured backends.

    Only services whose credentials are present are wired in, so the orchestrator's
    fallback chain naturally skips unconfigured backends. A deployment with no
    mastering credentials at all yields an empty orchestrator; the handler then
    fails a claimed job with a clear "not configured" message rather than crashing.
    """
    clients: dict[str, Any] = {}
    if settings.dolby_enabled:
        from acemusic.dolby_client import DolbyClient

        clients["dolby"] = DolbyClient(api_key=settings.dolby_api_key, api_secret=settings.dolby_api_secret)
    if settings.landr_enabled:
        from acemusic.landr_client import LandrClient

        clients["landr"] = LandrClient(api_key=settings.landr_api_key, api_secret=settings.landr_api_secret)
    if settings.bakuage_enabled:
        from acemusic.bakuage_client import BakuageClient

        clients["bakuage"] = BakuageClient(api_key=settings.bakuage_api_key)
    return MasteringOrchestrator(clients)


async def _store_master_clip(
    job: Job,
    source: Clip,
    storage: StorageBackend,
    data: bytes,
    fmt: str,
) -> str:
    """Upload the mastered audio and insert its lineage-tagged child Clip."""
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


async def process_mastering_job(
    job: Job, *, storage: StorageBackend, orchestrator: MasteringOrchestrator
) -> dict[str, Any]:
    """Master the source clip via the orchestrator and store the result as a child clip.

    Returns ``{"clip_ids": [<id>], "metrics": {...}, "service": <str>,
    "target_lufs": <float>}``. ``service`` is the backend that actually ran
    (which may differ from the requested service when a fallback succeeded).
    Raises :class:`JobProcessingError` (recorded as the job's failure) when the
    requested service is not configured, no backend is configured at all, or
    every backend in the fallback chain reports an error.
    """
    params = dict(job.input_params or {})
    service = params.get("service", "dolby")

    # Pre-flight rejections refund the credits charged at enqueue (US-12.1): no
    # mastering work is performed, so the user must not pay for the failed job.
    try:
        orchestrator.get_client(service)
    except ServiceNotConfiguredError as exc:
        await _refund_unperformed(job, service)
        hint = _configuration_hint()
        raise JobProcessingError(f"{exc} {hint}") from exc

    source = await load_source_clip(job)
    # target_lufs is resolved and stored by the submission endpoint (US-12.1); a
    # job missing it (e.g. a legacy/re-queued doc) fails clearly instead of KeyError.
    if params.get("target_lufs") is None:
        raise JobProcessingError("Mastering job is missing the resolved 'target_lufs' parameter")
    target_lufs = float(params["target_lufs"])
    profile = params.get("profile", "custom")
    fmt = params.get("format") or native_format(source)

    source_bytes = await download_clip(storage, source)

    # Key the upload by *job* id, not just the source clip, so concurrent masters
    # (or a retry) on the same clip never overwrite or download each other's audio.
    filename = f"{source.id}-{job.id}.{fmt}"
    try:
        output = await asyncio.to_thread(
            orchestrator.master_with_fallback,
            source_bytes,
            filename,
            profile,
            target_lufs,
            fmt,
            requested_service=service,
        )
    except ServiceNotConfiguredError as exc:
        # Defensive: master_with_fallback raises this only for an unconfigured
        # *requested* service, which the pre-flight get_client already caught.
        await _refund_unperformed(job, service)
        raise JobProcessingError(str(exc)) from exc
    except Exception as exc:
        raise JobProcessingError(f"Mastering failed: {exc}") from exc

    clip_id = await _store_master_clip(job, source, storage, output.audio_bytes, fmt)
    if output.service != service:
        logger.info("Mastering job %s fell back from %s to %s", job.id, service, output.service)

    return {
        "clip_ids": [clip_id],
        "service": output.service,
        "target_lufs": target_lufs,
        "metrics": output.metrics,
    }


def _configuration_hint() -> str:
    """A human-readable hint naming the mastering env vars, for error messages."""
    return (
        "Set mastering credentials to enable a backend: "
        "ACEMUSIC_API_DOLBY_API_KEY + ACEMUSIC_API_DOLBY_API_SECRET (Dolby.io), "
        "ACEMUSIC_API_LANDR_API_KEY + ACEMUSIC_API_LANDR_API_SECRET (LANDR), or "
        "ACEMUSIC_API_BAKUAGE_API_KEY (Bakuage)."
    )


MASTERING_JOB_HANDLERS = {MASTERING_JOB_TYPE: process_mastering_job}
