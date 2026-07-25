"""Tests for the video job handler (US-22.1).

Exercise ``process_video_job`` directly with a fake provider client (dependency
injection, no monkeypatching) and a local storage backend: it downloads the
source song, submits it, polls the provider (surfacing progress on
``job.progress_detail``), stores the rendered MP4 and records a ``Video``
document. The ``get_video_client`` factory tests run in CI (no DB); the handler
tests need a local MongoDB (Beanie) and are ``integration``.
"""

from __future__ import annotations

import pytest

from acemusic.api.models import Clip, Job, Video, Workspace
from acemusic.api.services import users as user_service
from acemusic.api.services.video import VIDEO_JOB_TYPE
from acemusic.api.settings import ApiSettings
from acemusic.api.tasks import video as tasks
from acemusic.api.tasks.common import JobProcessingError
from acemusic.storage import LocalStorage
from acemusic.video_client import VideoGenerationError, VideoJobUpdate

FAKE_MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 256
FAKE_AUDIO = b"RIFF" + b"\x00" * 100


class FakeVideoService:
    """Plays back a scripted sequence of status updates, then serves the MP4."""

    def __init__(self, updates: list[VideoJobUpdate], *, submit_error: str | None = None) -> None:
        self.updates = list(updates)
        self.submit_error = submit_error
        self.submitted: list[tuple[str, dict]] = []
        self.polls = 0

    def submit(self, audio_bytes: bytes, filename: str, params: dict) -> str:
        if self.submit_error:
            raise VideoGenerationError(self.submit_error)
        assert audio_bytes == FAKE_AUDIO
        self.submitted.append((filename, params))
        return "pj-1"

    def get_status(self, provider_job_id: str) -> VideoJobUpdate:
        self.polls += 1
        # Repeat the final update if polled past the script's end.
        index = min(self.polls - 1, len(self.updates) - 1)
        return self.updates[index]

    def download(self, provider_job_id: str) -> bytes:
        return FAKE_MP4


# ---------------------------------------------------------------------------
# get_video_client factory — CI (no DB)
# ---------------------------------------------------------------------------


class TestGetVideoClient:
    def test_none_without_config(self) -> None:
        assert tasks.get_video_client(ApiSettings(_env_file=None)) is None

    def test_none_with_partial_config(self) -> None:
        assert tasks.get_video_client(ApiSettings(_env_file=None, video_api_key="vk")) is None
        assert tasks.get_video_client(ApiSettings(_env_file=None, video_api_url="https://v.test")) is None

    def test_client_when_configured(self) -> None:
        settings = ApiSettings(_env_file=None, video_api_url="https://v.test", video_api_key="vk")
        client = tasks.get_video_client(settings)
        assert client is not None and client.api_key == "vk" and client.base_url == "https://v.test"


# ---------------------------------------------------------------------------
# Processor wiring — CI (no DB)
# ---------------------------------------------------------------------------


class TestProcessorWiring:
    def test_video_job_type_registered(self) -> None:
        from acemusic.api.tasks.processor import JobProcessor

        assert VIDEO_JOB_TYPE in JobProcessor()._handlers

    async def test_unconfigured_client_fails_claimed_job(self) -> None:
        from acemusic.api.tasks.processor import JobProcessor

        processor = JobProcessor(video_client_factory=None)
        with pytest.raises(JobProcessingError, match="not configured"):
            await processor._run_video_handler(tasks.process_video_job, None)

    async def test_configured_client_and_storage_injected(self) -> None:
        from acemusic.api.tasks.processor import JobProcessor

        fake_client, fake_storage, seen = object(), object(), {}

        async def handler(job, *, storage, client):
            seen.update(storage=storage, client=client)
            return {"ok": True}

        processor = JobProcessor(video_client_factory=lambda: fake_client, storage_factory=lambda: fake_storage)
        assert await processor._run_video_handler(handler, None) == {"ok": True}
        assert seen == {"storage": fake_storage, "client": fake_client}


# ---------------------------------------------------------------------------
# Handler — integration (local MongoDB)
# ---------------------------------------------------------------------------


@pytest.fixture
def storage(mongo_db, tmp_path) -> LocalStorage:
    return LocalStorage(tmp_path / "storage")


async def _make_job_and_clip() -> tuple[Job, Clip]:
    user = await user_service.get_or_create_user(email="v@e.com", provider="google", oauth_id="g-v", name="V")
    workspace = Workspace(name="WS", user_id=user.id)
    await workspace.insert()
    clip = Clip(user_id=user.id, workspace_id=workspace.id, file_path="song.wav", title="Song", duration=10.0)
    await clip.insert()
    params = {"clip_id": str(clip.id), "prompt": "neon city", "resolution": "720p", "aspect_ratio": "16:9"}
    job = Job(user_id=user.id, workspace_id=workspace.id, job_type=VIDEO_JOB_TYPE, input_params=params)
    await job.insert()
    return job, clip


def _updates_to_complete() -> list[VideoJobUpdate]:
    return [
        VideoJobUpdate(state="queued", progress=0),
        VideoJobUpdate(state="rendering", progress=40, eta_seconds=30.0),
        VideoJobUpdate(state="encoding", progress=90, eta_seconds=5.0),
        VideoJobUpdate(state="complete", progress=100),
    ]


