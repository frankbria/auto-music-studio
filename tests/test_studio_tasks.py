"""Tests for the studio export job handlers (US-19.6, issue #212).

Exercise ``process_studio_mixdown_job`` and ``process_studio_daw_export_job``
directly against a local on-disk storage backend and a local MongoDB: the
handlers download the referenced source clips, mix / bounce them, and store the
result (a ``generation_mode="studio"`` child clip, or a ZIP under the per-job
export key). They assert the worker contract — lineage, badge mode, format
conversion, the DAW ZIP layout — that only real audio + DB can cover, so the
whole module is ``integration`` (needs a local mongod; the MP3 conversion case
additionally needs ffmpeg and skips itself where it's absent).
"""

from __future__ import annotations

import io
import shutil
import zipfile

import numpy as np
import pytest
import soundfile as sf
from beanie import PydanticObjectId

from acemusic.api.models import Clip, Job, JobStatus, Workspace
from acemusic.api.services import users as user_service
from acemusic.api.services.studio import (
    STUDIO_DAW_EXPORT_JOB_TYPE,
    STUDIO_MIXDOWN_JOB_TYPE,
    studio_export_storage_path,
)
from acemusic.api.tasks import studio as tasks
from acemusic.storage import LocalStorage

SR = 48000

pytestmark = pytest.mark.integration


