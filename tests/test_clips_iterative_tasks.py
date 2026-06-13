"""Tests for the iterative generation job handlers (US-10.3, issue #83).

These exercise ``acemusic.api.tasks.iterative`` directly with a fake ACE-Step
client and a local on-disk storage backend: each handler downloads the source
clip, "submits" a task, downloads the (faked) audio, applies any local
post-processing, and stores a lineage-tagged child clip. They assert the worker
contract — lineage metadata, inherited fields, post-processing, rollback — that
the real ACE-Step integration tests cannot cheaply cover.

All require a local MongoDB (Beanie) and are marked ``integration``.
"""

import io

import numpy as np
import pytest
import soundfile as sf
from beanie import PydanticObjectId

from acemusic.api.models import Clip, Job, JobStatus, Workspace
from acemusic.api.services import users as user_service
from acemusic.api.tasks import iterative as tasks
from acemusic.storage import LocalStorage

pytestmark = pytest.mark.integration

SR = 44100


def _wav_bytes(duration_s: float = 3.0, freq: float = 440.0) -> bytes:
    """Render a stereo sine-wave WAV to bytes (no temp file)."""
    t = np.linspace(0, duration_s, int(SR * duration_s), endpoint=False)
    mono = (0.3 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    stereo = np.column_stack([mono, mono])
    buf = io.BytesIO()
    sf.write(buf, stereo, SR, format="WAV")
    return buf.getvalue()


class FakeAce:
    """Records submit_task kwargs and returns canned audio on download."""

    def __init__(self, output: bytes) -> None:
        self.output = output
        self.submitted: list[dict] = []
        self._n = 1

    def submit_task(self, **kwargs) -> str:
        self.submitted.append(kwargs)
        self._n = kwargs.get("num_clips", 1) or 1
        return "task-1"

    def download_audio(self, url: str) -> bytes:
        return self.output


def _make_poll(status: str = "completed", error: str | None = None):
    async def poll(client, task_id):
        return {"status": status, "audio_urls": [f"u{i}" for i in range(client._n)], "error": error}

    return poll


@pytest.fixture
def storage(mongo_db, tmp_path) -> LocalStorage:
    # ``mongo_db`` initialises Beanie so the handlers can read/insert documents.
    return LocalStorage(tmp_path / "storage")


async def _make_user(email: str):
    return await user_service.get_or_create_user(email=email, provider="google", oauth_id=f"g-{email}", name="T")


async def _make_clip(
    storage: LocalStorage,
    *,
    email: str,
    duration: float = 3.0,
    bpm: int | None = 120,
    key: str | None = "C",
    vocal_language: str | None = "en",
    title: str | None = "Source",
    audio: bytes | None = None,
) -> tuple[Job, Clip]:
    """Create a user/workspace/source clip with real wav bytes in storage."""
    user = await _make_user(email)
    workspace = Workspace(name="WS", user_id=user.id)
    await workspace.insert()
    clip_id = PydanticObjectId()
    file_path = f"{user.id}/{workspace.id}/clips/{clip_id}.wav"
    storage.upload(file_path, audio if audio is not None else _wav_bytes(duration))
    clip = Clip(
        id=clip_id,
        user_id=user.id,
        workspace_id=workspace.id,
        file_path=file_path,
        format="wav",
        duration=duration,
        bpm=bpm,
        key=key,
        vocal_language=vocal_language,
        title=title,
        style_tags=["lofi"],
    )
    await clip.insert()
    job = Job(user_id=user.id, workspace_id=workspace.id, job_type="", input_params={}, status=JobStatus.QUEUED)
    return job, clip


async def _child(result: dict) -> Clip:
    ids = result["clip_ids"]
    assert len(ids) == 1
    return await Clip.get(PydanticObjectId(ids[0]))


# ---------------------------------------------------------------------------
# extend
# ---------------------------------------------------------------------------


class TestExtend:
    async def test_creates_longer_child_with_lineage(self, storage) -> None:
        job, source = await _make_clip(storage, email="t-extend@example.com", duration=3.0)
        job.job_type = tasks.EXTEND_JOB_TYPE
        job.input_params = {"clip_id": str(source.id), "duration": "2s", "from_point": "end", "lyrics": "la"}
        client = FakeAce(_wav_bytes(5.0))

        result = await tasks.process_extend_job(job, storage=storage, client=client, poll=_make_poll())

        child = await _child(result)
        assert child.parent_clip_ids == [source.id]
        assert child.generation_mode == "extend"
        assert child.generation_params == job.input_params
        assert child.bpm == 120 and child.key == "C" and child.vocal_language == "en"
        # Extend grows the source by ~the requested duration (3s + 2s).
        assert child.duration == pytest.approx(5.0, abs=0.05)
        submitted = client.submitted[0]
        assert submitted["task_type"] == "repaint"
        assert submitted["repainting_start"] == pytest.approx(3.0)
        assert submitted["repainting_end"] == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# cover / remix / add-vocal
# ---------------------------------------------------------------------------


class TestRestyle:
    async def test_cover_forwards_lyrics_override(self, storage) -> None:
        job, source = await _make_clip(storage, email="t-cover@example.com")
        job.job_type = tasks.COVER_JOB_TYPE
        job.input_params = {"clip_id": str(source.id), "style": "jazz", "lyrics_override": "new words"}
        client = FakeAce(_wav_bytes(3.0))

        result = await tasks.process_cover_job(job, storage=storage, client=client, poll=_make_poll())

        child = await _child(result)
        assert child.generation_mode == "cover"
        submitted = client.submitted[0]
        assert submitted["task_type"] == "cover"
        assert submitted["lyrics"] == "new words"
        assert submitted["style"] == "jazz"

    async def test_remix_uses_cover_task_and_keeps_source_lyrics(self, storage) -> None:
        job, source = await _make_clip(storage, email="t-remix@example.com")
        source.lyrics = "original"
        await source.save()
        job.job_type = tasks.REMIX_JOB_TYPE
        job.input_params = {"clip_id": str(source.id), "style": "house"}
        client = FakeAce(_wav_bytes(3.0))

        result = await tasks.process_remix_job(job, storage=storage, client=client, poll=_make_poll())

        child = await _child(result)
        assert child.generation_mode == "remix"
        assert client.submitted[0]["task_type"] == "cover"
        assert client.submitted[0]["lyrics"] == "original"

    async def test_add_vocal_uses_complete_task(self, storage) -> None:
        job, source = await _make_clip(storage, email="t-vocal@example.com")
        job.job_type = tasks.ADD_VOCAL_JOB_TYPE
        job.input_params = {"clip_id": str(source.id), "lyrics": "sing this", "vocal_style": "soulful"}
        client = FakeAce(_wav_bytes(3.0))

        result = await tasks.process_add_vocal_job(job, storage=storage, client=client, poll=_make_poll())

        child = await _child(result)
        assert child.generation_mode == "add_vocal"
        submitted = client.submitted[0]
        assert submitted["task_type"] == "complete"
        assert submitted["lyrics"] == "sing this"
        assert submitted["style"] == "soulful"


# ---------------------------------------------------------------------------
# repaint
# ---------------------------------------------------------------------------


class TestRepaint:
    async def test_stitches_and_preserves_length(self, storage) -> None:
        job, source = await _make_clip(storage, email="t-repaint@example.com", duration=3.0)
        job.job_type = tasks.REPAINT_JOB_TYPE
        job.input_params = {
            "clip_id": str(source.id),
            "start_ms": 1000,
            "end_ms": 2000,
            "prompt": "add a solo",
            "style": None,
        }
        # ACE returns a full-length clip; only [1000,2000] is spliced in.
        client = FakeAce(_wav_bytes(3.0, freq=880.0))

        result = await tasks.process_repaint_job(job, storage=storage, client=client, poll=_make_poll())

        child = await _child(result)
        assert child.generation_mode == "repaint"
        # Stitched output stays ~the original length; the two 50ms crossfade
        # seams trim ~100ms off the 3.0s total.
        assert child.duration == pytest.approx(2.9, abs=0.05)
        submitted = client.submitted[0]
        assert submitted["task_type"] == "repaint"
        assert submitted["repainting_start"] == pytest.approx(1.0)
        assert submitted["repainting_end"] == pytest.approx(2.0)

    async def test_truncated_output_fails(self, storage) -> None:
        job, source = await _make_clip(storage, email="t-repaint-trunc@example.com", duration=3.0)
        job.job_type = tasks.REPAINT_JOB_TYPE
        job.input_params = {"clip_id": str(source.id), "start_ms": 1000, "end_ms": 2900, "prompt": "p", "style": None}
        client = FakeAce(_wav_bytes(1.0))  # far shorter than end_ms

        before = await Clip.count()
        with pytest.raises(tasks.IterativeProcessingError):
            await tasks.process_repaint_job(job, storage=storage, client=client, poll=_make_poll())
        assert await Clip.count() == before  # no orphan child


# ---------------------------------------------------------------------------
# mashup
# ---------------------------------------------------------------------------


class TestMashup:
    async def test_blends_two_sources_with_full_lineage(self, storage) -> None:
        job, primary = await _make_clip(storage, email="t-mashup@example.com", key="C")
        secondary_id = PydanticObjectId()
        sec_path = f"{primary.user_id}/{primary.workspace_id}/clips/{secondary_id}.wav"
        storage.upload(sec_path, _wav_bytes(3.0, freq=550.0))
        secondary = Clip(
            id=secondary_id,
            user_id=primary.user_id,
            workspace_id=primary.workspace_id,
            file_path=sec_path,
            format="wav",
            duration=3.0,
            bpm=128,
            key="G",  # mismatched key
            title="Second",
        )
        await secondary.insert()
        job.job_type = tasks.MASHUP_JOB_TYPE
        job.input_params = {
            "clip_ids": [str(primary.id), str(secondary.id)],
            "blend_mode": "layered",
            "style": "mashup vibes",
        }
        client = FakeAce(_wav_bytes(3.0))

        result = await tasks.process_mashup_job(job, storage=storage, client=client, poll=_make_poll())

        child = await _child(result)
        assert child.generation_mode == "mashup"
        assert child.parent_clip_ids == [primary.id, secondary.id]
        submitted = client.submitted[0]
        assert submitted["task_type"] == "mashup"
        assert submitted["src_audio_path"].endswith(".wav")
        assert submitted["ref_audio_path"].endswith(".wav")
        assert submitted["blend_mode"] == "layered"
        # Mismatched keys → no key constraint asserted.
        assert submitted["key"] is None

    async def test_three_sources_all_in_lineage(self, storage) -> None:
        job, primary = await _make_clip(storage, email="t-mashup3@example.com")
        extra = []
        for i in range(2):
            cid = PydanticObjectId()
            path = f"{primary.user_id}/{primary.workspace_id}/clips/{cid}.wav"
            storage.upload(path, _wav_bytes(3.0, freq=500.0 + 50 * i))
            clip = Clip(
                id=cid,
                user_id=primary.user_id,
                workspace_id=primary.workspace_id,
                file_path=path,
                format="wav",
                duration=3.0,
                bpm=120,
                key="C",
                title=f"Extra{i}",
            )
            await clip.insert()
            extra.append(clip)
        job.job_type = tasks.MASHUP_JOB_TYPE
        job.input_params = {
            "clip_ids": [str(primary.id), str(extra[0].id), str(extra[1].id)],
            "blend_mode": "layered",
            "style": None,
        }
        client = FakeAce(_wav_bytes(3.0))

        result = await tasks.process_mashup_job(job, storage=storage, client=client, poll=_make_poll())

        child = await _child(result)
        # Every requested source is recorded — none silently dropped.
        assert child.parent_clip_ids == [primary.id, extra[0].id, extra[1].id]
        # All non-primary sources are mixed into the single reference track.
        assert client.submitted[0]["ref_audio_path"].endswith("reference.wav")

    async def test_bpm_aligns_mismatched_secondary(self, storage, monkeypatch) -> None:
        import shutil

        job, primary = await _make_clip(storage, email="t-mashup-bpm@example.com", bpm=120)
        sec_id = PydanticObjectId()
        sec_path = f"{primary.user_id}/{primary.workspace_id}/clips/{sec_id}.wav"
        storage.upload(sec_path, _wav_bytes(3.0, freq=550.0))
        secondary = Clip(
            id=sec_id,
            user_id=primary.user_id,
            workspace_id=primary.workspace_id,
            file_path=sec_path,
            format="wav",
            duration=3.0,
            bpm=90,  # different tempo → must be aligned to the primary's 120
            key="C",
            title="Slow",
        )
        await secondary.insert()
        job.job_type = tasks.MASHUP_JOB_TYPE
        job.input_params = {"clip_ids": [str(primary.id), str(secondary.id)], "blend_mode": "layered", "style": None}
        client = FakeAce(_wav_bytes(3.0))

        rates: list[float] = []

        def fake_stretch(input_path, output_path, rate):
            rates.append(rate)
            shutil.copy(input_path, output_path)  # keep a readable wav for the overlay

        monkeypatch.setattr(tasks, "time_stretch_audio", fake_stretch)

        await tasks.process_mashup_job(job, storage=storage, client=client, poll=_make_poll())

        # Secondary at 90 BPM aligned to the primary's 120: rate 120/90.
        assert rates == [pytest.approx(120 / 90)]


# ---------------------------------------------------------------------------
# sample
# ---------------------------------------------------------------------------


class TestSample:
    async def test_produces_num_clips_children(self, storage) -> None:
        job, source = await _make_clip(storage, email="t-sample@example.com", duration=3.0)
        job.job_type = tasks.SAMPLE_JOB_TYPE
        job.input_params = {
            "clip_id": str(source.id),
            "start_ms": 500,
            "end_ms": 1500,
            "role": "loop-bed",
            "prompt": "make a beat",
            "backend": "ace-step",
            "num_clips": 2,
        }
        client = FakeAce(_wav_bytes(3.0))

        result = await tasks.process_sample_job(job, storage=storage, client=client, poll=_make_poll())

        assert len(result["clip_ids"]) == 2
        for cid in result["clip_ids"]:
            child = await Clip.get(PydanticObjectId(cid))
            assert child.generation_mode == "sample"
            assert child.parent_clip_ids == [source.id]
            assert child.duration and child.duration > 0
        assert client.submitted[0]["num_clips"] == 2

    async def test_partial_failure_rolls_back_earlier_children(self, storage, monkeypatch) -> None:
        job, source = await _make_clip(storage, email="t-sample-rollback@example.com", duration=3.0)
        job.job_type = tasks.SAMPLE_JOB_TYPE
        job.input_params = {
            "clip_id": str(source.id),
            "start_ms": 500,
            "end_ms": 1500,
            "role": "loop-bed",
            "prompt": "make a beat",
            "backend": "ace-step",
            "num_clips": 3,
        }
        client = FakeAce(_wav_bytes(3.0))

        # Fail on the second combine so the first child must be rolled back.
        real_combine = tasks.combine_sample
        calls = {"n": 0}

        def flaky_combine(**kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("combine boom")
            return real_combine(**kwargs)

        monkeypatch.setattr(tasks, "combine_sample", flaky_combine)

        before = await Clip.count()
        with pytest.raises(RuntimeError):
            await tasks.process_sample_job(job, storage=storage, client=client, poll=_make_poll())
        # The first child (created before the failure) was rolled back.
        assert await Clip.count() == before


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------


class TestFailures:
    async def test_failed_task_raises_and_leaves_no_clip(self, storage) -> None:
        job, source = await _make_clip(storage, email="t-fail@example.com")
        job.job_type = tasks.COVER_JOB_TYPE
        job.input_params = {"clip_id": str(source.id), "style": "jazz", "lyrics_override": None}
        client = FakeAce(_wav_bytes(3.0))

        before = await Clip.count()
        with pytest.raises(tasks.IterativeProcessingError):
            await tasks.process_cover_job(job, storage=storage, client=client, poll=_make_poll("failed", "boom"))
        assert await Clip.count() == before

    async def test_missing_source_clip_raises(self, storage) -> None:
        job, source = await _make_clip(storage, email="t-missing@example.com")
        await source.delete()
        job.job_type = tasks.COVER_JOB_TYPE
        job.input_params = {"clip_id": str(source.id), "style": "jazz", "lyrics_override": None}
        client = FakeAce(_wav_bytes(3.0))
        with pytest.raises(tasks.IterativeProcessingError):
            await tasks.process_cover_job(job, storage=storage, client=client, poll=_make_poll())
