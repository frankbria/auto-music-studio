"""Tests for the batch processing endpoints (US-10.5, issue #85).

Covers ``POST /batch/stems``, ``POST /batch/export`` (enqueue one sub-job per
clip) and ``GET /batch/{id}/status`` (aggregate progress + per-clip breakdown).

The auth-gate and request-validation tests run in CI (no DB; plain ``TestClient``
does not run the lifespan, and ``get_current_user`` only decodes the token). The
rest are ``integration`` and drive the real app with ``httpx.AsyncClient`` over a
local MongoDB. The lifecycle tests substitute lightweight doubles for the
demucs ``StemsClient`` and the ffmpeg-backed ``export_audio`` so neither real
dependency runs — the algorithms are covered elsewhere; here we verify the
batch/job wiring.
"""

import asyncio
import time
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from beanie import PydanticObjectId
from fastapi.testclient import TestClient

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.models import BatchJob, Clip, Job, Workspace
from acemusic.api.services import users as user_service
from acemusic.api.settings import ApiSettings
from acemusic.storage import get_storage_backend

BATCH_URL = f"{API_V1_PREFIX}/batch"
STEM_LABELS = ["drums", "bass", "other", "vocals"]

_CI_SECRET = "test-secret-key-at-least-32-bytes-long-xx"


def _stems_url() -> str:
    return f"{BATCH_URL}/stems"


def _export_url() -> str:
    return f"{BATCH_URL}/export"


def _status_url(batch_id) -> str:
    return f"{BATCH_URL}/{batch_id}/status"


# ---------------------------------------------------------------------------
# Auth gate + request validation — run in CI (no DB)
# ---------------------------------------------------------------------------


class TestAuthGate:
    def test_stems_missing_auth_returns_401(self) -> None:
        client = TestClient(create_app())
        resp = client.post(_stems_url(), json={"clip_ids": [str(PydanticObjectId())]})
        assert resp.status_code == 401

    def test_export_missing_auth_returns_401(self) -> None:
        client = TestClient(create_app())
        resp = client.post(_export_url(), json={"clip_ids": [str(PydanticObjectId())], "format": "mp3"})
        assert resp.status_code == 401

    def test_status_missing_auth_returns_401(self) -> None:
        client = TestClient(create_app())
        resp = client.get(_status_url(PydanticObjectId()))
        assert resp.status_code == 401


class TestRequestValidation:
    """Pydantic rejects bad envelopes before any DB/service work (CI-safe)."""

    def _client(self):
        settings = ApiSettings().model_copy(update={"jwt_secret_key": _CI_SECRET})
        token = create_access_token(
            user_id=str(PydanticObjectId()), email="ci@example.com", subscription_tier="free", settings=settings
        )
        return TestClient(create_app(settings)), {"Authorization": f"Bearer {token}"}

    def test_more_than_50_clips_returns_422(self) -> None:
        # AC: requesting more than 50 clips returns 422.
        client, headers = self._client()
        clip_ids = [str(PydanticObjectId()) for _ in range(51)]
        resp = client.post(_stems_url(), json={"clip_ids": clip_ids}, headers=headers)
        assert resp.status_code == 422

    def test_export_more_than_50_clips_returns_422(self) -> None:
        client, headers = self._client()
        clip_ids = [str(PydanticObjectId()) for _ in range(51)]
        resp = client.post(_export_url(), json={"clip_ids": clip_ids, "format": "mp3"}, headers=headers)
        assert resp.status_code == 422

    def test_empty_clip_list_returns_422(self) -> None:
        client, headers = self._client()
        resp = client.post(_stems_url(), json={"clip_ids": []}, headers=headers)
        assert resp.status_code == 422

    def test_duplicate_clip_ids_returns_422(self) -> None:
        client, headers = self._client()
        dup = str(PydanticObjectId())
        resp = client.post(_stems_url(), json={"clip_ids": [dup, dup]}, headers=headers)
        assert resp.status_code == 422

    def test_export_unsupported_format_returns_422(self) -> None:
        client, headers = self._client()
        resp = client.post(
            _export_url(), json={"clip_ids": [str(PydanticObjectId())], "format": "ogg"}, headers=headers
        )
        assert resp.status_code == 422

    def test_export_missing_format_returns_422(self) -> None:
        client, headers = self._client()
        resp = client.post(_export_url(), json={"clip_ids": [str(PydanticObjectId())]}, headers=headers)
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Integration — real MongoDB
# ---------------------------------------------------------------------------


