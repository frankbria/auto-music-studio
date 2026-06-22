"""Tests for the DAW-export endpoints (US-14.1, issue #138).

Covers ``POST /clips/{id}/export/daw`` (enqueue a bundle build) and
``GET /clips/{id}/export/daw`` (download the assembled ZIP). The 401 auth-gate
and the pure ``assemble_daw_bundle`` test run in CI (no DB); the rest are
``integration`` and drive the real app with ``httpx.AsyncClient`` over a local
MongoDB.

The end-to-end tests substitute lightweight stem/MIDI client doubles so the real
demucs / basic-pitch models never run — those algorithms are covered by US-5.3 /
US-5.4 and the extraction wiring by US-10.2; here we verify the bundle assembly,
the cache-reuse (no re-extraction), and the download.
"""

import asyncio
import io
import json
import time
import types
import zipfile
from pathlib import Path

import mido
import numpy as np
import pytest
import soundfile as sf
from beanie import PydanticObjectId
from fastapi.testclient import TestClient

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.models import Clip, Job, JobStatus, Workspace
from acemusic.api.services import users as user_service
from acemusic.api.services.daw_export import export_storage_path
from acemusic.api.settings import ApiSettings
from acemusic.daw_export import CANONICAL_STEMS, assemble_daw_bundle
from acemusic.midi_client import CHANNEL_MAP, MIDI_OUTPUT_LABELS
from acemusic.stems_client import STEM_LABELS
from acemusic.storage import get_storage_backend

CLIPS_URL = f"{API_V1_PREFIX}/clips"
JOBS_URL = f"{API_V1_PREFIX}/jobs"


def _daw_url(clip_id) -> str:
    return f"{CLIPS_URL}/{clip_id}/export/daw"


def _tone_bytes(duration_s: float = 0.5, sample_rate: int = 44100) -> bytes:
    tone = (
        0.2 * np.sin(2 * np.pi * 220 * np.linspace(0, duration_s, int(sample_rate * duration_s), endpoint=False))
    ).astype(np.float32)
    buf = io.BytesIO()
    sf.write(buf, np.column_stack([tone, tone]), sample_rate, format="WAV")
    return buf.getvalue()


def _midi_bytes(name: str, bpm: float = 120.0) -> bytes:
    mid = mido.MidiFile(type=1)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm), time=0))
    track.append(mido.MetaMessage("track_name", name=name, time=0))
    track.append(mido.MetaMessage("end_of_track", time=0))
    buf = io.BytesIO()
    mid.save(file=buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Pure assembly — runs in CI (no DB, no ffmpeg: wav/midi are copied, not transcoded)
# ---------------------------------------------------------------------------


class TestAssembleBundle:
    def test_zip_structure_and_project_json(self, tmp_path) -> None:
        clip = types.SimpleNamespace(
            id="abc123",
            title="My Song",
            bpm=128,
            key="C minor",
            duration=12.5,
            lyrics="la la la",
            style_tags=["synthwave", "dreamy"],
            model="ace-step-v1",
            seed=42,
        )
        stem_paths = {}
        for label in CANONICAL_STEMS:
            p = tmp_path / f"{label}.wav"
            p.write_bytes(_tone_bytes())
            stem_paths[label] = p
        midi_paths = {}
        for label in MIDI_OUTPUT_LABELS:
            p = tmp_path / f"{label}.mid"
            p.write_bytes(_midi_bytes(label, bpm=128))
            midi_paths[label] = p

        full_mix = tmp_path / "full_mix.wav"
        full_mix.write_bytes(_tone_bytes())

        out = tmp_path / "bundle.zip"
        assemble_daw_bundle(clip, full_mix_path=full_mix, stem_paths=stem_paths, midi_paths=midi_paths, output_path=out)

        with zipfile.ZipFile(out) as zf:
            names = set(zf.namelist())
            root = "my-song_Export"
            expected = {f"{root}/audio/full_mix.wav", f"{root}/project.json", f"{root}/artwork.jpg"}
            expected |= {f"{root}/audio/{s}.wav" for s in CANONICAL_STEMS}
            expected |= {f"{root}/midi/{m}.mid" for m in MIDI_OUTPUT_LABELS}
            assert expected <= names

            meta = json.loads(zf.read(f"{root}/project.json"))

        assert meta["bpm"] == 128
        assert meta["key"] == "C minor"
        assert meta["duration_seconds"] == 12.5
        assert meta["lyrics"] == "la la la"
        assert meta["style_tags"] == ["synthwave", "dreamy"]
        assert meta["source_model"] == "ace-step-v1"
        assert meta["generation_seed"] == 42
        assert meta["time_signature"] is None
        # MIDI channel assignments mirror CHANNEL_MAP (importable into a DAW).
        assert {m["name"]: m["channel"] for m in meta["midi_files"]} == CHANNEL_MAP
        assert {s["name"] for s in meta["stems"]} == set(CANONICAL_STEMS)

    def test_incomplete_set_raises(self, tmp_path) -> None:
        clip = types.SimpleNamespace(
            id="x", title="t", bpm=None, key=None, duration=None, lyrics=None, style_tags=None, model=None, seed=None
        )
        full = tmp_path / "full.wav"
        full.write_bytes(_tone_bytes())
        with pytest.raises(ValueError, match="missing"):
            assemble_daw_bundle(clip, full_mix_path=full, stem_paths={}, midi_paths={}, output_path=tmp_path / "b.zip")


# ---------------------------------------------------------------------------
# Auth gate — runs in CI (no DB; plain TestClient does not run the lifespan)
# ---------------------------------------------------------------------------


class TestAuthGate:
    @pytest.mark.parametrize("method", ["post", "get"])
    def test_missing_auth_header_returns_401(self, method: str) -> None:
        client = TestClient(create_app())
        resp = getattr(client, method)(_daw_url(PydanticObjectId()))
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


@pytest.fixture
def local_storage(monkeypatch, tmp_path):
    monkeypatch.setenv("ACEMUSIC_STORAGE_BACKEND", "local")
    monkeypatch.setenv("ACEMUSIC_STORAGE_LOCAL_ROOT", str(tmp_path / "storage"))
    return tmp_path


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
    user, workspace, *, title="Song", duration=10.0, bpm=120, key="C", fmt="wav", store_bytes=None, is_public=False
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
        title=title,
        format=fmt,
        duration=duration,
        bpm=bpm,
        key=key,
        is_public=is_public,
    )
    await clip.insert()
    return clip


