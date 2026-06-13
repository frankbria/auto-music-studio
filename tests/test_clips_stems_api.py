"""Tests for the stem-separation endpoints (US-10.2, issue #82).

Covers ``POST /clips/{id}/stems`` (enqueue or cache-hit) and
``GET /clips/{id}/stems`` (retrieve stem clip ids). The 401 auth-gate test runs
in CI (no DB); the rest are ``integration`` and drive the real app with
``httpx.AsyncClient`` over a local MongoDB.

The end-to-end lifecycle test substitutes a lightweight ``StemsClient`` double so
the real demucs model never runs — the separation algorithm itself is covered by
US-5.3 (``tests/test_stems.py``); here we verify the API/job wiring.
"""

import asyncio
import time

import numpy as np
import pytest
import soundfile as sf
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

STEM_LABELS = ["drums", "bass", "other", "vocals"]


def _stems_url(clip_id) -> str:
    return f"{CLIPS_URL}/{clip_id}/stems"


# ---------------------------------------------------------------------------
# Auth gate — runs in CI (no DB; plain TestClient does not run the lifespan)
# ---------------------------------------------------------------------------


class TestAuthGate:
    @pytest.mark.parametrize("method", ["post", "get"])
    def test_missing_auth_header_returns_401(self, method: str) -> None:
        client = TestClient(create_app())
        resp = getattr(client, method)(_stems_url(PydanticObjectId()))
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
    # Disable the background processor by default: most tests assert on the
    # queued job record and do not want a worker claiming it. The lifecycle
    # test starts its own processor explicitly.
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
    key: str | None = None,
    fmt: str | None = "wav",
    store_bytes: bytes | None = None,
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
        key=key,
    )
    await clip.insert()
    return clip


async def _user_with_clip(email: str, **clip_kwargs):
    user = await _make_user(email)
    workspace = await _make_workspace(user)
    clip = await _insert_clip(user, workspace, **clip_kwargs)
    return user, workspace, clip


async def _insert_stem_children(parent: Clip, labels=STEM_LABELS) -> list[Clip]:
    """Pre-create the 4 stem child clips, as a completed separation would."""
    children = []
    for label in labels:
        child = Clip(
            user_id=parent.user_id,
            workspace_id=parent.workspace_id,
            file_path=f"{parent.user_id}/{parent.workspace_id}/clips/{PydanticObjectId()}.wav",
            title=label,
            format="wav",
            duration=parent.duration,
            parent_clip_ids=[parent.id],
            generation_mode="stems",
        )
        await child.insert()
        children.append(child)
    return children


# ---------------------------------------------------------------------------
# 404 — unknown / malformed / other-user clip ids
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestClipNotFound:
    @pytest.mark.parametrize("method", ["post", "get"])
    async def test_unknown_clip_returns_404(self, client, settings, method: str) -> None:
        user = await _make_user(f"stems-404-{method}@example.com")
        resp = await getattr(client, method)(
            _stems_url(PydanticObjectId()), headers=_auth_headers(user, settings)
        )
        assert resp.status_code == 404

    @pytest.mark.parametrize("method", ["post", "get"])
    async def test_malformed_id_returns_404(self, client, settings, method: str) -> None:
        user = await _make_user(f"stems-malformed-{method}@example.com")
        resp = await getattr(client, method)(
            _stems_url("not-an-object-id"), headers=_auth_headers(user, settings)
        )
        assert resp.status_code == 404

    @pytest.mark.parametrize("method", ["post", "get"])
    async def test_other_users_clip_returns_404(self, client, settings, method: str) -> None:
        _, _, clip = await _user_with_clip(f"stems-owner-{method}@example.com")
        other = await _make_user(f"stems-other-{method}@example.com")
        resp = await getattr(client, method)(_stems_url(clip.id), headers=_auth_headers(other, settings))
        assert resp.status_code == 404
        assert await Job.count() == 0


