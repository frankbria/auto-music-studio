"""Tests for the editing job handlers (US-10.1, Step 3).

Integration tests drive the real :class:`JobProcessor` against a local MongoDB
and :class:`LocalStorage`, with real sine-wave WAVs (``write_tone``) — no
ACE-Step involvement, so they run in CI. They prove the issue's acceptance
criteria at the worker level: crop duration = end − start, speed ×2 halves the
duration, remaster lands on the target LUFS, and originals are never touched.
"""

import asyncio
import io
import os
import time

import pytest
import soundfile as sf
from beanie import PydanticObjectId

from acemusic.api.models import Clip, Job, JobStatus
from acemusic.api.tasks.processor import JobProcessor
from acemusic.audio import measure_lufs
from acemusic.storage import LocalStorage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_processor(storage) -> JobProcessor:
    # client_factory would only run for "generate" jobs, which these tests never
    # enqueue; a crashing factory proves editing never touches ACE-Step.
    def _no_client():  # pragma: no cover - would only run on a routing bug
        raise AssertionError("editing jobs must not build an ACE-Step client")

    return JobProcessor(
        concurrency=1,
        poll_interval=0.01,
        poll_timeout=30.0,
        ace_poll_interval=0.01,
        stale_after=3600.0,
        client_factory=_no_client,
        storage_factory=lambda: storage,
    )


@pytest.fixture
def storage(tmp_path) -> LocalStorage:
    root = tmp_path / "storage"
    root.mkdir()
    return LocalStorage(root_dir=root)


async def _insert_source_clip(
    storage: LocalStorage,
    tmp_path,
    write_tone,
    *,
    duration_s: float = 2.0,
    bpm: int | None = None,
    key: str | None = None,
    amplitude: float = 0.3,
) -> Clip:
    """Write a real tone, upload it to storage and insert its Clip document."""
    user_id = PydanticObjectId()
    workspace_id = PydanticObjectId()
    clip_id = PydanticObjectId()

    scratch = tmp_path / "scratch"
    scratch.mkdir(exist_ok=True)
    tone_path = scratch / f"{clip_id}.wav"
    write_tone(tone_path, duration_s=duration_s, amplitude=amplitude)

    file_path = f"{user_id}/{workspace_id}/clips/{clip_id}.wav"
    storage.upload(file_path, tone_path.read_bytes())
    clip = Clip(
        id=clip_id,
        user_id=user_id,
        workspace_id=workspace_id,
        file_path=file_path,
        format="wav",
        duration=duration_s,
        bpm=bpm,
        key=key,
    )
    await clip.insert()
    return clip


async def _enqueue_edit(source: Clip, job_type: str, params: dict) -> Job:
    job = Job(
        user_id=source.user_id,
        workspace_id=source.workspace_id,
        job_type=job_type,
        status=JobStatus.QUEUED,
        input_params={"clip_id": str(source.id), **params},
    )
    await job.insert()
    return job


async def _run_to_terminal(storage: LocalStorage, job: Job, *, timeout: float = 30.0) -> Job:
    """Start a processor, wait until ``job`` reaches a terminal state, stop it."""
    proc = _make_processor(storage)
    await proc.start()
    try:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            refreshed = await Job.get(job.id)
            if refreshed.status in (JobStatus.COMPLETED, JobStatus.FAILED):
                return refreshed
            await asyncio.sleep(0.02)
    finally:
        await proc.stop()
    pytest.fail(f"job {job.id} did not reach a terminal state within {timeout}s")


def _audio_duration_seconds(data: bytes) -> float:
    samples, sample_rate = sf.read(io.BytesIO(data))
    return len(samples) / sample_rate


async def _result_clip(job: Job) -> Clip:
    clip_ids = job.result["clip_ids"]
    assert len(clip_ids) == 1
    clip = await Clip.get(PydanticObjectId(clip_ids[0]))
    assert clip is not None
    return clip