async def _user_with_clip(email: str, **clip_kwargs):
    user = await _make_user(email)
    workspace = await _make_workspace(user)
    clip = await _insert_clip(user, workspace, **clip_kwargs)
    return user, workspace, clip


async def _seed_cached_stems(user, workspace, parent: Clip) -> list[Clip]:
    """Pre-create the 4 stem child clips with real WAV bytes in storage."""
    children = []
    for label in STEM_LABELS:
        cid = PydanticObjectId()
        path = f"{user.id}/{workspace.id}/clips/{cid}.wav"
        get_storage_backend().upload(path, _tone_bytes())
        child = Clip(
            id=cid,
            user_id=parent.user_id,
            workspace_id=parent.workspace_id,
            file_path=path,
            title=label,
            format="wav",
            duration=parent.duration,
            parent_clip_ids=[parent.id],
            generation_mode="stems",
        )
        await child.insert()
        children.append(child)
    return children


async def _seed_cached_midi(user, workspace, clip: Clip) -> None:
    """Attach the 4 MIDI files to the clip's midi_paths with real bytes in storage."""
    storage = get_storage_backend()
    midi_paths = {}
    for label in MIDI_OUTPUT_LABELS:
        key = f"{user.id}/{workspace.id}/clips/{clip.id}/midi/{label}.mid"
        storage.upload(key, _midi_bytes(label, bpm=clip.bpm or 120))
        midi_paths[label] = key
    clip.midi_paths = midi_paths
    await clip.save()


# ---------------------------------------------------------------------------
# 404 — unknown / malformed / other-user clip ids (POST creates no job)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestClipNotFound:
    @pytest.mark.parametrize("method", ["post", "get"])
    async def test_unknown_clip_returns_404(self, client, settings, method: str) -> None:
        user = await _make_user(f"daw-404-{method}@example.com")
        resp = await getattr(client, method)(_daw_url(PydanticObjectId()), headers=_auth_headers(user, settings))
        assert resp.status_code == 404

    @pytest.mark.parametrize("method", ["post", "get"])
    async def test_malformed_id_returns_404(self, client, settings, method: str) -> None:
        user = await _make_user(f"daw-malformed-{method}@example.com")
        resp = await getattr(client, method)(_daw_url("not-an-object-id"), headers=_auth_headers(user, settings))
        assert resp.status_code == 404

    async def test_other_users_clip_returns_404_on_post(self, client, settings) -> None:
        _, _, clip = await _user_with_clip("daw-owner@example.com")
        other = await _make_user("daw-other@example.com")
        resp = await client.post(_daw_url(clip.id), headers=_auth_headers(other, settings))
        assert resp.status_code == 404
        assert await Job.count() == 0