def _async_client(app):
    import httpx

    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


@pytest.fixture
def settings(mongo_db, mongo_settings) -> ApiSettings:
    # Disable the background processor by default: enqueue tests assert on the
    # queued sub-jobs and do not want a worker claiming them. The lifecycle
    # tests start their own processor explicitly.
    return mongo_settings.model_copy(update={"jwt_secret_key": _CI_SECRET, "job_processor_enabled": False})


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
        user_id=str(user.id), email=user.email, subscription_tier=user.subscription_tier, settings=settings
    )
    return {"Authorization": f"Bearer {token}"}


async def _make_user(email: str):
    return await user_service.get_or_create_user(email=email, provider="google", oauth_id=f"g-{email}", name="T")


async def _make_workspace(user, name: str = "WS") -> Workspace:
    workspace = Workspace(name=name, user_id=user.id)
    await workspace.insert()
    return workspace


async def _insert_clip(user, workspace, *, fmt: str | None = "wav", store_bytes: bytes | None = None) -> Clip:
    clip_id = PydanticObjectId()
    file_path = f"{user.id}/{workspace.id}/clips/{clip_id}.{fmt or 'wav'}"
    if store_bytes is not None:
        get_storage_backend().upload(file_path, store_bytes)
    clip = Clip(
        id=clip_id, user_id=user.id, workspace_id=workspace.id, file_path=file_path, format=fmt, duration=2.0, bpm=120
    )
    await clip.insert()
    return clip


async def _poll_batch(client, batch_id, headers, *, until=("completed", "failed", "partial_success"), timeout=30.0):
    from acemusic.api.tasks.processor import JobProcessor

    processor = JobProcessor(concurrency=2, poll_interval=0.05)
    await processor.start()
    try:
        body = None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            resp = await client.get(_status_url(batch_id), headers=headers)
            assert resp.status_code == 200
            body = resp.json()
            if body["overall_status"] in until:
                break
            await asyncio.sleep(0.05)
    finally:
        await processor.stop()
    return body


# --- stems: enqueue --------------------------------------------------------


@pytest.mark.integration
class TestBatchStemsEnqueue:
    async def test_returns_202_with_a_subjob_per_clip(self, client, settings) -> None:
        user = await _make_user("batch-stems-202@example.com")
        ws = await _make_workspace(user)
        clips = [await _insert_clip(user, ws) for _ in range(3)]
        ids = [str(c.id) for c in clips]

        resp = await client.post(_stems_url(), json={"clip_ids": ids}, headers=_auth_headers(user, settings))
        assert resp.status_code == 202
        body = resp.json()
        assert len(body["sub_job_ids"]) == 3

        batch = await BatchJob.get(PydanticObjectId(body["batch_job_id"]))
        assert batch is not None and batch.operation == "stems"
        assert [e.clip_id for e in batch.entries] == ids
        # Each valid clip got a real queued stems sub-job.
        jobs = await Job.find_all().to_list()
        assert {j.job_type for j in jobs} == {"stems"}
        assert len(jobs) == 3

    async def test_unknown_clip_becomes_failed_entry_without_aborting(self, client, settings) -> None:
        # AC: individual failures do not halt the batch.
        user = await _make_user("batch-stems-mixed@example.com")
        ws = await _make_workspace(user)
        good = await _insert_clip(user, ws)
        bogus = str(PydanticObjectId())

        resp = await client.post(
            _stems_url(), json={"clip_ids": [str(good.id), bogus]}, headers=_auth_headers(user, settings)
        )
        assert resp.status_code == 202
        assert len(resp.json()["sub_job_ids"]) == 1  # only the good clip queued

        body = await client.get(_status_url(resp.json()["batch_job_id"]), headers=_auth_headers(user, settings))
        data = body.json()
        assert data["total"] == 2
        by_clip = {s["clip_id"]: s for s in data["sub_jobs"]}
        assert by_clip[bogus]["status"] == "failed"
        assert by_clip[str(good.id)]["status"] in {"queued", "processing"}

    async def test_non_wav_clip_becomes_failed_entry(self, client, settings) -> None:
        user = await _make_user("batch-stems-nonwav@example.com")
        ws = await _make_workspace(user)
        mp3 = await _insert_clip(user, ws, fmt="mp3")

        resp = await client.post(_stems_url(), json={"clip_ids": [str(mp3.id)]}, headers=_auth_headers(user, settings))
        assert resp.status_code == 202
        assert resp.json()["sub_job_ids"] == []
        assert await Job.count() == 0  # no sub-job queued for the bad clip
        batch = await BatchJob.get(PydanticObjectId(resp.json()["batch_job_id"]))
        assert "mp3" in (batch.entries[0].error or "")

    async def test_50_clips_is_accepted(self, client, settings) -> None:
        # The 50-clip boundary is allowed (51 is rejected by validation, tested
        # in CI). Unknown ids become failed entries, so this also exercises the
        # all-unknown path returning 202 rather than erroring.
        user = await _make_user("batch-stems-50@example.com")
        ids = [str(PydanticObjectId()) for _ in range(50)]
        resp = await client.post(_stems_url(), json={"clip_ids": ids}, headers=_auth_headers(user, settings))
        assert resp.status_code == 202
        batch = await BatchJob.get(PydanticObjectId(resp.json()["batch_job_id"]))
        assert len(batch.entries) == 50