def _wav_bytes(duration_s: float = 1.0, freq: float = 220.0) -> bytes:
    t = np.linspace(0, duration_s, int(SR * duration_s), endpoint=False)
    mono = (0.4 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    buf = io.BytesIO()
    sf.write(buf, np.column_stack([mono, mono]), SR, format="WAV")
    return buf.getvalue()


@pytest.fixture
def storage(mongo_db, tmp_path) -> LocalStorage:
    # ``mongo_db`` initialises Beanie so the handler can read/insert documents.
    return LocalStorage(tmp_path / "storage")


async def _make_clip(storage: LocalStorage, user, workspace, *, freq: float = 220.0, duration: float = 1.0) -> Clip:
    clip_id = PydanticObjectId()
    file_path = f"{user.id}/{workspace.id}/clips/{clip_id}.wav"
    storage.upload(file_path, _wav_bytes(duration, freq))
    clip = Clip(
        id=clip_id,
        user_id=user.id,
        workspace_id=workspace.id,
        file_path=file_path,
        title="Src",
        format="wav",
        duration=duration,
    )
    await clip.insert()
    return clip


async def _setup(storage: LocalStorage, email: str, n_clips: int = 2):
    user = await user_service.get_or_create_user(email=email, provider="google", oauth_id=f"g-{email}", name="T")
    workspace = Workspace(name="WS", user_id=user.id)
    await workspace.insert()
    clips = [await _make_clip(storage, user, workspace, freq=220.0 * (i + 1)) for i in range(n_clips)]
    return user, workspace, clips


def _mix_job(user, workspace, clips, *, fmt: str = "wav") -> Job:
    return Job(
        user_id=user.id,
        workspace_id=workspace.id,
        job_type=STUDIO_MIXDOWN_JOB_TYPE,
        status=JobStatus.QUEUED,
        input_params={
            "workspace_id": str(workspace.id),
            "project_name": "Studio Song",
            "format": fmt,
            "bpm": 128.0,
            "markers": [{"name": "Drop", "time_sec": 1.0}],
            "tracks": [
                {
                    "name": "Melody",
                    "track_type": "melody",
                    "volume_db": -3.0,
                    "pan": 0.2,
                    "muted": False,
                    "solo": False,
                    "placements": [{"clip_id": str(clips[0].id), "start_sec": 0.0, "duration_sec": None}],
                },
                {
                    "name": "Bass",
                    "track_type": "bass",
                    "volume_db": 0.0,
                    "pan": -0.2,
                    "muted": False,
                    "solo": False,
                    "placements": [{"clip_id": str(clips[1].id), "start_sec": 1.0, "duration_sec": None}],
                },
            ],
        },
    )


class TestMixdownHandler:
    async def test_creates_studio_clip_with_lineage(self, storage) -> None:
        user, workspace, clips = await _setup(storage, "studio-task-mix@example.com")
        job = _mix_job(user, workspace, clips)
        await job.insert()

        result = await tasks.process_studio_mixdown_job(job, storage)

        assert len(result["clip_ids"]) == 1
        child = await Clip.get(PydanticObjectId(result["clip_ids"][0]))
        assert child is not None
        assert child.generation_mode == "studio"
        assert child.title == "Studio Song"
        assert child.format == "wav"
        assert child.bpm == 128
        # Lineage links both distinct source clips.
        assert set(child.parent_clip_ids) == {clips[0].id, clips[1].id}
        # Duration spans the arrangement (bass placed at 1s + 1s clip => ~2s).
        assert child.duration == pytest.approx(2.0, abs=0.1)
        # The rendered audio is retrievable and readable.
        data = storage.download(child.file_path)
        audio, sr = sf.read(io.BytesIO(data), always_2d=True)
        assert sr == SR
        assert audio.shape[1] == 2

    async def test_progress_reaches_uploading(self, storage) -> None:
        user, workspace, clips = await _setup(storage, "studio-task-progress@example.com")
        job = _mix_job(user, workspace, clips)
        await job.insert()
        await tasks.process_studio_mixdown_job(job, storage)
        reloaded = await Job.get(job.id)
        assert reloaded.progress == "Uploading"

    @pytest.mark.parametrize(
        "fmt",
        [
            "flac",  # libsndfile — runs everywhere, ffmpeg not needed
            pytest.param(
                "mp3",
                marks=pytest.mark.skipif(
                    shutil.which("ffmpeg") is None, reason="mp3 conversion requires ffmpeg (not installed in CI)"
                ),
            ),
        ],
    )
    async def test_alternate_formats(self, storage, fmt: str) -> None:
        user, workspace, clips = await _setup(storage, f"studio-task-{fmt}@example.com")
        job = _mix_job(user, workspace, clips, fmt=fmt)
        await job.insert()
        result = await tasks.process_studio_mixdown_job(job, storage)
        child = await Clip.get(PydanticObjectId(result["clip_ids"][0]))
        assert child.format == fmt
        assert child.file_path.endswith(f".{fmt}")
        assert storage.download(child.file_path)

    async def test_missing_source_clip_fails_job(self, storage) -> None:
        from acemusic.api.tasks.common import JobProcessingError

        user, workspace, clips = await _setup(storage, "studio-task-missing@example.com", n_clips=1)
        job = _mix_job(user, workspace, [clips[0], clips[0]])
        # Point the second track at a non-existent clip.
        job.input_params["tracks"][1]["placements"][0]["clip_id"] = str(PydanticObjectId())
        await job.insert()
        with pytest.raises(JobProcessingError):
            await tasks.process_studio_mixdown_job(job, storage)

    async def test_overlong_arrangement_fails_job(self, storage, monkeypatch) -> None:
        from acemusic.api.tasks.common import JobProcessingError

        user, workspace, clips = await _setup(storage, "studio-task-overlong@example.com", n_clips=1)
        job = _mix_job(user, workspace, [clips[0], clips[0]])
        await job.insert()
        # The field caps bound start_sec, but an untrimmed placement runs the full
        # source clip — fake a source long enough to blow past the timeline cap
        # (a real multi-hour WAV fixture would be absurd).
        monkeypatch.setattr(tasks, "arrangement_duration", lambda _mixes: 5 * 3600.0)
        with pytest.raises(JobProcessingError, match="export limit"):
            await tasks.process_studio_mixdown_job(job, storage)


class TestDawExportHandler:
    async def test_bundles_stems_and_metadata(self, storage) -> None:
        user, workspace, clips = await _setup(storage, "studio-task-daw@example.com")
        job = Job(
            user_id=user.id,
            workspace_id=workspace.id,
            job_type=STUDIO_DAW_EXPORT_JOB_TYPE,
            status=JobStatus.QUEUED,
            input_params={
                "workspace_id": str(workspace.id),
                "project_name": "DAW Song",
                "bpm": 90.0,
                "markers": [{"name": "Intro", "time_sec": 0.0}],
                "tracks": [
                    {
                        "name": "Melody",
                        "track_type": "melody",
                        "volume_db": -6.0,
                        "pan": 0.5,
                        "muted": False,
                        "solo": False,
                        "placements": [{"clip_id": str(clips[0].id), "start_sec": 0.0, "duration_sec": None}],
                    },
                    {
                        "name": "Bass",
                        "track_type": "bass",
                        "volume_db": 0.0,
                        "pan": 0.0,
                        "muted": False,
                        "solo": False,
                        "placements": [{"clip_id": str(clips[1].id), "start_sec": 1.0, "duration_sec": None}],
                    },
                ],
            },
        )
        await job.insert()

        result = await tasks.process_studio_daw_export_job(job, storage)

        export_key = studio_export_storage_path(user.id, workspace.id, job.id)
        assert result["export_path"] == export_key
        data = storage.download(export_key)
        import json

        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = set(zf.namelist())
            root = "daw-song_Export"
            assert f"{root}/project.json" in names
            assert f"{root}/audio/melody.wav" in names
            assert f"{root}/audio/bass.wav" in names
            meta = json.loads(zf.read(f"{root}/project.json"))
            melody_stem = zf.read(f"{root}/audio/melody.wav")
            bass_stem = zf.read(f"{root}/audio/bass.wav")
        assert meta["project_name"] == "DAW Song"
        assert meta["bpm"] == 90.0
        # Per-track gain/pan recorded in metadata (not baked into the stem).
        assert {t["name"]: t["volume_db"] for t in meta["tracks"]} == {"Melody": -6.0, "Bass": 0.0}
        assert {t["name"]: t["pan"] for t in meta["tracks"]} == {"Melody": 0.5, "Bass": 0.0}
        assert meta["markers"] == [{"name": "Intro", "time": 0.0}]
        # Stems are silence-padded to the full arrangement length (~2s), decodable,
        # and carry real signal where their placements sit.
        audio, sr = sf.read(io.BytesIO(melody_stem), always_2d=True)
        assert len(audio) / sr == pytest.approx(2.0, abs=0.1)
        assert np.sqrt(np.mean(np.square(audio[: sr // 2]))) > 1e-3  # melody sounds from t=0
        bass_audio, bass_sr = sf.read(io.BytesIO(bass_stem), always_2d=True)
        assert len(bass_audio) / bass_sr == pytest.approx(2.0, abs=0.1)
        assert np.sqrt(np.mean(np.square(bass_audio[: bass_sr // 2]))) < 1e-3  # bass placed at 1s: leading silence
        assert np.sqrt(np.mean(np.square(bass_audio[bass_sr + bass_sr // 4 :]))) > 1e-3  # ...then audible

    async def test_progress_reaches_uploading(self, storage) -> None:
        user, workspace, clips = await _setup(storage, "studio-task-daw-progress@example.com", n_clips=1)
        job = Job(
            user_id=user.id,
            workspace_id=workspace.id,
            job_type=STUDIO_DAW_EXPORT_JOB_TYPE,
            status=JobStatus.QUEUED,
            input_params={
                "workspace_id": str(workspace.id),
                "project_name": "P",
                "bpm": None,
                "markers": [],
                "tracks": [
                    {
                        "name": "Only",
                        "track_type": "melody",
                        "volume_db": 0.0,
                        "pan": 0.0,
                        "muted": False,
                        "solo": False,
                        "placements": [{"clip_id": str(clips[0].id), "start_sec": 0.0, "duration_sec": None}],
                    }
                ],
            },
        )
        await job.insert()
        await tasks.process_studio_daw_export_job(job, storage)
        reloaded = await Job.get(job.id)
        assert reloaded.progress == "Uploading"