@pytest.mark.integration
class TestProcessVideoJob:
    async def test_success_stores_mp4_and_records_video(self, storage) -> None:
        job, clip = await _make_job_and_clip()
        storage.upload(clip.file_path, FAKE_AUDIO)
        client = FakeVideoService(_updates_to_complete())

        result = await tasks.process_video_job(job, storage=storage, client=client, poll_interval=0)

        videos = await Video.find(Video.clip_id == clip.id).to_list()
        assert len(videos) == 1
        video = videos[0]
        assert result == {"video_ids": [str(video.id)], "storage_path": video.storage_path}
        assert video.user_id == job.user_id and video.job_id == job.id
        assert video.resolution == "720p" and video.aspect_ratio == "16:9"
        assert video.storage_path == f"{job.user_id}/{job.workspace_id}/videos/{clip.id}/{job.id}.mp4"
        # The stored object is the provider's rendered MP4, byte for byte.
        assert storage.download(video.storage_path) == FAKE_MP4
        # The poll loop walked the provider states and left the terminal detail.
        assert client.polls >= 4
        fresh = await Job.get(job.id)
        assert fresh.progress_detail == {"state": "complete", "progress": 100}

    async def test_submit_receives_params_without_clip_id(self, storage) -> None:
        job, clip = await _make_job_and_clip()
        storage.upload(clip.file_path, FAKE_AUDIO)
        client = FakeVideoService(_updates_to_complete())

        await tasks.process_video_job(job, storage=storage, client=client, poll_interval=0)

        (filename, params), *_ = client.submitted
        assert filename == f"{clip.id}.wav"
        assert "clip_id" not in params
        assert params["prompt"] == "neon city"

    async def test_progress_detail_written_during_polling(self, storage, monkeypatch) -> None:
        """Each poll persists the provider's state so the status endpoint can serve it live."""
        job, clip = await _make_job_and_clip()
        storage.upload(clip.file_path, FAKE_AUDIO)
        client = FakeVideoService(_updates_to_complete())
        seen: list[dict | None] = []
        original = tasks._set_progress

        async def _spy(job_, state, progress, eta_seconds):
            await original(job_, state, progress, eta_seconds)
            seen.append((await Job.get(job_.id)).progress_detail)

        monkeypatch.setattr(tasks, "_set_progress", _spy)
        await tasks.process_video_job(job, storage=storage, client=client, poll_interval=0)

        assert {"state": "rendering", "progress": 40, "eta_seconds": 30.0} in seen
        assert {"state": "encoding", "progress": 90, "eta_seconds": 5.0} in seen

    async def test_transient_poll_failures_tolerated(self, storage) -> None:
        """A blip in a status poll must not kill a render that is still running."""
        job, clip = await _make_job_and_clip()
        storage.upload(clip.file_path, FAKE_AUDIO)
        client = FakeVideoService(_updates_to_complete())
        real_get_status = client.get_status
        blips = {"remaining": 2}

        def flaky_get_status(provider_job_id: str) -> VideoJobUpdate:
            if blips["remaining"] > 0:
                blips["remaining"] -= 1
                raise VideoGenerationError("connection reset")
            return real_get_status(provider_job_id)

        client.get_status = flaky_get_status
        result = await tasks.process_video_job(job, storage=storage, client=client, poll_interval=0)
        assert await Video.find(Video.job_id == job.id).count() == 1
        assert result["video_ids"]

    async def test_sustained_poll_failure_fails_job(self, storage) -> None:
        job, clip = await _make_job_and_clip()
        storage.upload(clip.file_path, FAKE_AUDIO)
        client = FakeVideoService(_updates_to_complete())

        def always_down(provider_job_id: str) -> VideoJobUpdate:
            raise VideoGenerationError("connection reset")

        client.get_status = always_down
        with pytest.raises(JobProcessingError, match="status poll failed"):
            await tasks.process_video_job(job, storage=storage, client=client, poll_interval=0)

    async def test_provider_failure_fails_job_without_artifacts(self, storage) -> None:
        job, clip = await _make_job_and_clip()
        storage.upload(clip.file_path, FAKE_AUDIO)
        client = FakeVideoService([VideoJobUpdate(state="failed", error="render farm on fire")])

        with pytest.raises(JobProcessingError, match="render farm on fire"):
            await tasks.process_video_job(job, storage=storage, client=client, poll_interval=0)

        assert await Video.find(Video.job_id == job.id).count() == 0

    async def test_submit_error_fails_job(self, storage) -> None:
        job, clip = await _make_job_and_clip()
        storage.upload(clip.file_path, FAKE_AUDIO)
        client = FakeVideoService([], submit_error="401 from provider")

        with pytest.raises(JobProcessingError, match="submission failed"):
            await tasks.process_video_job(job, storage=storage, client=client, poll_interval=0)

    async def test_poll_timeout_fails_job(self, storage) -> None:
        job, clip = await _make_job_and_clip()
        storage.upload(clip.file_path, FAKE_AUDIO)
        client = FakeVideoService([VideoJobUpdate(state="rendering", progress=10)])

        with pytest.raises(JobProcessingError, match="timed out"):
            await tasks.process_video_job(job, storage=storage, client=client, poll_interval=0, poll_timeout=0)

    async def test_missing_source_clip_fails_job(self, storage) -> None:
        job, clip = await _make_job_and_clip()
        await clip.delete()
        client = FakeVideoService(_updates_to_complete())

        with pytest.raises(JobProcessingError, match="no longer exists"):
            await tasks.process_video_job(job, storage=storage, client=client, poll_interval=0)
