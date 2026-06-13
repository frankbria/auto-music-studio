"""Tests for the MIDI-extraction endpoints (US-10.2, issue #82).

Covers ``POST /clips/{id}/midi`` (enqueue or cache-hit) and
``GET /clips/{id}/midi`` (download URLs). MIDI files are stored as objects, not
clip records, and referenced from ``Clip.midi_paths``. The 401 auth-gate test
runs in CI (no DB); the rest are ``integration``.

The end-to-end lifecycle test substitutes a lightweight ``MidiClient`` double so
the real basic-pitch model never runs — the extraction algorithm itself is
covered by US-5.4 (``tests/test_midi.py``); here we verify the API/job wiring.
"""

import asyncio
import time
from pathlib import Path

import mido
import pytest
from beanie import PydanticObjectId
from fastapi.testclient import TestClient

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.models import Clip, Job, JobStatus, Workspace
from acemusic.api.services import users as user_service
from acemusic.api.settings import ApiSettings
from acemusic.storage import get_storage_backend

CLIPS_URL = f"{API_V1_PREFIX}/clips"
JOBS_URL = f"{API_V1_PREFIX}/jobs"

MIDI_LABELS = ["melody", "chords", "drums", "bass"]


def _midi_url(clip_id) -> str:
    return f"{CLIPS_URL}/{clip_id}/midi"


# ---------------------------------------------------------------------------
# Auth gate — runs in CI (no DB)
# ---------------------------------------------------------------------------


class TestAuthGate:
    @pytest.mark.parametrize("method", ["post", "get"])
    def test_missing_auth_header_returns_401(self, method: str) -> None:
        client = TestClient(create_app())
        resp = getattr(client, method)(_midi_url(PydanticObjectId()))
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Integration — real MongoDB
# ---------------------------------------------------------------------------


def _async_client(app):
    import httpx

    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


@pytest.fixture
def settings(mongo_db, mongo_settings) -> ApiSettings:
    return mongo_settings.model_copy(
        update={
            "jwt_secret_key": "test-secret-key-at-least-32-bytes-long-xx",
            "job_processor_enabled": False,
        }
    )


@pytest.fixture
async def client(settings):
    async with _async_client(create_app(settings)) as ac:
        yield ac


def _auth_headers(user, settings: ApiSettings) -> dict[str, str]:
    token = create_access_token(
        user_id=str(user.id),
        email=user.email,
        subscription_tier=user.subscription_tier,
        settings=settings,
    )
    return {"Authorization": f"Bearer {token}"}


async def _make_user(email: str):
    return await user_service.get_or_create_user(email=email, provider="google", oauth_id=f"g-{email}", name="T")


async def _make_workspace(user, name: str = "WS") -> Workspace:
    workspace = Workspace(name=name, user_id=user.id)
    await workspace.insert()
    return workspace


async def _insert_clip(
    user,
    workspace: Workspace,
    *,
    duration: float | None = 10.0,
    bpm: int | None = None,
    fmt: str | None = "wav",
    store_bytes: bytes | None = None,
    midi_paths: dict | None = None,
) -> Clip:
    clip_id = PydanticObjectId()
    file_path = f"{user.id}/{workspace.id}/clips/{clip_id}.{fmt or 'wav'}"
    if store_bytes is not None:
        get_storage_backend().upload(file_path, store_bytes)
    clip = Clip(
        id=clip_id,
        user_id=user.id,
        workspace_id=workspace.id,
        file_path=file_path,
        format=fmt,
        duration=duration,
        bpm=bpm,
        midi_paths=midi_paths,
    )
    await clip.insert()
    return clip


async def _user_with_clip(email: str, **clip_kwargs):
    user = await _make_user(email)
    workspace = await _make_workspace(user)
    clip = await _insert_clip(user, workspace, **clip_kwargs)
    return user, workspace, clip


# ---------------------------------------------------------------------------
# 404 — unknown / malformed / other-user clip ids
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestClipNotFound:
    @pytest.mark.parametrize("method", ["post", "get"])
    async def test_unknown_clip_returns_404(self, client, settings, method: str) -> None:
        user = await _make_user(f"midi-404-{method}@example.com")
        resp = await getattr(client, method)(_midi_url(PydanticObjectId()), headers=_auth_headers(user, settings))
        assert resp.status_code == 404

    @pytest.mark.parametrize("method", ["post", "get"])
    async def test_malformed_id_returns_404(self, client, settings, method: str) -> None:
        user = await _make_user(f"midi-malformed-{method}@example.com")
        resp = await getattr(client, method)(_midi_url("not-an-object-id"), headers=_auth_headers(user, settings))
        assert resp.status_code == 404

    @pytest.mark.parametrize("method", ["post", "get"])
    async def test_other_users_clip_returns_404(self, client, settings, method: str) -> None:
        _, _, clip = await _user_with_clip(f"midi-owner-{method}@example.com")
        other = await _make_user(f"midi-other-{method}@example.com")
        resp = await getattr(client, method)(_midi_url(clip.id), headers=_auth_headers(other, settings))
        assert resp.status_code == 404
        assert await Job.count() == 0


