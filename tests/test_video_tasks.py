"""Tests for the video job handler (US-22.1).

Exercise ``process_video_job`` directly with a fake provider client (dependency
injection, no monkeypatching) and a local storage backend: it downloads the
source song, submits it, polls the provider (surfacing progress on
``job.progress_detail``), stores the rendered MP4 and records a ``Video``
document. The ``get_video_client`` factory tests run in CI (no DB); the handler
tests need a local MongoDB (Beanie) and are ``integration``.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest
from beanie import PydanticObjectId

from acemusic.api.models import Clip, Job, Video, Workspace
from acemusic.api.services import users as user_service
from acemusic.api.services.video import VIDEO_JOB_TYPE
from acemusic.api.settings import ApiSettings
from acemusic.api.tasks import video as tasks
from acemusic.api.tasks.common import JobProcessingError
from acemusic.storage import LocalStorage
from acemusic.video_client import VideoGenerationError, VideoJobUpdate
from acemusic.video_watermark import WatermarkError

FAKE_MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 256
FAKE_AUDIO = b"RIFF" + b"\x00" * 100


class FakeVideoService:
    """Plays back a scripted sequence of status updates, then serves the MP4."""

    def __init__(
        self,
        updates: list[VideoJobUpdate],
        *,
        submit_error: str | None = None,
        expect_media: bytes | None = FAKE_AUDIO,
    ) -> None:
        self.updates = list(updates)
        self.submit_error = submit_error
        self.expect_media = expect_media
        self.submitted: list[tuple[str, dict]] = []
        self.submitted_media: list[bytes] = []
        self.polls = 0

    def submit(self, audio_bytes: bytes, filename: str, params: dict) -> str:
        if self.submit_error:
            raise VideoGenerationError(self.submit_error)
        if self.expect_media is not None:
            assert audio_bytes == self.expect_media
        self.submitted_media.append(audio_bytes)
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

    def test_default_watermark_is_the_real_compositor(self) -> None:
        """#401: the injectable seam must default to the real thing, not a no-op."""
        import inspect

        from acemusic.video_watermark import apply_watermark

        assert inspect.signature(tasks.process_video_job).parameters["watermark"].default is apply_watermark


# ---------------------------------------------------------------------------
# Handler — integration (local MongoDB)
# ---------------------------------------------------------------------------


@pytest.fixture
def storage(mongo_db, tmp_path) -> LocalStorage:
    return LocalStorage(tmp_path / "storage")


async def _make_job_and_clip(*, tier: str = "pro") -> tuple[Job, Clip]:
    # Pro by default: these tests assert the provider's bytes are stored verbatim,
    # which is exactly the Pro deliverable. The free tier's watermarking (#401) has
    # its own cases below.
    user = await user_service.get_or_create_user(email="v@e.com", provider="google", oauth_id="g-v", name="V")
    user.subscription_tier = tier
    await user.save()
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
        assert video.duration == clip.duration == 10.0  # original render inherits the song's length
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


# ---------------------------------------------------------------------------
# Edit jobs (US-22.4) — integration
# ---------------------------------------------------------------------------


async def _make_edit_job_and_source(storage: LocalStorage, *, tier: str = "pro") -> tuple[Job, Video]:
    """A source Video (its MP4 stored) plus a queued edit job referencing it."""
    user = await user_service.get_or_create_user(email="ve@e.com", provider="google", oauth_id="g-ve", name="VE")
    user.subscription_tier = tier
    await user.save()
    workspace = Workspace(name="WS", user_id=user.id)
    await workspace.insert()
    clip = Clip(user_id=user.id, workspace_id=workspace.id, file_path="song.wav", title="Song", duration=10.0)
    await clip.insert()
    source = Video(
        clip_id=clip.id,
        user_id=user.id,
        job_id=(await Job(user_id=user.id, workspace_id=workspace.id, job_type=VIDEO_JOB_TYPE).insert()).id,
        storage_path=f"{user.id}/{workspace.id}/videos/{clip.id}/orig.mp4",
        resolution="1080p",
        aspect_ratio="9:16",
    )
    storage.upload(source.storage_path, FAKE_MP4)
    await source.insert()
    params = {
        "clip_id": str(clip.id),
        "source_video_id": str(source.id),
        "resolution": source.resolution,
        "aspect_ratio": source.aspect_ratio,
        "edit": {"operation": "trim", "start_seconds": 2.0, "end_seconds": 8.0},
    }
    job = Job(user_id=user.id, workspace_id=workspace.id, job_type=VIDEO_JOB_TYPE, input_params=params)
    await job.insert()
    return job, source