# ---------------------------------------------------------------------------
# 422 — non-wav source (no ffmpeg on the server)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestFormatGate:
    @pytest.mark.parametrize("fmt", ["mp3", "aac", "opus", "flac"])
    async def test_non_wav_clip_returns_422(self, client, settings, fmt: str) -> None:
        user, _, clip = await _user_with_clip(f"stems-fmt-{fmt}@example.com", fmt=fmt)
        resp = await client.post(_stems_url(clip.id), headers=_auth_headers(user, settings))
        assert resp.status_code == 422
        assert fmt in resp.json()["detail"]
        assert await Job.count() == 0

    async def test_missing_format_falls_back_to_wav_suffix(self, client, settings) -> None:
        user, _, clip = await _user_with_clip("stems-fmt-none@example.com", fmt=None)
        resp = await client.post(_stems_url(clip.id), headers=_auth_headers(user, settings))
        assert resp.status_code == 202
        assert await Job.count() == 1


# ---------------------------------------------------------------------------
# 202 — job enqueue
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestStemsEnqueue:
    async def test_returns_202_and_persists_job(self, client, settings) -> None:
        user, workspace, clip = await _user_with_clip("stems-202@example.com")
        resp = await client.post(_stems_url(clip.id), headers=_auth_headers(user, settings))
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "queued"

        jobs = await Job.find_all().to_list()
        assert len(jobs) == 1
        job = jobs[0]
        assert str(job.id) == body["job_id"]
        assert job.job_type == "stems"
        assert job.status == JobStatus.QUEUED
        assert job.user_id == user.id
        assert job.workspace_id == workspace.id
        assert job.input_params == {"clip_id": str(clip.id)}

    async def test_double_submit_reuses_in_flight_job(self, client, settings) -> None:
        # Two POSTs before the first completes must not create competing jobs —
        # the second rides the queued one (idempotent per clip).
        user, _, clip = await _user_with_clip("stems-dedup@example.com")
        headers = _auth_headers(user, settings)

        first = await client.post(_stems_url(clip.id), headers=headers)
        second = await client.post(_stems_url(clip.id), headers=headers)
        assert first.status_code == 202
        assert second.status_code == 202
        assert first.json()["job_id"] == second.json()["job_id"]
        assert await Job.count() == 1