# ---------------------------------------------------------------------------
# 422 — non-wav source
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestFormatGate:
    @pytest.mark.parametrize("fmt", ["mp3", "aac", "opus", "flac"])
    async def test_non_wav_clip_returns_422(self, client, settings, fmt: str) -> None:
        user, _, clip = await _user_with_clip(f"midi-fmt-{fmt}@example.com", fmt=fmt)
        resp = await client.post(_midi_url(clip.id), headers=_auth_headers(user, settings))
        assert resp.status_code == 422
        assert fmt in resp.json()["detail"]
        assert await Job.count() == 0


# ---------------------------------------------------------------------------
# 202 — job enqueue
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestMidiEnqueue:
    async def test_returns_202_and_persists_job(self, client, settings) -> None:
        user, workspace, clip = await _user_with_clip("midi-202@example.com")
        resp = await client.post(_midi_url(clip.id), headers=_auth_headers(user, settings))
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "queued"

        jobs = await Job.find_all().to_list()
        assert len(jobs) == 1
        job = jobs[0]
        assert str(job.id) == body["job_id"]
        assert job.job_type == "midi"
        assert job.status == JobStatus.QUEUED
        assert job.workspace_id == workspace.id
        assert job.input_params == {"clip_id": str(clip.id)}


# ---------------------------------------------------------------------------
# GET — 404 when absent, URLs when present
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestGetMidi:
    async def test_get_returns_404_when_not_extracted(self, client, settings) -> None:
        user, _, clip = await _user_with_clip("midi-get-404@example.com")
        resp = await client.get(_midi_url(clip.id), headers=_auth_headers(user, settings))
        assert resp.status_code == 404

    async def test_get_returns_download_urls_after_extraction(self, client, settings, local_storage) -> None:
        user, workspace, clip = await _user_with_clip("midi-get-ok@example.com")
        # Simulate a completed extraction: files in storage + midi_paths on the clip.
        storage = get_storage_backend()
        midi_paths = {}
        for label in ("melody", "bass"):
            key = f"{user.id}/{workspace.id}/clips/{clip.id}/midi/{label}.mid"
            storage.upload(key, b"MThd")
            midi_paths[label] = key
        clip.midi_paths = midi_paths
        await clip.save()

        resp = await client.get(_midi_url(clip.id), headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        body = resp.json()
        assert body["parent_clip_id"] == str(clip.id)
        assert set(body["download_urls"]) == {"melody", "bass"}
        assert all(body["download_urls"].values())


# ---------------------------------------------------------------------------
# Cache — POST returns existing MIDI with 200 instead of enqueuing
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestMidiCache:
    async def test_post_returns_200_with_cached_midi(self, client, settings, local_storage) -> None:
        user, workspace, clip = await _user_with_clip("midi-cache@example.com")
        storage = get_storage_backend()
        key = f"{user.id}/{workspace.id}/clips/{clip.id}/midi/melody.mid"
        storage.upload(key, b"MThd")
        clip.midi_paths = {"melody": key}
        await clip.save()

        resp = await client.post(_midi_url(clip.id), headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        assert set(resp.json()["download_urls"]) == {"melody"}
        assert await Job.count() == 0

    async def test_cache_hit_works_even_for_non_wav_source(self, client, settings, local_storage) -> None:
        # The cache check precedes the wav gate: an mp3 clip that already has
        # MIDI still returns it rather than 422.
        user, workspace, clip = await _user_with_clip("midi-cache-mp3@example.com", fmt="mp3")
        storage = get_storage_backend()
        key = f"{user.id}/{workspace.id}/clips/{clip.id}/midi/melody.mid"
        storage.upload(key, b"MThd")
        clip.midi_paths = {"melody": key}
        await clip.save()

        resp = await client.post(_midi_url(clip.id), headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        assert await Job.count() == 0


# ---------------------------------------------------------------------------
# End-to-end lifecycle with a stubbed MidiClient
# ---------------------------------------------------------------------------


class _FakeMidiClient:
    """Writes minimal valid MIDI files without running basic-pitch."""

    def extract(self, audio_path, from_stems=False, stem_paths=None, progress_callback=None):
        return {label: [] for label in MIDI_LABELS}

    def save_midi(self, midi_data, output_dir, base_name, bpm=120.0):
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        paths = {}
        # Only melody and bass "have notes" — exercises the up-to-4 / subset case.
        for label in ("melody", "bass"):
            mid = mido.MidiFile(type=1)
            track = mido.MidiTrack()
            mid.tracks.append(track)
            track.append(mido.MetaMessage("track_name", name=label, time=0))
            track.append(mido.MetaMessage("end_of_track", time=0))
            path = output_dir / f"{base_name}-{label}.mid"
            mid.save(str(path))
            paths[label] = path
        return paths


@pytest.fixture
def local_storage(monkeypatch, tmp_path):
    monkeypatch.setenv("ACEMUSIC_STORAGE_BACKEND", "local")
    monkeypatch.setenv("ACEMUSIC_STORAGE_LOCAL_ROOT", str(tmp_path / "storage"))
    return tmp_path


@pytest.mark.integration
class TestMidiCleanupOnClipDelete:
    async def test_deleting_clip_removes_its_midi_objects(self, client, settings, local_storage) -> None:
        # MIDI files live under their own keys (not file_path); deleting the
        # parent clip must remove them too, not just the source audio.
        user, workspace, clip = await _user_with_clip(
            "midi-delete@example.com", store_bytes=b"RIFFsource"
        )
        storage = get_storage_backend()
        key = f"{user.id}/{workspace.id}/clips/{clip.id}/midi/melody.mid"
        storage.upload(key, b"MThd")
        clip.midi_paths = {"melody": key}
        await clip.save()

        resp = await client.delete(f"{CLIPS_URL}/{clip.id}", headers=_auth_headers(user, settings))
        assert resp.status_code == 204
        with pytest.raises(FileNotFoundError):
            storage.download(key)


@pytest.mark.integration
class TestMidiLifecycleEndToEnd:
    async def test_midi_runs_to_completed_and_stores_files_not_clips(
        self, client, settings, local_storage, write_tone, monkeypatch
    ) -> None:
        from acemusic.api.tasks import extraction as extraction_tasks
        from acemusic.api.tasks.processor import JobProcessor

        monkeypatch.setattr(extraction_tasks, "MidiClient", _FakeMidiClient)

        user = await _make_user("midi-e2e@example.com")
        workspace = await _make_workspace(user)
        tone_path = local_storage / "tone.wav"
        write_tone(tone_path, duration_s=2.0)
        clip = await _insert_clip(user, workspace, duration=2.0, bpm=120, store_bytes=tone_path.read_bytes())
        headers = _auth_headers(user, settings)
        clips_before = await Clip.count()

        accepted = await client.post(_midi_url(clip.id), headers=headers)
        assert accepted.status_code == 202
        job_id = accepted.json()["job_id"]

        processor = JobProcessor(concurrency=1, poll_interval=0.05)
        await processor.start()
        try:
            status_body = None
            deadline = time.monotonic() + 30.0
            while time.monotonic() < deadline:
                resp = await client.get(f"{JOBS_URL}/{job_id}/status", headers=headers)
                assert resp.status_code == 200
                status_body = resp.json()
                assert status_body["status"] in {"queued", "processing", "completed"}, status_body.get("error")
                if status_body["status"] == "completed":
                    break
                await asyncio.sleep(0.05)
        finally:
            await processor.stop()
        assert status_body is not None and status_body["status"] == "completed", "midi job never completed"

        # AC: job status is trackable through completion — the completed MIDI job
        # surfaces resolved download URLs (not raw storage keys, and not clips).
        assert set(status_body["midi_download_urls"]) == {"melody", "bass"}
        assert "clip_ids" not in status_body  # excluded when None

        # AC: downloadable .mid files, and NOT clip records (no new clips created).
        assert await Clip.count() == clips_before
        reloaded = await Clip.get(clip.id)
        assert set(reloaded.midi_paths) == {"melody", "bass"}

        get_resp = await client.get(_midi_url(clip.id), headers=headers)
        assert get_resp.status_code == 200
        urls = get_resp.json()["download_urls"]
        assert set(urls) == {"melody", "bass"}
        # The resolved local-storage URL points at a real .mid file on disk.
        for url in urls.values():
            assert Path(url).read_bytes().startswith(b"MThd")