# ---------------------------------------------------------------------------
# 202 — job enqueue (always async, even when cached)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestEnqueue:
    async def test_returns_202_and_persists_job(self, client, settings) -> None:
        user, workspace, clip = await _user_with_clip("daw-202@example.com")
        resp = await client.post(_daw_url(clip.id), headers=_auth_headers(user, settings))
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "queued"

        jobs = await Job.find_all().to_list()
        assert len(jobs) == 1
        job = jobs[0]
        assert str(job.id) == body["job_id"]
        assert job.job_type == "daw_export"
        assert job.status == JobStatus.QUEUED
        assert job.user_id == user.id
        assert job.workspace_id == workspace.id
        assert job.input_params == {"clip_id": str(clip.id)}

    @pytest.mark.parametrize("fmt", ["mp3", "flac"])
    async def test_non_wav_clip_returns_422(self, client, settings, fmt: str) -> None:
        # The server has no ffmpeg to transcode the full mix to wav, so a
        # compressed source is rejected up front rather than failing the job.
        user, _, clip = await _user_with_clip(f"daw-fmt-{fmt}@example.com", fmt=fmt)
        resp = await client.post(_daw_url(clip.id), headers=_auth_headers(user, settings))
        assert resp.status_code == 422
        assert fmt in resp.json()["detail"]
        assert await Job.count() == 0


# ---------------------------------------------------------------------------
# Clip deletion removes the orphan-able export bundle (US-14.1)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDeleteCleansExport:
    async def test_deleting_clip_removes_its_daw_export(self, settings, local_storage) -> None:
        from acemusic.api.services import clips as clip_service

        user, workspace, clip = await _user_with_clip("daw-del@example.com")
        storage = get_storage_backend()
        export_key = export_storage_path(user.id, workspace.id, clip.id)
        storage.upload(export_key, b"PK-bundle")

        await clip_service.delete_clip(str(clip.id), str(user.id))

        with pytest.raises(FileNotFoundError):
            storage.download(export_key)