@pytest.mark.integration
class TestProcessVideoEditJob:
    async def test_edit_stores_new_version_linked_to_source(self, storage) -> None:
        job, source = await _make_edit_job_and_source(storage)
        client = FakeVideoService(_updates_to_complete(), expect_media=FAKE_MP4)

        result = await tasks.process_video_job(job, storage=storage, client=client, poll_interval=0)

        new = await Video.get(PydanticObjectId(result["video_ids"][0]))
        assert new.id != source.id  # a new version, original preserved
        assert new.parent_video_id == source.id
        assert new.edit == {"operation": "trim", "start_seconds": 2.0, "end_seconds": 8.0}
        assert new.duration == 6.0  # a trim resizes the video to its range (8 - 2)
        assert new.clip_id == source.clip_id
        assert new.resolution == "1080p" and new.aspect_ratio == "9:16"
        assert new.storage_path == f"{job.user_id}/{job.workspace_id}/videos/{source.clip_id}/{job.id}.mp4"
        # The source document and its object are untouched.
        assert (await Video.get(source.id)).parent_video_id is None
        assert storage.download(source.storage_path) == FAKE_MP4

    async def test_non_trim_edit_inherits_source_duration(self, storage) -> None:
        # A lyrics-overlay edit keeps the source video's length (only trim resizes).
        job, source = await _make_edit_job_and_source(storage)
        source.duration = 8.0
        await source.save()
        job.input_params["edit"] = {"operation": "lyrics_overlay", "lyrics_enabled": True}
        await job.save()
        client = FakeVideoService(_updates_to_complete(), expect_media=FAKE_MP4)

        result = await tasks.process_video_job(job, storage=storage, client=client, poll_interval=0)

        new = await Video.get(PydanticObjectId(result["video_ids"][0]))
        assert new.duration == 8.0

    async def test_edit_submits_source_media_and_spec(self, storage) -> None:
        job, source = await _make_edit_job_and_source(storage)
        client = FakeVideoService(_updates_to_complete(), expect_media=FAKE_MP4)

        await tasks.process_video_job(job, storage=storage, client=client, poll_interval=0)

        (filename, params), *_ = client.submitted
        assert filename == f"{source.id}.mp4"
        assert params["operation"] == "trim"
        assert params["start_seconds"] == 2.0
        assert "source_video_id" not in params  # provider gets the media + spec, not our ids

    async def test_missing_source_object_fails_job(self, storage) -> None:
        job, source = await _make_edit_job_and_source(storage)
        storage.delete(source.storage_path)
        client = FakeVideoService(_updates_to_complete(), expect_media=None)

        with pytest.raises(JobProcessingError, match="is missing"):
            await tasks.process_video_job(job, storage=storage, client=client, poll_interval=0)

    async def test_deleted_source_document_fails_job(self, storage) -> None:
        job, source = await _make_edit_job_and_source(storage)
        await source.delete()
        client = FakeVideoService(_updates_to_complete(), expect_media=None)

        with pytest.raises(JobProcessingError, match="not found"):
            await tasks.process_video_job(job, storage=storage, client=client, poll_interval=0)


# ---------------------------------------------------------------------------
# Free-tier watermarking (#401) — integration
# ---------------------------------------------------------------------------

MARKED_MP4 = b"\x00\x00\x00\x18ftypmp42" + b"WATERMARKED" * 8


def _encode_test_video(tmp_path) -> bytes:
    """A real 1s 720p clip, for the one case that runs the actual compositor."""
    out = tmp_path / "provider.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", "color=c=gray:s=1280x720:r=15:d=1", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)],
        check=True,
    )  # fmt: skip
    return out.read_bytes()


def _bottom_right_changed(tmp_path, before: bytes, after: bytes) -> bool:
    """Whether the two clips' first frames differ in the bottom-right corner."""
    from PIL import Image

    frames = []
    for name, data in (("before", before), ("after", after)):
        mp4, png = tmp_path / f"{name}.mp4", tmp_path / f"{name}.png"
        mp4.write_bytes(data)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp4), "-frames:v", "1", str(png)], check=True)
        frames.append(Image.open(png).convert("RGB"))
    width, height = frames[0].size
    corner = (int(width * 0.6), int(height * 0.8), width, height)
    return frames[0].crop(corner).tobytes() != frames[1].crop(corner).tobytes()


def _fake_watermark(calls: list[bytes]):
    """A stand-in for ``apply_watermark`` that records what it was handed."""

    def watermark(data: bytes) -> bytes:
        calls.append(data)
        return MARKED_MP4

    return watermark


def _exploding_watermark(data: bytes) -> bytes:
    raise WatermarkError("ffmpeg is not installed or not on PATH")


