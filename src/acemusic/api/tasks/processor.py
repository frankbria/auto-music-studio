"""Async job processor (US-9.2, generalised for multiple job types in US-10.1).

A background worker that drives queued jobs to completion inside the FastAPI
process. It polls MongoDB for ``status=queued`` jobs — a stateless,
restart-safe design that mirrors how a future Celery/Redis swap would behave —
atomically claims each, dispatches it to the handler registered for its
``job_type`` (generation runs ACE-Step and stores the audio; editing handlers
live in :mod:`acemusic.api.tasks.editing`), and transitions the job
``queued -> processing -> completed | failed``.

The ACE-Step client and storage backend are synchronous, so their blocking calls
run in a worker thread (:func:`asyncio.to_thread`) to keep the event loop
responsive. Concurrency is bounded by an :class:`asyncio.Semaphore`; :meth:`stop`
cancels in-flight work for a graceful shutdown.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import timedelta
from functools import partial
from typing import Any

from beanie import PydanticObjectId
from pymongo import ASCENDING, ReturnDocument

from acemusic.client import AceStepClient
from acemusic.config import load_config
from acemusic.mastering_orchestrator import MasteringOrchestrator
from acemusic.runpod_client import RunPodClient
from acemusic.storage import StorageBackend, get_storage_backend

from .. import database
from ..models import Clip, Job, JobStatus
from ..models.common import utcnow
from .common import JobProcessingError
from .editing import EDIT_JOB_HANDLERS
from .export import EXPORT_JOB_HANDLERS
from .extraction import EXTRACTION_JOB_HANDLERS
from .iterative import ITERATIVE_JOB_HANDLERS
from .mastering import MASTERING_JOB_HANDLERS

logger = logging.getLogger(__name__)

# query_result already normalises ACE-Step's integer status codes to these.
_TERMINAL_STATES = {"completed", "failed"}

# input_params is the verbatim GenerationRequest snapshot. submit_task accepts a
# focused subset; anything else (API-only fields) is ignored. prompt/duration/
# format are mapped explicitly below.
_SUBMIT_FIELDS = (
    "style",
    "lyrics",
    "vocal_language",
    "instrumental",
    "bpm",
    "key",
    "time_signature",
    "seed",
    "inference_steps",
    "weirdness",
    "style_influence",
    "thinking",
    "model",
    "mode",
    "sound_type",
)


JobHandler = Callable[[Job], Awaitable[dict[str, Any]]]


def _default_client_factory() -> AceStepClient:
    """Build an ACE-Step client from the CLI config (env > .env > config.yaml)."""
    config = load_config()
    if not config.api_url:
        raise JobProcessingError("ACE-Step base URL is not configured (set ACEMUSIC_BASE_URL).")
    return AceStepClient(base_url=config.api_url, api_key=config.api_key)


class JobProcessor:
    """Background worker pool that processes queued jobs by ``job_type``.

    Each registered job_type maps to a handler; the built-in ``generate``
    handler runs ACE-Step generations. The ACE-Step client and storage backend
    are obtained through factories so tests can inject in-process doubles;
    production uses the real config-driven client and the configured storage
    backend.
    """

    def __init__(
        self,
        *,
        concurrency: int = 2,
        poll_interval: float = 1.0,
        poll_timeout: float = 600.0,
        ace_poll_interval: float = 2.0,
        stale_after: float | None = None,
        client_factory: Callable[[], AceStepClient] | None = None,
        runpod_client_factory: Callable[[], RunPodClient] | None = None,
        runpod_timeout: float = 300.0,
        runpod_poll_interval: float = 5.0,
        mastering_orchestrator_factory: Callable[[], MasteringOrchestrator] | None = None,
        storage_factory: Callable[[], StorageBackend] | None = None,
        handlers: dict[str, JobHandler] | None = None,
    ) -> None:
        self._concurrency = concurrency
        self._semaphore = asyncio.Semaphore(concurrency)
        self._poll_interval = poll_interval
        self._poll_timeout = poll_timeout
        self._ace_poll_interval = ace_poll_interval
        # Remote (RunPod) generation (US-11.2). The factory is None unless RunPod is
        # configured; a job routed to ``remote`` (US-11.1) without it fails loudly
        # rather than silently running locally. The remote poll interval defaults
        # higher than the local one to tolerate serverless cold starts.
        self._runpod_client_factory = runpod_client_factory
        self._runpod_timeout = runpod_timeout
        self._runpod_poll_interval = runpod_poll_interval
        # Mastering orchestrator (US-12.3). The factory builds the orchestrator
        # from the configured backends (Dolby/LANDR/Bakuage); None only when no
        # mastering credentials are set at all, in which case the mastering handler
        # fails a claimed job with a clear message rather than crashing.
        self._mastering_orchestrator_factory = mastering_orchestrator_factory
        # A job legitimately stays in `processing` for at most poll_timeout (its
        # own worker fails it after that). Only re-queue jobs older than that
        # window plus a margin, so a startup sweep never reclaims a job a live
        # sibling process is still working — see _requeue_stale_jobs.
        self._stale_after = stale_after if stale_after is not None else poll_timeout + 300.0
        self._client_factory = client_factory or _default_client_factory
        self._storage_factory = storage_factory or get_storage_backend
        # Handler registry keyed by job_type: only registered types are claimed
        # (and re-queued when stale), so jobs another deployment owns are left
        # alone. ``handlers`` lets callers add or override entries.
        self._handlers: dict[str, JobHandler] = {"generate": self._handle_generate}
        # Editing, extraction, and export handlers share the same ``(job, storage)``
        # contract, so all are adapted onto the registry the same way.
        for job_type, storage_handler in {
            **EDIT_JOB_HANDLERS,
            **EXTRACTION_JOB_HANDLERS,
            **EXPORT_JOB_HANDLERS,
        }.items():
            self._handlers[job_type] = partial(self._run_storage_handler, storage_handler)
        # Iterative generation handlers (US-10.3) are generative: they need the
        # ACE-Step client and the poll loop in addition to storage, so they are
        # adapted through their own injecting wrapper.
        for job_type, iterative_handler in ITERATIVE_JOB_HANDLERS.items():
            self._handlers[job_type] = partial(self._run_iterative_handler, iterative_handler)
        # Mastering handlers (US-12.2 / US-12.3) need storage plus the mastering
        # orchestrator (which selects and falls back across Dolby/LANDR/Bakuage),
        # so they get their own injecting wrapper.
        for job_type, mastering_handler in MASTERING_JOB_HANDLERS.items():
            self._handlers[job_type] = partial(self._run_mastering_handler, mastering_handler)
        if handlers:
            self._handlers.update(handlers)
        self._running = False
        self._worker_task: asyncio.Task[None] | None = None
        self._active: set[asyncio.Task[None]] = set()

    # -- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        """Re-queue stale jobs, then launch the polling worker. Idempotent."""
        if self._running:
            return
        self._running = True
        await self._requeue_stale_jobs()
        self._worker_task = asyncio.create_task(self._run_worker())
        logger.info("Job processor started (concurrency=%d)", self._concurrency)

    async def stop(self) -> None:
        """Stop polling and cancel any in-flight jobs, awaiting their unwind."""
        self._running = False
        if self._worker_task is not None:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
        active = list(self._active)
        for task in active:
            task.cancel()
        if active:
            await asyncio.gather(*active, return_exceptions=True)
        self._active.clear()
        logger.info("Job processor stopped")

    # -- worker loop -------------------------------------------------------

    async def _run_worker(self) -> None:
        """Continuously claim and dispatch jobs, bounded by the semaphore."""
        while self._running:
            # Acquire a slot *before* claiming: the claim flips status to
            # processing, so over-claiming would strand jobs with no worker.
            # acquire() returns holding a permit, or raises (e.g. on cancellation)
            # holding none — so a raise here leaks nothing. The path from here to
            # the try below is synchronous, so the permit is never held across an
            # unguarded suspension point; the finally then releases it on every
            # path that doesn't hand it to a job task.
            await self._semaphore.acquire()
            slot_held = True
            try:
                if not self._running:
                    break
                try:
                    job = await self._claim_next_job()
                except Exception:  # pragma: no cover - defensive: keep the loop alive
                    logger.exception("Failed to claim next job")
                    job = None
                if job is None:
                    # Release before the idle backoff so a freed slot stays usable.
                    self._semaphore.release()
                    slot_held = False
                    await asyncio.sleep(self._poll_interval)
                    continue
                task = asyncio.create_task(self._process_and_release(job))
                self._active.add(task)
                task.add_done_callback(self._active.discard)
                slot_held = False  # ownership of the permit passes to the job task
            finally:
                if slot_held:
                    self._semaphore.release()

    async def _process_and_release(self, job: Job) -> None:
        try:
            await self._process_job(job)
        finally:
            self._semaphore.release()

    # -- job discovery -----------------------------------------------------

    async def _claim_next_job(self) -> Job | None:
        """Atomically claim the oldest queued job, or return None if there are none.

        ``find_one_and_update`` is atomic at the document level, so two workers
        racing for the same job are serialised by MongoDB — exactly one wins.
        """
        collection = database.get_database()[Job.Settings.name]
        doc = await collection.find_one_and_update(
            {"status": JobStatus.QUEUED.value, "job_type": {"$in": list(self._handlers)}},
            {"$set": {"status": JobStatus.PROCESSING.value, "started_at": utcnow()}},
            sort=[("created_at", ASCENDING)],
            return_document=ReturnDocument.AFTER,
        )
        if doc is None:
            return None
        # Re-load through Beanie so the rest of the pipeline works with a typed
        # Job (and its update helpers) rather than a raw BSON dict.
        job = await Job.get(doc["_id"])
        if job is None:  # pragma: no cover - claimed doc deleted out from under us
            logger.error("Claimed job %s vanished before reload; skipping", doc["_id"])
        return job

    async def _requeue_stale_jobs(self) -> None:
        """Reset *stale* ``processing`` jobs back to ``queued`` on startup.

        A job left in ``processing`` longer than ``stale_after`` is orphaned: its
        worker either crashed or was cancelled mid-generation, since a live worker
        fails a job after ``poll_timeout``. Re-queue only those so they are retried
        rather than stranded. Bounding by ``started_at`` keeps this safe when more
        than one API process runs — a job a sibling is actively working (started
        recently) is never reclaimed. (Running a single processor instance is still
        the recommended deployment; this is the safety net.)
        """
        collection = database.get_database()[Job.Settings.name]
        cutoff = utcnow() - timedelta(seconds=self._stale_after)
        result = await collection.update_many(
            {
                "status": JobStatus.PROCESSING.value,
                "job_type": {"$in": list(self._handlers)},
                # ``started_at`` missing/None means a legacy/partial claim — also stale.
                "$or": [{"started_at": {"$lt": cutoff}}, {"started_at": None}],
            },
            {"$set": {"status": JobStatus.QUEUED.value, "started_at": None}},
        )
        if result.modified_count:
            logger.info("Re-queued %d stale processing job(s)", result.modified_count)

    # -- single-job processing --------------------------------------------

    async def _process_job(self, job: Job) -> None:
        """Dispatch one claimed job to its handler, recording success or failure.

        Cancellation (graceful shutdown) is re-raised, leaving the job in
        ``processing`` so the next startup re-queues it. Any other error is
        captured on the job as ``failed`` with its message. The claim query
        filters on registered types, so the handler lookup cannot miss.
        """
        try:
            handler = self._handlers[job.job_type]
            result = await handler(job)
            await self._mark_completed(job, result)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - any failure must land on the job record
            logger.exception("Job %s failed", job.id)
            await self._mark_failed(job, str(exc))

    async def _run_storage_handler(self, storage_handler: Any, job: Job) -> dict[str, Any]:
        """Adapt a ``(job, storage) -> result`` handler (editing/extraction) to the registry."""
        return await storage_handler(job, self._storage_factory())

    async def _run_iterative_handler(self, iterative_handler: Any, job: Job) -> dict[str, Any]:
        """Adapt an iterative handler (US-10.3), injecting storage, the ACE-Step client and the poll loop."""
        return await iterative_handler(
            job,
            storage=self._storage_factory(),
            client=self._client_factory(),
            poll=self._poll_until_complete,
        )

    async def _run_mastering_handler(self, mastering_handler: Any, job: Job) -> dict[str, Any]:
        """Adapt a mastering handler (US-12.2/US-12.3), injecting storage and the orchestrator."""
        if self._mastering_orchestrator_factory is None:
            raise JobProcessingError(
                "Mastering is not configured: this processor has no mastering orchestrator factory"
            )
        orchestrator = self._mastering_orchestrator_factory()
        return await mastering_handler(job, storage=self._storage_factory(), orchestrator=orchestrator)

    async def _handle_generate(self, job: Job) -> dict[str, Any]:
        """Run a generation job — locally via ACE-Step or remotely via RunPod.

        US-11.1 records the routing decision on ``job.compute_target``; US-11.2 acts
        on it here. The two backends share an interface (``submit_task`` /
        ``query_result`` / ``download_audio``) and the normalised result shape, so
        only the client and the poll cadence/timeout differ between them.
        """
        params = dict(job.input_params or {})
        # "remote" is the Job.compute_target literal the routing engine (US-11.1) writes.
        remote = job.compute_target == "remote"
        if remote:
            if self._runpod_client_factory is None:
                raise JobProcessingError("Job routed to remote compute but RunPod is not configured")
            client: AceStepClient | RunPodClient = self._runpod_client_factory()
            poll_interval, timeout, backend = self._runpod_poll_interval, self._runpod_timeout, "RunPod"
        else:
            client = self._client_factory()
            poll_interval, timeout, backend = self._ace_poll_interval, self._poll_timeout, "ACE-Step"

        task_id = await asyncio.to_thread(partial(client.submit_task, **self._build_submit_kwargs(params)))
        result = await self._poll_until_complete(client, task_id, poll_interval=poll_interval, timeout=timeout)
        if result.get("status") == "failed":
            raise JobProcessingError(result.get("error") or f"{backend} generation failed")

        audio_urls = result.get("audio_urls") or []
        if not audio_urls:
            raise JobProcessingError(f"{backend} completed but returned no audio")

        clip_ids = await self._store_clips(job, params, client, audio_urls)
        return {"clip_ids": clip_ids}

    async def _poll_until_complete(
        self,
        client: AceStepClient | RunPodClient,
        task_id: str,
        *,
        poll_interval: float | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Poll query_result until the task reaches a terminal state or times out.

        ``poll_interval``/``timeout`` default to the local ACE-Step cadence so
        existing callers (the iterative handlers) keep their behaviour; the remote
        path passes RunPod's longer cadence/budget.
        """
        interval = poll_interval if poll_interval is not None else self._ace_poll_interval
        budget = timeout if timeout is not None else self._poll_timeout
        start = time.monotonic()
        while True:
            result = await asyncio.to_thread(client.query_result, task_id)
            if result.get("status") in _TERMINAL_STATES:
                return result
            if time.monotonic() - start > budget:
                raise JobProcessingError(f"Timed out after {budget:.0f}s waiting for task {task_id}")
            await asyncio.sleep(interval)

    async def _store_clips(
        self,
        job: Job,
        params: dict[str, Any],
        client: AceStepClient | RunPodClient,
        audio_urls: list[str],
    ) -> list[str]:
        """Download each result, store it, and create its Clip record.

        A failure partway through (download/upload/insert error on a later clip)
        rolls back the clips and files already written, so a job that ends up
        ``failed`` never leaves orphaned ``Clip`` rows or storage objects behind.
        """
        storage = self._storage_factory()
        fmt = params.get("format") or "wav"
        clip_ids: list[str] = []
        stored: list[tuple[Clip, str]] = []
        try:
            for url in audio_urls:
                data = await asyncio.to_thread(client.download_audio, url)
                clip_id = PydanticObjectId()
                path = f"{job.user_id}/{job.workspace_id}/clips/{clip_id}.{fmt}"
                await asyncio.to_thread(storage.upload, path, data)
                clip = self._build_clip(job, params, clip_id, path, fmt)
                await clip.insert()
                stored.append((clip, path))
                clip_ids.append(str(clip_id))
        except Exception:
            await self._rollback_clips(storage, stored)
            raise
        return clip_ids

    @staticmethod
    async def _rollback_clips(storage: StorageBackend, stored: list[tuple[Clip, str]]) -> None:
        """Best-effort cleanup of clips/files written before a mid-batch failure."""
        for clip, path in stored:
            try:
                await clip.delete()
            except Exception:  # pragma: no cover - cleanup is best-effort
                logger.exception("Failed to delete orphaned clip %s during rollback", clip.id)
            try:
                await asyncio.to_thread(storage.delete, path)
            except Exception:  # pragma: no cover - cleanup is best-effort
                logger.exception("Failed to delete orphaned storage object %s during rollback", path)

    @staticmethod
    def _build_submit_kwargs(params: dict[str, Any]) -> dict[str, Any]:
        """Map persisted job params onto ``AceStepClient.submit_task`` kwargs."""
        kwargs: dict[str, Any] = {"prompt": params.get("prompt", "")}
        if params.get("duration") is not None:
            kwargs["audio_duration"] = params["duration"]
        if params.get("format") is not None:
            kwargs["format"] = params["format"]
        for field in _SUBMIT_FIELDS:
            if field in params:
                kwargs[field] = params[field]
        return kwargs

    @staticmethod
    def _build_clip(
        job: Job,
        params: dict[str, Any],
        clip_id: PydanticObjectId,
        path: str,
        fmt: str,
    ) -> Clip:
        """Construct a Clip from a job's params (id pre-assigned to match the path)."""
        # ``duration`` is the *requested* duration from the job params (ACE-Step
        # honours it); we store it as the clip's duration metadata.
        # bpm may be the literal "auto"; Clip.bpm is an int, so persist only ints.
        bpm = params.get("bpm")
        style = params.get("style")
        return Clip(
            id=clip_id,
            user_id=job.user_id,
            workspace_id=job.workspace_id,
            file_path=path,
            format=fmt,
            duration=params.get("duration"),
            bpm=bpm if isinstance(bpm, int) else None,
            key=params.get("key"),
            style_tags=[style] if isinstance(style, str) and style else [],
            lyrics=params.get("lyrics"),
            vocal_language=params.get("vocal_language"),
            model=params.get("model"),
            seed=params.get("seed"),
            inference_steps=params.get("inference_steps"),
            generation_mode=params.get("mode"),
        )

    # -- status transitions ------------------------------------------------

    async def _mark_completed(self, job: Job, result: dict[str, Any]) -> None:
        await job.set(
            {
                Job.status: JobStatus.COMPLETED,
                Job.result: result,
                Job.completed_at: utcnow(),
            }
        )

    async def _mark_failed(self, job: Job, error: str) -> None:
        try:
            await job.set(
                {
                    Job.status: JobStatus.FAILED,
                    Job.error: error,
                    Job.completed_at: utcnow(),
                }
            )
        except Exception:  # pragma: no cover - last-ditch; never crash the worker
            logger.exception("Failed to record failure for job %s", job.id)