# --- status: ownership -----------------------------------------------------


@pytest.mark.integration
class TestBatchStatusOwnership:
    async def test_unknown_batch_returns_404(self, client, settings) -> None:
        user = await _make_user("batch-status-404@example.com")
        resp = await client.get(_status_url(PydanticObjectId()), headers=_auth_headers(user, settings))
        assert resp.status_code == 404

    async def test_malformed_batch_id_returns_404(self, client, settings) -> None:
        user = await _make_user("batch-status-malformed@example.com")
        resp = await client.get(_status_url("not-an-id"), headers=_auth_headers(user, settings))
        assert resp.status_code == 404

    async def test_other_users_batch_returns_404(self, client, settings) -> None:
        owner = await _make_user("batch-owner@example.com")
        ws = await _make_workspace(owner)
        clip = await _insert_clip(owner, ws)
        created = await client.post(
            _stems_url(), json={"clip_ids": [str(clip.id)]}, headers=_auth_headers(owner, settings)
        )
        batch_id = created.json()["batch_job_id"]

        other = await _make_user("batch-intruder@example.com")
        resp = await client.get(_status_url(batch_id), headers=_auth_headers(other, settings))
        assert resp.status_code == 404


# --- lifecycle: stems with a stubbed StemsClient ---------------------------


class _FakeStemsClient:
    """Writes four short WAV stems without running demucs."""

    model_samplerate = 44100

    def separate(self, audio_path, progress_callback=None):
        return {label: label for label in STEM_LABELS}

    def save_stems(self, stems, output_dir, base_name, sample_rate=44100, output_format="wav"):
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        tone = (0.2 * np.sin(2 * np.pi * 220 * np.linspace(0, 0.5, int(sample_rate * 0.5), endpoint=False))).astype(
            np.float32
        )
        paths = {}
        for label in STEM_LABELS:
            path = output_dir / f"{base_name}-{label}.{output_format}"
            sf.write(str(path), np.column_stack([tone, tone]), sample_rate)
            paths[label] = path
        return paths


@pytest.mark.integration
class TestBatchStemsLifecycle:
    async def test_partial_success_one_completes_one_fails(
        self, client, settings, local_storage, write_tone, monkeypatch
    ) -> None:
        # AC: batch stems tracks individual status and reports partial success.
        from acemusic.api.tasks import extraction as extraction_tasks

        monkeypatch.setattr(extraction_tasks, "StemsClient", _FakeStemsClient)

        user = await _make_user("batch-stems-partial@example.com")
        ws = await _make_workspace(user)
        tone_path = local_storage / "tone.wav"
        write_tone(tone_path, duration_s=2.0)
        good = await _insert_clip(user, ws, store_bytes=tone_path.read_bytes())
        bogus = str(PydanticObjectId())
        headers = _auth_headers(user, settings)

        created = await client.post(_stems_url(), json={"clip_ids": [str(good.id), bogus]}, headers=headers)
        batch_id = created.json()["batch_job_id"]

        body = await _poll_batch(client, batch_id, headers)
        assert body["overall_status"] == "partial_success", body
        assert body["completed_count"] == 1
        assert body["failed_count"] == 1
        assert body["overall_progress"] == 1.0

        by_clip = {s["clip_id"]: s for s in body["sub_jobs"]}
        assert by_clip[bogus]["status"] == "failed"
        completed = by_clip[str(good.id)]
        assert completed["status"] == "completed"
        assert len(completed["clip_ids"]) == 4  # four stem clips