# ---------------------------------------------------------------------------
# GET — 404 when absent, results when present
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestGetStems:
    async def test_get_returns_404_when_not_extracted(self, client, settings) -> None:
        user, _, clip = await _user_with_clip("stems-get-404@example.com")
        resp = await client.get(_stems_url(clip.id), headers=_auth_headers(user, settings))
        assert resp.status_code == 404

    async def test_get_returns_404_for_partial_set(self, client, settings) -> None:
        # A partial set (one stem child deleted) is reported as "not separated",
        # matching the POST cache check — never a result missing required labels.
        user, _, clip = await _user_with_clip("stems-get-partial@example.com")
        await _insert_stem_children(clip, labels=["drums", "bass", "other"])  # missing vocals
        resp = await client.get(_stems_url(clip.id), headers=_auth_headers(user, settings))
        assert resp.status_code == 404

    async def test_get_returns_stem_ids_after_extraction(self, client, settings) -> None:
        user, _, clip = await _user_with_clip("stems-get-ok@example.com")
        children = await _insert_stem_children(clip)

        resp = await client.get(_stems_url(clip.id), headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        body = resp.json()
        assert body["parent_clip_id"] == str(clip.id)
        assert set(body["labels"]) == set(STEM_LABELS)
        assert set(body["stem_clip_ids"]) == {str(c.id) for c in children}

    async def test_stems_are_scoped_to_their_own_parent(self, client, settings) -> None:
        # A second clip with its own stems must not leak into the first clip's
        # results — guards the parent_clip_ids cache query.
        user = await _make_user("stems-parent-isolation@example.com")
        workspace = await _make_workspace(user)
        clip_a = await _insert_clip(user, workspace)
        clip_b = await _insert_clip(user, workspace)
        children_a = await _insert_stem_children(clip_a)
        await _insert_stem_children(clip_b)

        resp = await client.get(_stems_url(clip_a.id), headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        assert set(resp.json()["stem_clip_ids"]) == {str(c.id) for c in children_a}


# ---------------------------------------------------------------------------
# Cache — POST returns existing stems with 200 instead of enqueuing
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestStemsCache:
    async def test_post_returns_200_with_cached_stems(self, client, settings) -> None:
        user, _, clip = await _user_with_clip("stems-cache@example.com")
        children = await _insert_stem_children(clip)

        resp = await client.post(_stems_url(clip.id), headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        body = resp.json()
        assert set(body["stem_clip_ids"]) == {str(c.id) for c in children}
        assert set(body["labels"]) == set(STEM_LABELS)
        # No duplicate job is created on a cache hit.
        assert await Job.count() == 0

    async def test_cache_hit_works_even_for_non_wav_source(self, client, settings) -> None:
        # The cache check precedes the wav gate: an mp3 clip that already has a
        # *complete* stem set still returns it rather than 422.
        user, _, clip = await _user_with_clip("stems-cache-mp3@example.com", fmt="mp3")
        await _insert_stem_children(clip)
        resp = await client.post(_stems_url(clip.id), headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        assert await Job.count() == 0

    async def test_incomplete_cache_re_enqueues(self, client, settings) -> None:
        # If the owner deleted one stem child, an incomplete set must not be
        # served as a cache hit — re-POST enqueues a fresh separation (202).
        user, _, clip = await _user_with_clip("stems-cache-partial@example.com")
        await _insert_stem_children(clip, labels=["drums", "bass", "other"])  # missing vocals

        resp = await client.post(_stems_url(clip.id), headers=_auth_headers(user, settings))
        assert resp.status_code == 202
        assert await Job.count() == 1


# ---------------------------------------------------------------------------
# End-to-end lifecycle with a stubbed StemsClient
# ---------------------------------------------------------------------------


class _FakeStemsClient:
    """Writes four short WAV stems without running demucs."""

    model_samplerate = 44100

    def separate(self, audio_path, progress_callback=None):
        # The real return is a tensor dict; the handler only forwards it to
        # save_stems, which we also stub, so an opaque marker per label suffices.
        return {label: label for label in STEM_LABELS}

    def save_stems(self, stems, output_dir, base_name, sample_rate=44100, output_format="wav"):
        from pathlib import Path

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        paths = {}
        tone = (0.2 * np.sin(2 * np.pi * 220 * np.linspace(0, 0.5, int(sample_rate * 0.5), endpoint=False))).astype(
            np.float32
        )
        for label in STEM_LABELS:
            path = output_dir / f"{base_name}-{label}.{output_format}"
            sf.write(str(path), np.column_stack([tone, tone]), sample_rate)
            paths[label] = path
        return paths


@pytest.fixture
def local_storage(monkeypatch, tmp_path):
    monkeypatch.setenv("ACEMUSIC_STORAGE_BACKEND", "local")
    monkeypatch.setenv("ACEMUSIC_STORAGE_LOCAL_ROOT", str(tmp_path / "storage"))
    return tmp_path


@pytest.mark.integration
class TestStemsLifecycleEndToEnd:
    async def test_stems_run_to_completed_and_create_four_linked_clips(
        self, client, settings, local_storage, write_tone, monkeypatch
    ) -> None:
        from acemusic.api.tasks import extraction as extraction_tasks
        from acemusic.api.tasks.processor import JobProcessor

        monkeypatch.setattr(extraction_tasks, "StemsClient", _FakeStemsClient)

        user = await _make_user("stems-e2e@example.com")
        workspace = await _make_workspace(user)
        tone_path = local_storage / "tone.wav"
        write_tone(tone_path, duration_s=2.0)
        clip = await _insert_clip(user, workspace, duration=2.0, bpm=120, store_bytes=tone_path.read_bytes())
        headers = _auth_headers(user, settings)

        accepted = await client.post(_stems_url(clip.id), headers=headers)
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
        assert status_body is not None and status_body["status"] == "completed", "stems job never completed"

        # AC: 4 playable clips linked to the parent, time-aligned/equal length.
        assert len(status_body["clip_ids"]) == 4
        assert len(status_body["audio_urls"]) == 4
        children = [await Clip.get(PydanticObjectId(cid)) for cid in status_body["clip_ids"]]
        assert {c.title for c in children} == set(STEM_LABELS)
        for child in children:
            assert child.parent_clip_ids == [clip.id]
            assert child.generation_mode == "stems"
            assert child.duration == clip.duration  # equal length

        # The endpoint now reports the cached stems.
        get_resp = await client.get(_stems_url(clip.id), headers=headers)
        assert get_resp.status_code == 200
        assert set(get_resp.json()["stem_clip_ids"]) == set(status_body["clip_ids"])