# ---------------------------------------------------------------------------
# GET — 404 until built; visibility rules
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDownload:
    async def test_get_returns_404_when_not_exported(self, client, settings, local_storage) -> None:
        user, _, clip = await _user_with_clip("daw-get-404@example.com")
        resp = await client.get(_daw_url(clip.id), headers=_auth_headers(user, settings))
        assert resp.status_code == 404

    async def test_get_returns_zip_when_present(self, client, settings, local_storage) -> None:
        user, workspace, clip = await _user_with_clip("daw-get-ok@example.com", title="Cool Track")
        export_path = export_storage_path(user.id, workspace.id, clip.id)
        get_storage_backend().upload(export_path, b"PK\x03\x04 zip-bytes")

        resp = await client.get(_daw_url(clip.id), headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/zip"
        assert resp.headers["content-disposition"] == 'attachment; filename="cool-track_Export.zip"'
        assert resp.content == b"PK\x03\x04 zip-bytes"

    async def test_other_users_private_clip_returns_403(self, client, settings, local_storage) -> None:
        user, workspace, clip = await _user_with_clip("daw-priv-owner@example.com")
        get_storage_backend().upload(export_storage_path(user.id, workspace.id, clip.id), b"PK")
        other = await _make_user("daw-priv-other@example.com")
        resp = await client.get(_daw_url(clip.id), headers=_auth_headers(other, settings))
        assert resp.status_code == 403

    async def test_public_clip_export_downloadable_by_other_user(self, client, settings, local_storage) -> None:
        user, workspace, clip = await _user_with_clip("daw-pub-owner@example.com", is_public=True)
        get_storage_backend().upload(export_storage_path(user.id, workspace.id, clip.id), b"PK-public")
        other = await _make_user("daw-pub-other@example.com")
        resp = await client.get(_daw_url(clip.id), headers=_auth_headers(other, settings))
        assert resp.status_code == 200
        assert resp.content == b"PK-public"


# ---------------------------------------------------------------------------
# End-to-end with stubbed clients
# ---------------------------------------------------------------------------


class _ExplodingStemsClient:
    def __init__(self, *a, **k):
        raise AssertionError("StemsClient must not run when stems are cached")


class _ExplodingMidiClient:
    def __init__(self, *a, **k):
        raise AssertionError("MidiClient must not run when MIDI is cached")


class _FakeStemsClient:
    model_samplerate = 44100

    def separate(self, audio_path, progress_callback=None):
        return {label: label for label in STEM_LABELS}

    def save_stems(self, stems, output_dir, base_name, sample_rate=44100, output_format="wav"):
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        paths = {}
        for label in STEM_LABELS:
            path = output_dir / f"{base_name}-{label}.{output_format}"
            path.write_bytes(_tone_bytes())
            paths[label] = path
        return paths


class _FakeMidiClient:
    def extract(self, audio_path, from_stems=False, stem_paths=None, progress_callback=None):
        return {label: [] for label in MIDI_OUTPUT_LABELS}

    def save_midi(self, midi_data, output_dir, base_name, bpm=120.0):
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        paths = {}
        for label in MIDI_OUTPUT_LABELS:
            path = output_dir / f"{base_name}-{label}.mid"
            path.write_bytes(_midi_bytes(label, bpm=bpm))
            paths[label] = path
        return paths


async def _run_to_completion(client, settings, job_id, headers) -> dict:
    from acemusic.api.tasks.processor import JobProcessor

    processor = JobProcessor(concurrency=1, poll_interval=0.05)
    await processor.start()
    try:
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            resp = await client.get(f"{JOBS_URL}/{job_id}/status", headers=headers)
            assert resp.status_code == 200
            body = resp.json()
            assert body["status"] in {"queued", "processing", "completed"}, body.get("error")
            if body["status"] == "completed":
                return body
            await asyncio.sleep(0.05)
    finally:
        await processor.stop()
    raise AssertionError("daw_export job never completed")


@pytest.mark.integration
class TestLifecycleEndToEnd:
    async def test_cached_stems_and_midi_reused_without_re_extraction(
        self, client, settings, local_storage, monkeypatch
    ) -> None:
        from acemusic.api.tasks import extraction as extraction_tasks

        # Prove no re-extraction: instantiating either client fails the job.
        monkeypatch.setattr(extraction_tasks, "StemsClient", _ExplodingStemsClient)
        monkeypatch.setattr(extraction_tasks, "MidiClient", _ExplodingMidiClient)

        user = await _make_user("daw-cached@example.com")
        workspace = await _make_workspace(user)
        clip = await _insert_clip(user, workspace, title="Reused Mix", bpm=120, store_bytes=_tone_bytes())
        await _seed_cached_stems(user, workspace, clip)
        await _seed_cached_midi(user, workspace, clip)
        headers = _auth_headers(user, settings)

        accepted = await client.post(_daw_url(clip.id), headers=headers)
        assert accepted.status_code == 202
        await _run_to_completion(client, settings, accepted.json()["job_id"], headers)

        # No new stem children were created (cache was reused, not regenerated).
        stem_children = await Clip.find(Clip.generation_mode == "stems").to_list()
        assert len(stem_children) == len(STEM_LABELS)

        resp = await client.get(_daw_url(clip.id), headers=headers)
        assert resp.status_code == 200
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            names = set(zf.namelist())
            root = "reused-mix_Export"
            assert f"{root}/audio/full_mix.wav" in names
            assert {f"{root}/audio/{s}.wav" for s in CANONICAL_STEMS} <= names
            assert {f"{root}/midi/{m}.mid" for m in MIDI_OUTPUT_LABELS} <= names
            meta = json.loads(zf.read(f"{root}/project.json"))
            assert meta["bpm"] == 120
            assert {m["name"]: m["channel"] for m in meta["midi_files"]} == CHANNEL_MAP

    async def test_triggers_extraction_when_not_cached(self, client, settings, local_storage, monkeypatch) -> None:
        from acemusic.api.tasks import extraction as extraction_tasks

        monkeypatch.setattr(extraction_tasks, "StemsClient", _FakeStemsClient)
        monkeypatch.setattr(extraction_tasks, "MidiClient", _FakeMidiClient)

        user = await _make_user("daw-fresh@example.com")
        workspace = await _make_workspace(user)
        clip = await _insert_clip(user, workspace, title="Fresh Mix", bpm=90, store_bytes=_tone_bytes())
        headers = _auth_headers(user, settings)

        accepted = await client.post(_daw_url(clip.id), headers=headers)
        assert accepted.status_code == 202
        await _run_to_completion(client, settings, accepted.json()["job_id"], headers)

        # Extraction ran: 4 stem children linked to the source, midi_paths populated.
        stem_children = await Clip.find(Clip.generation_mode == "stems").to_list()
        assert {c.title for c in stem_children} == set(STEM_LABELS)
        assert all(c.parent_clip_ids == [clip.id] for c in stem_children)
        reloaded = await Clip.get(clip.id)
        assert set(reloaded.midi_paths or {}) == set(MIDI_OUTPUT_LABELS)

        resp = await client.get(_daw_url(clip.id), headers=headers)
        assert resp.status_code == 200
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            root = "fresh-mix_Export"
            assert f"{root}/project.json" in zf.namelist()