@pytest.mark.integration
class TestFreeTierWatermark:
    """US-26.2 sells the free tier as *watermarked* 720p; #401 is that half."""

    async def test_free_account_render_is_watermarked(self, storage) -> None:
        job, clip = await _make_job_and_clip(tier="free")
        storage.upload(clip.file_path, FAKE_AUDIO)
        client = FakeVideoService(_updates_to_complete())
        calls: list[bytes] = []

        result = await tasks.process_video_job(
            job, storage=storage, client=client, poll_interval=0, watermark=_fake_watermark(calls)
        )

        assert calls == [FAKE_MP4]  # the provider's render went in...
        assert storage.download(result["storage_path"]) == MARKED_MP4  # ...the marked one was stored

    async def test_pro_account_render_is_untouched(self, storage) -> None:
        job, clip = await _make_job_and_clip(tier="pro")
        storage.upload(clip.file_path, FAKE_AUDIO)
        client = FakeVideoService(_updates_to_complete())
        calls: list[bytes] = []

        result = await tasks.process_video_job(
            job, storage=storage, client=client, poll_interval=0, watermark=_fake_watermark(calls)
        )

        assert calls == []
        assert storage.download(result["storage_path"]) == FAKE_MP4

    async def test_unknown_tier_is_watermarked(self, storage) -> None:
        """A typo in the tier field must fail closed, as ``tiers.normalise`` does."""
        job, clip = await _make_job_and_clip(tier="proo")
        storage.upload(clip.file_path, FAKE_AUDIO)
        client = FakeVideoService(_updates_to_complete())
        calls: list[bytes] = []

        await tasks.process_video_job(
            job, storage=storage, client=client, poll_interval=0, watermark=_fake_watermark(calls)
        )

        assert calls == [FAKE_MP4]

    async def test_deleted_user_is_watermarked(self, storage) -> None:
        job, clip = await _make_job_and_clip(tier="pro")
        storage.upload(clip.file_path, FAKE_AUDIO)
        await (await user_service.get_user_by_id(str(job.user_id))).delete()
        client = FakeVideoService(_updates_to_complete())
        calls: list[bytes] = []

        await tasks.process_video_job(
            job, storage=storage, client=client, poll_interval=0, watermark=_fake_watermark(calls)
        )

        assert calls == [FAKE_MP4]

    async def test_free_account_edit_is_watermarked(self, storage) -> None:
        """An edit is a render too — it must not be a way around the mark."""
        job, source = await _make_edit_job_and_source(storage, tier="free")
        client = FakeVideoService(_updates_to_complete(), expect_media=FAKE_MP4)
        calls: list[bytes] = []

        result = await tasks.process_video_job(
            job, storage=storage, client=client, poll_interval=0, watermark=_fake_watermark(calls)
        )

        assert calls == [FAKE_MP4]
        assert storage.download(result["storage_path"]) == MARKED_MP4

    async def test_tier_is_read_when_the_render_completes_not_at_enqueue(self, storage) -> None:
        """A job queued while Pro is marked if the owner is free by the time it renders.

        The policy is deliberate — the mark reflects the tier at the moment the
        video is produced — so it deserves a test rather than only a docstring.
        """
        job, clip = await _make_job_and_clip(tier="pro")
        storage.upload(clip.file_path, FAKE_AUDIO)
        owner = await user_service.get_user_by_id(str(job.user_id))
        owner.subscription_tier = "free"
        await owner.save()
        calls: list[bytes] = []

        await tasks.process_video_job(
            job, storage=storage, client=FakeVideoService(_updates_to_complete()), poll_interval=0,
            watermark=_fake_watermark(calls),
        )  # fmt: skip

        assert calls == [FAKE_MP4]

    async def test_watermark_failure_fails_the_job(self, storage) -> None:
        """#401: never silently produce an unmarked video for a free account."""
        job, clip = await _make_job_and_clip(tier="free")
        storage.upload(clip.file_path, FAKE_AUDIO)
        client = FakeVideoService(_updates_to_complete())

        with pytest.raises(JobProcessingError, match="[Ww]atermark"):
            await tasks.process_video_job(
                job, storage=storage, client=client, poll_interval=0, watermark=_exploding_watermark
            )

        assert await Video.find(Video.job_id == job.id).count() == 0
        path = f"{job.user_id}/{job.workspace_id}/videos/{clip.id}/{job.id}.mp4"
        with pytest.raises(FileNotFoundError):
            storage.download(path)

    @pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
    async def test_default_path_really_composites(self, storage, tmp_path) -> None:
        """No injected double: the handler's own default marks a real MP4.

        The other cases here inject a stand-in to keep them fast, which would let
        a regression that kept the default but stopped calling it pass unnoticed.
        """
        rendered = _encode_test_video(tmp_path)
        job, clip = await _make_job_and_clip(tier="free")
        storage.upload(clip.file_path, FAKE_AUDIO)
        client = FakeVideoService(_updates_to_complete())
        client.download = lambda provider_job_id: rendered

        result = await tasks.process_video_job(job, storage=storage, client=client, poll_interval=0)

        stored = storage.download(result["storage_path"])
        assert stored != rendered
        assert _bottom_right_changed(tmp_path, rendered, stored), "no mark in the stored video"