# --- lifecycle: export with a stubbed export_audio -------------------------


def _fake_export_audio(src, dest, fmt):
    Path(dest).write_bytes(b"FAKE-EXPORT-" + fmt.encode())
    return Path(dest)


@pytest.mark.integration
class TestBatchExportLifecycle:
    async def test_export_runs_to_completed_with_download_urls(
        self, client, settings, local_storage, write_tone, monkeypatch
    ) -> None:
        # AC: batch export produces files for all clips in the requested format.
        from acemusic.api.tasks import export as export_tasks

        monkeypatch.setattr(export_tasks, "export_audio", _fake_export_audio)

        user = await _make_user("batch-export-e2e@example.com")
        ws = await _make_workspace(user)
        tone_path = local_storage / "tone.wav"
        write_tone(tone_path, duration_s=2.0)
        clips = [await _insert_clip(user, ws, store_bytes=tone_path.read_bytes()) for _ in range(2)]
        headers = _auth_headers(user, settings)

        created = await client.post(
            _export_url(), json={"clip_ids": [str(c.id) for c in clips], "format": "mp3"}, headers=headers
        )
        assert created.status_code == 202
        batch_id = created.json()["batch_job_id"]

        body = await _poll_batch(client, batch_id, headers)
        assert body["overall_status"] == "completed", body
        assert body["completed_count"] == 2
        for sub in body["sub_jobs"]:
            assert sub["status"] == "completed"
            assert sub["download_url"]  # exported file is retrievable

        # The export objects were actually written to storage.
        jobs = await Job.find(Job.job_type == "export").to_list()
        storage = get_storage_backend()
        for job in jobs:
            assert storage.download((job.result or {})["export_path"]).startswith(b"FAKE-EXPORT-")

    async def test_non_wav_clip_is_queued_for_export(self, client, settings) -> None:
        # Unlike stems (wav-only), export transcodes any generated format, so an
        # mp3 clip is queued — not recorded as a failed entry.
        user = await _make_user("batch-export-nonwav@example.com")
        ws = await _make_workspace(user)
        mp3 = await _insert_clip(user, ws, fmt="mp3")

        resp = await client.post(
            _export_url(), json={"clip_ids": [str(mp3.id)], "format": "flac"}, headers=_auth_headers(user, settings)
        )
        assert resp.status_code == 202
        assert len(resp.json()["sub_job_ids"]) == 1
        jobs = await Job.find(Job.job_type == "export").to_list()
        assert len(jobs) == 1 and jobs[0].input_params["clip_id"] == str(mp3.id)

    async def test_real_transcode_decodes_non_wav_source(self, client, settings, local_storage, write_tone) -> None:
        # Proves the source-extension fix: a real mp3 source decodes through
        # ffmpeg and exports to flac (uses the real export_audio, no stub).
        # Shells out to ffmpeg, which CI lacks — skip there (matches test_audio.py).
        import shutil

        if shutil.which("ffmpeg") is None:
            pytest.skip("ffmpeg not installed; required for real transcode")

        from pydub import AudioSegment

        user = await _make_user("batch-export-real-mp3@example.com")
        ws = await _make_workspace(user)
        tone_path = local_storage / "tone.wav"
        write_tone(tone_path, duration_s=1.0)
        mp3_path = local_storage / "tone.mp3"
        AudioSegment.from_file(str(tone_path), format="wav").export(str(mp3_path), format="mp3")
        clip = await _insert_clip(user, ws, fmt="mp3", store_bytes=mp3_path.read_bytes())
        headers = _auth_headers(user, settings)

        created = await client.post(_export_url(), json={"clip_ids": [str(clip.id)], "format": "flac"}, headers=headers)
        batch_id = created.json()["batch_job_id"]

        body = await _poll_batch(client, batch_id, headers)
        assert body["overall_status"] == "completed", body
        sub = body["sub_jobs"][0]
        assert sub["status"] == "completed" and sub["download_url"]
        job = (await Job.find(Job.job_type == "export").to_list())[0]
        data = get_storage_backend().download((job.result or {})["export_path"])
        assert data[:4] == b"fLaC"  # valid FLAC stream marker
