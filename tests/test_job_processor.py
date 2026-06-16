"""Tests for the async job processor (US-9.2).

Pure helper tests run in CI (no services). The lifecycle/claim/shutdown tests are
marked ``integration``: they run against a real local MongoDB (``mongo_db``) and a
real :class:`LocalStorage` backend, with only the external, account-gated ACE-Step
HTTP client replaced by an in-process double (mirrors ``tests/test_generate.py``).
"""

import asyncio
import os
import threading
import time

import pytest
from beanie import PydanticObjectId

from acemusic.api.models import Clip, Job, JobStatus
from acemusic.api.tasks.processor import JobProcessor
from acemusic.storage import LocalStorage

# ---------------------------------------------------------------------------
# In-process ACE-Step double + helpers
# ---------------------------------------------------------------------------


class _ConcurrencyTracker:
    """Records the peak number of overlapping ``query_result`` calls (real threads)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.current = 0
        self.max = 0

    def enter(self) -> None:
        with self._lock:
            self.current += 1
            self.max = max(self.max, self.current)
        # Hold the slot briefly so genuine overlap is observable.
        time.sleep(0.05)

    def exit(self) -> None:
        with self._lock:
            self.current -= 1


class _FakeAceClient:
    """Synchronous ACE-Step stand-in driven by canned results."""

    def __init__(
        self,
        *,
        audio_urls=None,
        audio: bytes = b"FAKE-WAV-BYTES",
        status: str = "completed",
        error: str | None = None,
        pending_forever: bool = False,
        track: _ConcurrencyTracker | None = None,
        fail_download_after: int | None = None,
    ) -> None:
        self._audio_urls = ["http://ace/a.wav", "http://ace/b.wav"] if audio_urls is None else audio_urls
        self._audio = audio
        self._status = status
        self._error = error
        self._pending_forever = pending_forever
        self._track = track
        self._fail_download_after = fail_download_after
        self._downloads = 0
        self.submitted: list[dict] = []

    def submit_task(self, **kwargs) -> str:
        self.submitted.append(kwargs)
        return "task-123"

    def query_result(self, task_id: str, timeout: float = 10.0) -> dict:
        if self._track is not None:
            self._track.enter()
        try:
            if self._pending_forever:
                time.sleep(0.02)
                return {"status": "pending", "audio_urls": [], "error": None}
            if self._status == "failed":
                return {"status": "failed", "audio_urls": [], "error": self._error or "boom"}
            return {"status": "completed", "audio_urls": list(self._audio_urls), "error": None}
        finally:
            if self._track is not None:
                self._track.exit()

    def download_audio(self, url: str, timeout: float = 120.0) -> bytes:
        self._downloads += 1
        if self._fail_download_after is not None and self._downloads > self._fail_download_after:
            raise RuntimeError("download boom")
        return self._audio


class _FakeRunPodClient:
    """Synchronous RunPod stand-in mirroring the AceStep consumer interface."""

    def __init__(
        self,
        *,
        audio_urls=None,
        audio: bytes = b"RUNPOD-WAV-BYTES",
        status: str = "completed",
        error: str | None = None,
        pending_forever: bool = False,
    ) -> None:
        self._audio_urls = ["http://runpod/a.wav"] if audio_urls is None else audio_urls
        self._audio = audio
        self._status = status
        self._error = error
        self._pending_forever = pending_forever
        self.submitted: list[dict] = []

    def submit_task(self, **kwargs) -> str:
        self.submitted.append(kwargs)
        return "runpod-job-1"

    def query_result(self, task_id: str, timeout: float = 10.0) -> dict:
        if self._pending_forever:
            time.sleep(0.01)
            return {"status": "pending", "audio_urls": [], "error": None}
        if self._status == "failed":
            return {"status": "failed", "audio_urls": [], "error": self._error or "remote boom"}
        return {"status": "completed", "audio_urls": list(self._audio_urls), "error": None}

    def download_audio(self, url: str, timeout: float = 120.0) -> bytes:
        return self._audio


class _ExplodingClient:
    """A client whose every call fails — used to prove the *other* backend ran."""

    def submit_task(self, **kwargs) -> str:  # pragma: no cover - must never be called
        raise AssertionError("wrong backend: local ACE-Step client was used for a remote job")


async def _enqueue(
    input_params: dict | None = None, *, job_type: str = "generate", compute_target: str | None = None
) -> Job:
    job = Job(
        user_id=PydanticObjectId(),
        workspace_id=PydanticObjectId(),
        job_type=job_type,
        compute_target=compute_target,
        status=JobStatus.QUEUED,
        input_params=input_params or {"prompt": "a calm piano ballad", "format": "wav"},
    )
    await job.insert()
    return job


async def _wait_until(predicate, *, timeout: float = 5.0, interval: float = 0.02) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if await predicate():
            return True
        await asyncio.sleep(interval)
    return False


def _make_processor(
    fake,
    storage,
    *,
    concurrency: int = 2,
    stale_after: float = 0.0,
    handlers=None,
    runpod=None,
    runpod_timeout: float = 5.0,
) -> JobProcessor:
    # stale_after=0.0: any `processing` job is treated as immediately orphaned, so
    # the requeue-on-startup test is deterministic (production uses a real window).
    return JobProcessor(
        concurrency=concurrency,
        poll_interval=0.01,
        poll_timeout=5.0,
        ace_poll_interval=0.01,
        stale_after=stale_after,
        client_factory=lambda: fake,
        runpod_client_factory=(lambda: runpod) if runpod is not None else None,
        runpod_poll_interval=0.01,
        runpod_timeout=runpod_timeout,
        storage_factory=lambda: storage,
        handlers=handlers,
    )


# ---------------------------------------------------------------------------
# Pure helpers (no services) — run in CI
# ---------------------------------------------------------------------------


class TestBuildSubmitKwargs:
    def test_maps_known_fields(self) -> None:
        params = {
            "prompt": "epic orchestral",
            "duration": 90.0,
            "format": "flac",
            "style": "cinematic",
            "bpm": 120,
            "mode": "song",
            "weirdness": 70,
            # An API-only field the client does not accept must be dropped.
            "weirdness_unknown": "ignored",
        }
        kwargs = JobProcessor._build_submit_kwargs(params)
        assert kwargs["prompt"] == "epic orchestral"
        assert kwargs["audio_duration"] == 90.0
        assert kwargs["format"] == "flac"
        assert kwargs["style"] == "cinematic"
        assert kwargs["bpm"] == 120
        assert kwargs["mode"] == "song"
        assert kwargs["weirdness"] == 70
        assert "weirdness_unknown" not in kwargs
        assert "duration" not in kwargs  # renamed to audio_duration

    def test_minimal_params(self) -> None:
        kwargs = JobProcessor._build_submit_kwargs({"prompt": "lofi"})
        assert kwargs == {"prompt": "lofi"}


# ---------------------------------------------------------------------------
# Lifecycle / claim / shutdown — integration (real MongoDB + LocalStorage)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestLifecycle:
    async def test_queued_job_runs_to_completed(self, mongo_db, tmp_path) -> None:
        storage = LocalStorage(root_dir=tmp_path)
        fake = _FakeAceClient(audio_urls=["http://ace/a.wav", "http://ace/b.wav"])
        proc = _make_processor(fake, storage)
        job = await _enqueue()

        await proc.start()
        try:
            done = await _wait_until(lambda: _is_status(job.id, JobStatus.COMPLETED))
        finally:
            await proc.stop()

        assert done, "job did not reach completed"
        refreshed = await Job.get(job.id)
        assert refreshed.status == JobStatus.COMPLETED
        assert refreshed.started_at is not None
        assert refreshed.completed_at is not None
        clip_ids = refreshed.result["clip_ids"]
        assert len(clip_ids) == 2

        clips = await Clip.find(Clip.user_id == job.user_id).to_list()
        assert len(clips) == 2
        for clip in clips:
            assert storage.download(clip.file_path) == b"FAKE-WAV-BYTES"
            assert clip.workspace_id == job.workspace_id

    async def test_clip_metadata_persisted_from_params(self, mongo_db, tmp_path) -> None:
        storage = LocalStorage(root_dir=tmp_path)
        fake = _FakeAceClient(audio_urls=["http://ace/only.wav"])
        proc = _make_processor(fake, storage, concurrency=1)
        job = await _enqueue(
            {
                "prompt": "house loop",
                "format": "wav",
                "style": "deep house",
                "bpm": 124,
                "key": "A minor",
                "model": "turbo",
                "seed": 7,
                "mode": "sound",
            }
        )

        await proc.start()
        try:
            await _wait_until(lambda: _is_status(job.id, JobStatus.COMPLETED))
        finally:
            await proc.stop()

        clip = (await Clip.find(Clip.user_id == job.user_id).to_list())[0]
        assert clip.format == "wav"
        assert clip.style_tags == ["deep house"]
        assert clip.bpm == 124
        assert clip.key == "A minor"
        assert clip.model == "turbo"
        assert clip.seed == 7
        assert clip.generation_mode == "sound"

    async def test_bpm_auto_is_not_persisted_as_int(self, mongo_db, tmp_path) -> None:
        storage = LocalStorage(root_dir=tmp_path)
        fake = _FakeAceClient(audio_urls=["http://ace/only.wav"])
        proc = _make_processor(fake, storage, concurrency=1)
        job = await _enqueue({"prompt": "x", "format": "wav", "bpm": "auto"})

        await proc.start()
        try:
            await _wait_until(lambda: _is_status(job.id, JobStatus.COMPLETED))
        finally:
            await proc.stop()

        clip = (await Clip.find(Clip.user_id == job.user_id).to_list())[0]
        assert clip.bpm is None

    async def test_failed_generation_records_error(self, mongo_db, tmp_path) -> None:
        storage = LocalStorage(root_dir=tmp_path)
        fake = _FakeAceClient(status="failed", error="model overloaded")
        proc = _make_processor(fake, storage)
        job = await _enqueue()

        await proc.start()
        try:
            await _wait_until(lambda: _is_status(job.id, JobStatus.FAILED))
        finally:
            await proc.stop()

        refreshed = await Job.get(job.id)
        assert refreshed.status == JobStatus.FAILED
        assert refreshed.error == "model overloaded"
        assert await Clip.find(Clip.user_id == job.user_id).to_list() == []

    async def test_completed_without_audio_marks_failed(self, mongo_db, tmp_path) -> None:
        storage = LocalStorage(root_dir=tmp_path)
        fake = _FakeAceClient(audio_urls=[])  # completed but empty
        proc = _make_processor(fake, storage)
        job = await _enqueue()

        await proc.start()
        try:
            await _wait_until(lambda: _is_status(job.id, JobStatus.FAILED))
        finally:
            await proc.stop()

        refreshed = await Job.get(job.id)
        assert refreshed.status == JobStatus.FAILED
        assert "no audio" in (refreshed.error or "").lower()

    async def test_partial_failure_rolls_back_stored_clips(self, mongo_db, tmp_path) -> None:
        # Second download fails after the first clip is already stored — the job
        # fails and the first clip's record AND file must be rolled back.
        storage = LocalStorage(root_dir=tmp_path)
        fake = _FakeAceClient(audio_urls=["http://ace/a.wav", "http://ace/b.wav"], fail_download_after=1)
        proc = _make_processor(fake, storage)
        job = await _enqueue()

        await proc.start()
        try:
            await _wait_until(lambda: _is_status(job.id, JobStatus.FAILED))
        finally:
            await proc.stop()

        refreshed = await Job.get(job.id)
        assert refreshed.status == JobStatus.FAILED
        assert await Clip.count() == 0, "orphaned clip record not rolled back"
        leftover = [f for _root, _dirs, files in os.walk(tmp_path) for f in files]
        assert leftover == [], "orphaned storage file not rolled back"


@pytest.mark.integration
class TestRemoteRunPod:
    """Generation jobs routed to remote (RunPod) compute (US-11.2)."""

    async def test_remote_job_runs_via_runpod_and_stores_clips(self, mongo_db, tmp_path) -> None:
        storage = LocalStorage(root_dir=tmp_path)
        remote = _FakeRunPodClient(audio_urls=["http://runpod/a.wav", "http://runpod/b.wav"])
        proc = _make_processor(_ExplodingClient(), storage, runpod=remote)
        job = await _enqueue(compute_target="remote")

        await proc.start()
        try:
            done = await _wait_until(lambda: _is_status(job.id, JobStatus.COMPLETED))
        finally:
            await proc.stop()

        assert done, "remote job did not reach completed"
        # The remote client ran (the local _ExplodingClient would have failed the job).
        assert remote.submitted, "RunPod client was not used for the remote job"
        refreshed = await Job.get(job.id)
        assert refreshed.status == JobStatus.COMPLETED
        assert len(refreshed.result["clip_ids"]) == 2
        clips = await Clip.find(Clip.user_id == job.user_id).to_list()
        assert len(clips) == 2
        for clip in clips:
            assert storage.download(clip.file_path) == b"RUNPOD-WAV-BYTES"

    async def test_remote_failure_surfaces_error(self, mongo_db, tmp_path) -> None:
        storage = LocalStorage(root_dir=tmp_path)
        remote = _FakeRunPodClient(status="failed", error="GPU OOM on worker")
        proc = _make_processor(_ExplodingClient(), storage, runpod=remote)
        job = await _enqueue(compute_target="remote")

        await proc.start()
        try:
            await _wait_until(lambda: _is_status(job.id, JobStatus.FAILED))
        finally:
            await proc.stop()

        refreshed = await Job.get(job.id)
        assert refreshed.status == JobStatus.FAILED
        assert refreshed.error == "GPU OOM on worker"

    async def test_remote_timeout_surfaces_error(self, mongo_db, tmp_path) -> None:
        storage = LocalStorage(root_dir=tmp_path)
        remote = _FakeRunPodClient(pending_forever=True)
        # Tiny runpod_timeout so the poll budget is exhausted quickly.
        proc = _make_processor(_ExplodingClient(), storage, runpod=remote, runpod_timeout=0.05)
        job = await _enqueue(compute_target="remote")

        await proc.start()
        try:
            await _wait_until(lambda: _is_status(job.id, JobStatus.FAILED))
        finally:
            await proc.stop()

        refreshed = await Job.get(job.id)
        assert refreshed.status == JobStatus.FAILED
        assert "timed out" in (refreshed.error or "").lower()

    async def test_remote_job_without_factory_fails_clearly(self, mongo_db, tmp_path) -> None:
        storage = LocalStorage(root_dir=tmp_path)
        # runpod=None → no factory, but a job is still routed remote.
        proc = _make_processor(_ExplodingClient(), storage, runpod=None)
        job = await _enqueue(compute_target="remote")

        await proc.start()
        try:
            await _wait_until(lambda: _is_status(job.id, JobStatus.FAILED))
        finally:
            await proc.stop()

        refreshed = await Job.get(job.id)
        assert refreshed.status == JobStatus.FAILED
        assert "runpod is not configured" in (refreshed.error or "").lower()

    async def test_local_job_still_uses_ace_step(self, mongo_db, tmp_path) -> None:
        # A job with compute_target="local" must ignore the configured RunPod client.
        storage = LocalStorage(root_dir=tmp_path)
        local = _FakeAceClient(audio_urls=["http://ace/a.wav"])
        remote = _FakeRunPodClient()
        proc = _make_processor(local, storage, runpod=remote)
        job = await _enqueue(compute_target="local")

        await proc.start()
        try:
            await _wait_until(lambda: _is_status(job.id, JobStatus.COMPLETED))
        finally:
            await proc.stop()

        assert local.submitted, "local ACE-Step client was not used for the local job"
        assert remote.submitted == [], "RunPod client must not run a local job"

    async def test_two_concurrent_jobs_complete_without_corruption(self, mongo_db, tmp_path) -> None:
        storage = LocalStorage(root_dir=tmp_path)
        tracker = _ConcurrencyTracker()
        fake = _FakeAceClient(audio_urls=["http://ace/a.wav", "http://ace/b.wav"], track=tracker)
        proc = _make_processor(fake, storage, concurrency=2)
        job_a = await _enqueue({"prompt": "first", "format": "wav"})
        job_b = await _enqueue({"prompt": "second", "format": "wav"})

        await proc.start()
        try:
            done = await _wait_until(
                lambda: _all_status([job_a.id, job_b.id], JobStatus.COMPLETED),
                timeout=8.0,
            )
        finally:
            await proc.stop()

        assert done, "both jobs did not complete"
        assert tracker.max >= 2, "jobs did not actually run concurrently"

        refreshed_a = await Job.get(job_a.id)
        refreshed_b = await Job.get(job_b.id)
        ids_a = set(refreshed_a.result["clip_ids"])
        ids_b = set(refreshed_b.result["clip_ids"])
        assert len(ids_a) == 2 and len(ids_b) == 2
        assert ids_a.isdisjoint(ids_b), "clip ids leaked between jobs"
        assert await Clip.count() == 4


@pytest.mark.integration
class TestClaim:
    async def test_claim_returns_none_when_empty(self, mongo_db, tmp_path) -> None:
        proc = _make_processor(_FakeAceClient(), LocalStorage(root_dir=tmp_path))
        assert await proc._claim_next_job() is None

    async def test_claim_is_exclusive(self, mongo_db, tmp_path) -> None:
        proc = _make_processor(_FakeAceClient(), LocalStorage(root_dir=tmp_path))
        job = await _enqueue()

        # Two workers race for the same single queued job; the atomic
        # find_one_and_update must hand it to exactly one of them.
        first, second = await asyncio.gather(proc._claim_next_job(), proc._claim_next_job())

        claimed = [r for r in (first, second) if r is not None]
        assert len(claimed) == 1, "the same job was claimed by two workers"
        assert str(claimed[0].id) == str(job.id)
        assert claimed[0].status == JobStatus.PROCESSING


@pytest.mark.integration
class TestShutdownAndRequeue:
    async def test_stop_cancels_in_flight_then_restart_requeues(self, mongo_db, tmp_path) -> None:
        storage = LocalStorage(root_dir=tmp_path)
        # A job that never finishes: it sits in `processing` until the worker stops.
        stuck = _FakeAceClient(pending_forever=True)
        proc = _make_processor(stuck, storage, concurrency=1)
        job = await _enqueue()

        await proc.start()
        claimed = await _wait_until(lambda: _is_status(job.id, JobStatus.PROCESSING))
        await proc.stop()
        assert claimed, "job was never claimed"

        # Shutdown left it processing (not failed): it is re-runnable.
        mid = await Job.get(job.id)
        assert mid.status == JobStatus.PROCESSING

        # A fresh processor re-queues the stale job on startup and finishes it.
        good = _FakeAceClient(audio_urls=["http://ace/a.wav"])
        proc2 = _make_processor(good, storage, concurrency=1)
        await proc2.start()
        try:
            done = await _wait_until(lambda: _is_status(job.id, JobStatus.COMPLETED))
        finally:
            await proc2.stop()

        assert done, "stale job was not re-queued and completed"
        final = await Job.get(job.id)
        assert final.status == JobStatus.COMPLETED
        assert len(final.result["clip_ids"]) == 1

    async def test_recently_started_job_is_not_requeued(self, mongo_db, tmp_path) -> None:
        # A job a live sibling process started moments ago must survive the startup
        # sweep — only jobs older than stale_after are reclaimed (multi-worker safety).
        from acemusic.api.models.common import utcnow

        proc = _make_processor(_FakeAceClient(), LocalStorage(root_dir=tmp_path), stale_after=3600.0)
        job = Job(
            user_id=PydanticObjectId(),
            workspace_id=PydanticObjectId(),
            job_type="generate",
            status=JobStatus.PROCESSING,
            started_at=utcnow(),
            input_params={"prompt": "x"},
        )
        await job.insert()

        await proc._requeue_stale_jobs()

        refreshed = await Job.get(job.id)
        assert refreshed.status == JobStatus.PROCESSING

    async def test_stale_processing_job_is_requeued(self, mongo_db, tmp_path) -> None:
        from datetime import timedelta

        from acemusic.api.models.common import utcnow

        proc = _make_processor(_FakeAceClient(), LocalStorage(root_dir=tmp_path), stale_after=60.0)
        job = Job(
            user_id=PydanticObjectId(),
            workspace_id=PydanticObjectId(),
            job_type="generate",
            status=JobStatus.PROCESSING,
            started_at=utcnow() - timedelta(seconds=120),
            input_params={"prompt": "x"},
        )
        await job.insert()

        await proc._requeue_stale_jobs()

        refreshed = await Job.get(job.id)
        assert refreshed.status == JobStatus.QUEUED
        assert refreshed.started_at is None


# ---------------------------------------------------------------------------
# Handler registry — dispatch by job_type (US-10.1, Step 2)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestHandlerRegistry:
    async def test_custom_handler_processes_its_job_type(self, mongo_db, tmp_path) -> None:
        seen: list[str] = []

        async def echo_handler(job: Job) -> dict:
            seen.append(job.job_type)
            return {"echo": job.input_params["value"]}

        proc = _make_processor(
            _FakeAceClient(),
            LocalStorage(root_dir=tmp_path),
            handlers={"echo": echo_handler},
        )
        job = await _enqueue({"value": 42}, job_type="echo")

        await proc.start()
        try:
            done = await _wait_until(lambda: _is_status(job.id, JobStatus.COMPLETED))
        finally:
            await proc.stop()

        assert done, "custom-typed job did not complete"
        refreshed = await Job.get(job.id)
        assert refreshed.result == {"echo": 42}
        assert seen == ["echo"]

    async def test_generate_jobs_still_route_to_generate_handler(self, mongo_db, tmp_path) -> None:
        # The registry must not change generate behaviour: a generate job and a
        # custom-typed job each reach their own handler.
        async def noop_handler(job: Job) -> dict:
            return {"handled": True}

        storage = LocalStorage(root_dir=tmp_path)
        fake = _FakeAceClient(audio_urls=["http://ace/a.wav"])
        proc = _make_processor(fake, storage, handlers={"noop": noop_handler})
        gen_job = await _enqueue()
        noop_job = await _enqueue({"x": 1}, job_type="noop")

        await proc.start()
        try:
            done = await _wait_until(lambda: _all_status([gen_job.id, noop_job.id], JobStatus.COMPLETED))
        finally:
            await proc.stop()

        assert done, "jobs did not complete"
        refreshed_gen = await Job.get(gen_job.id)
        assert refreshed_gen.result["clip_ids"], "generate handler did not produce clips"
        refreshed_noop = await Job.get(noop_job.id)
        assert refreshed_noop.result == {"handled": True}

    async def test_unregistered_job_type_is_never_claimed(self, mongo_db, tmp_path) -> None:
        proc = _make_processor(_FakeAceClient(), LocalStorage(root_dir=tmp_path))
        job = await _enqueue({"x": 1}, job_type="mystery")

        await proc.start()
        try:
            claimed = await _wait_until(lambda: _is_status(job.id, JobStatus.PROCESSING), timeout=0.3)
        finally:
            await proc.stop()

        assert not claimed, "a job with no registered handler was claimed"
        refreshed = await Job.get(job.id)
        assert refreshed.status == JobStatus.QUEUED

    async def test_handler_exception_marks_job_failed(self, mongo_db, tmp_path) -> None:
        async def boom_handler(job: Job) -> dict:
            raise RuntimeError("edit boom")

        proc = _make_processor(
            _FakeAceClient(),
            LocalStorage(root_dir=tmp_path),
            handlers={"boom": boom_handler},
        )
        job = await _enqueue({"x": 1}, job_type="boom")

        await proc.start()
        try:
            done = await _wait_until(lambda: _is_status(job.id, JobStatus.FAILED))
        finally:
            await proc.stop()

        assert done, "failing handler did not mark the job failed"
        refreshed = await Job.get(job.id)
        assert refreshed.error == "edit boom"

    async def test_stale_requeue_covers_all_registered_types(self, mongo_db, tmp_path) -> None:
        from acemusic.api.models.common import utcnow

        async def noop_handler(job: Job) -> dict:  # pragma: no cover - never runs
            return {}

        proc = _make_processor(
            _FakeAceClient(),
            LocalStorage(root_dir=tmp_path),
            stale_after=0.0,
            handlers={"noop": noop_handler},
        )
        stale = Job(
            user_id=PydanticObjectId(),
            workspace_id=PydanticObjectId(),
            job_type="noop",
            status=JobStatus.PROCESSING,
            started_at=utcnow(),
            input_params={"x": 1},
        )
        await stale.insert()
        unknown = Job(
            user_id=PydanticObjectId(),
            workspace_id=PydanticObjectId(),
            job_type="mystery",
            status=JobStatus.PROCESSING,
            started_at=utcnow(),
            input_params={"x": 1},
        )
        await unknown.insert()

        await proc._requeue_stale_jobs()

        assert (await Job.get(stale.id)).status == JobStatus.QUEUED
        # A type this processor cannot run is left alone for whoever owns it.
        assert (await Job.get(unknown.id)).status == JobStatus.PROCESSING


# ---------------------------------------------------------------------------
# Status predicates (used by _wait_until)
# ---------------------------------------------------------------------------


async def _is_status(job_id, expected: JobStatus) -> bool:
    job = await Job.get(job_id)
    return job is not None and job.status == expected


async def _all_status(job_ids, expected: JobStatus) -> bool:
    for job_id in job_ids:
        if not await _is_status(job_id, expected):
            return False
    return True