def _storage_files(storage: LocalStorage) -> set[str]:
    return {
        os.path.relpath(os.path.join(root, name), storage.root_dir)
        for root, _dirs, files in os.walk(storage.root_dir)
        for name in files
    }


# ---------------------------------------------------------------------------
# Handlers are registered by default
# ---------------------------------------------------------------------------


class TestDefaultRegistry:
    def test_editing_job_types_are_registered(self, tmp_path) -> None:
        proc = JobProcessor(storage_factory=lambda: LocalStorage(root_dir=tmp_path))
        assert {"generate", "crop", "speed", "remaster"} <= set(proc._handlers)


# ---------------------------------------------------------------------------
# Crop
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCropJob:
    async def test_crop_creates_clip_with_duration_end_minus_start(
        self, mongo_db, storage, tmp_path, write_tone
    ) -> None:
        source = await _insert_source_clip(storage, tmp_path, write_tone, duration_s=2.0, bpm=120, key="C major")
        original_bytes = storage.download(source.file_path)
        # Snapshot via a DB round-trip so datetime precision matches the later read.
        original_doc = (await Clip.get(source.id)).model_dump()

        job = await _enqueue_edit(source, "crop", {"start_ms": 500, "end_ms": 1500, "fade_in_ms": 0, "fade_out_ms": 0})
        finished = await _run_to_terminal(storage, job)

        assert finished.status == JobStatus.COMPLETED
        new_clip = await _result_clip(finished)
        assert new_clip.duration == pytest.approx(1.0)
        # The stored audio really is one second long, not just the metadata.
        assert _audio_duration_seconds(storage.download(new_clip.file_path)) == pytest.approx(1.0, abs=0.05)

        # Lineage and inherited metadata.
        assert new_clip.parent_clip_ids == [source.id]
        assert new_clip.generation_mode == "crop"
        assert new_clip.user_id == source.user_id
        assert new_clip.workspace_id == source.workspace_id
        assert new_clip.key == "C major"
        assert new_clip.format == "wav"
        assert new_clip.bpm == 120
        assert new_clip.file_path == f"{source.user_id}/{source.workspace_id}/clips/{new_clip.id}.wav"

        # The original is untouched: stored bytes and document both unchanged.
        assert storage.download(source.file_path) == original_bytes
        assert (await Clip.get(source.id)).model_dump() == original_doc

    async def test_crop_applies_fades_without_changing_duration(self, mongo_db, storage, tmp_path, write_tone) -> None:
        source = await _insert_source_clip(storage, tmp_path, write_tone, duration_s=2.0)
        job = await _enqueue_edit(
            source, "crop", {"start_ms": 0, "end_ms": 1000, "fade_in_ms": 100, "fade_out_ms": 100}
        )
        finished = await _run_to_terminal(storage, job)

        assert finished.status == JobStatus.COMPLETED
        new_clip = await _result_clip(finished)
        data = storage.download(new_clip.file_path)
        assert _audio_duration_seconds(data) == pytest.approx(1.0, abs=0.05)
        # Fade-in tames the first samples relative to the (constant-amplitude) middle.
        samples, _sr = sf.read(io.BytesIO(data))
        head = abs(samples[: len(samples) // 100]).max()
        middle = abs(samples[len(samples) // 2 :]).max()
        assert head < middle


# ---------------------------------------------------------------------------
# Speed
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSpeedJob:
    async def test_multiplier_two_halves_duration_and_scales_bpm(self, mongo_db, storage, tmp_path, write_tone) -> None:
        source = await _insert_source_clip(storage, tmp_path, write_tone, duration_s=2.0, bpm=100, key="A minor")
        original_bytes = storage.download(source.file_path)

        job = await _enqueue_edit(source, "speed", {"multiplier": 2.0, "preserve_pitch": True})
        finished = await _run_to_terminal(storage, job)

        assert finished.status == JobStatus.COMPLETED
        new_clip = await _result_clip(finished)
        assert new_clip.duration == pytest.approx(1.0)
        assert _audio_duration_seconds(storage.download(new_clip.file_path)) == pytest.approx(1.0, abs=0.1)
        assert new_clip.bpm == 200
        assert new_clip.key == "A minor"
        assert new_clip.parent_clip_ids == [source.id]
        assert new_clip.generation_mode == "speed"

        assert storage.download(source.file_path) == original_bytes

    async def test_bpm_stays_unset_when_source_has_none(self, mongo_db, storage, tmp_path, write_tone) -> None:
        source = await _insert_source_clip(storage, tmp_path, write_tone, duration_s=2.0, bpm=None)
        job = await _enqueue_edit(source, "speed", {"multiplier": 1.5, "preserve_pitch": True})
        finished = await _run_to_terminal(storage, job)

        assert finished.status == JobStatus.COMPLETED
        new_clip = await _result_clip(finished)
        assert new_clip.bpm is None
        assert new_clip.duration == pytest.approx(2.0 / 1.5)


# ---------------------------------------------------------------------------
# Remaster
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRemasterJob:
    async def test_remaster_hits_target_lufs(self, mongo_db, storage, tmp_path, write_tone) -> None:
        # A quiet source (~-29 LUFS) so the normalisation has real work to do.
        source = await _insert_source_clip(
            storage, tmp_path, write_tone, duration_s=3.0, bpm=90, key="D major", amplitude=0.05
        )
        original_bytes = storage.download(source.file_path)

        job = await _enqueue_edit(source, "remaster", {"target_lufs": -14.0})
        finished = await _run_to_terminal(storage, job)

        assert finished.status == JobStatus.COMPLETED
        new_clip = await _result_clip(finished)

        samples, sample_rate = sf.read(io.BytesIO(storage.download(new_clip.file_path)))
        assert measure_lufs(samples, sample_rate) == pytest.approx(-14.0, abs=1.5)

        # Before/after measurements land on the job result for the client.
        assert finished.result["before_lufs"] == pytest.approx(-29.0, abs=3.0)
        assert finished.result["after_lufs"] == pytest.approx(-14.0, abs=1.5)

        # Remaster inherits duration/bpm/key; lineage points at the source.
        assert new_clip.duration == pytest.approx(3.0)
        assert new_clip.bpm == 90
        assert new_clip.key == "D major"
        assert new_clip.parent_clip_ids == [source.id]
        assert new_clip.generation_mode == "remaster"

        assert storage.download(source.file_path) == original_bytes


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestEditFailures:
    async def test_missing_source_clip_fails_job_without_orphans(self, mongo_db, storage) -> None:
        ghost_id = PydanticObjectId()
        job = Job(
            user_id=PydanticObjectId(),
            workspace_id=PydanticObjectId(),
            job_type="crop",
            status=JobStatus.QUEUED,
            input_params={"clip_id": str(ghost_id), "start_ms": 0, "end_ms": 1000, "fade_in_ms": 0, "fade_out_ms": 0},
        )
        await job.insert()

        finished = await _run_to_terminal(storage, job)

        assert finished.status == JobStatus.FAILED
        assert str(ghost_id) in (finished.error or "")
        assert await Clip.count() == 0
        assert _storage_files(storage) == set()

    async def test_missing_source_audio_fails_job_without_orphans(
        self, mongo_db, storage, tmp_path, write_tone
    ) -> None:
        source = await _insert_source_clip(storage, tmp_path, write_tone, duration_s=2.0)
        storage.delete(source.file_path)  # the record exists but its object is gone

        job = await _enqueue_edit(source, "speed", {"multiplier": 1.5, "preserve_pitch": True})
        finished = await _run_to_terminal(storage, job)

        assert finished.status == JobStatus.FAILED
        assert finished.error
        assert await Clip.count() == 1, "no derived clip may be recorded for a failed edit"
        assert _storage_files(storage) == set(), "no partial output may be left behind"
