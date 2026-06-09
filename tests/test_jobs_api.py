"""Tests for the job status endpoint (US-9.2).

The 401 auth-gate test runs in CI (the router dependency rejects before any DB
access). The lifecycle/ownership tests are ``integration``: they drive the real
app with ``httpx.AsyncClient`` over a local MongoDB (``mongo_db``), mirroring
``tests/test_generation_api.py``.
"""

import httpx
import pytest
from beanie import PydanticObjectId
from fastapi.testclient import TestClient

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.models import Clip, Job, JobStatus
from acemusic.api.services import users as user_service
from acemusic.api.settings import ApiSettings


def _status_url(job_id: str) -> str:
    return f"{API_V1_PREFIX}/jobs/{job_id}/status"


# ---------------------------------------------------------------------------
# Auth gate — runs in CI (no DB; plain TestClient does not run the lifespan)
# ---------------------------------------------------------------------------


class TestAuthGate:
    def test_missing_auth_header_returns_401(self) -> None:
        client = TestClient(create_app())
        resp = client.get(_status_url(str(PydanticObjectId())))
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Integration — real MongoDB
# ---------------------------------------------------------------------------


def _async_client(app) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


@pytest.fixture
def settings(mongo_db, mongo_settings) -> ApiSettings:
    # Disable the background processor: these tests drive job state directly and
    # do not want a worker claiming their fixtures out from under them.
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


async def _insert_job(user, *, status=JobStatus.QUEUED, result=None, error=None, params=None) -> Job:
    job = Job(
        user_id=user.id,
        workspace_id=PydanticObjectId(),
        job_type="generate",
        status=status,
        input_params=params or {"prompt": "a calm piano ballad"},
        result=result,
        error=error,
    )
    await job.insert()
    return job


@pytest.mark.integration
class TestStatusLifecycle:
    async def test_queued_job_reports_queued(self, client, settings) -> None:
        user = await _make_user("jobs-queued@example.com")
        job = await _insert_job(user, status=JobStatus.QUEUED)

        resp = await client.get(_status_url(str(job.id)), headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        body = resp.json()
        assert body["job_id"] == str(job.id)
        assert body["status"] == "queued"
        assert isinstance(body["estimated_time_seconds"], int)
        assert "clip_ids" not in body
        assert "audio_urls" not in body
        assert "error" not in body

    async def test_processing_job_reports_processing(self, client, settings) -> None:
        user = await _make_user("jobs-processing@example.com")
        job = await _insert_job(user, status=JobStatus.PROCESSING)

        resp = await client.get(_status_url(str(job.id)), headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "processing"
        # Result fields apply only once terminal; they must be absent here.
        assert "clip_ids" not in body
        assert "audio_urls" not in body
        assert "error" not in body

    async def test_completed_job_includes_clip_ids_and_audio_urls(
        self, client, settings, monkeypatch, tmp_path
    ) -> None:
        # Point storage at a throwaway root so get_url() resolves cleanly.
        monkeypatch.setenv("ACEMUSIC_STORAGE_BACKEND", "local")
        monkeypatch.setenv("ACEMUSIC_STORAGE_LOCAL_ROOT", str(tmp_path))

        user = await _make_user("jobs-done@example.com")
        workspace_id = PydanticObjectId()
        clip_ids = []
        for name in ("a", "b"):
            clip = Clip(
                user_id=user.id,
                workspace_id=workspace_id,
                file_path=f"{user.id}/{workspace_id}/clips/{name}.wav",
                format="wav",
            )
            await clip.insert()
            clip_ids.append(str(clip.id))

        job = await _insert_job(user, status=JobStatus.COMPLETED, result={"clip_ids": clip_ids})

        resp = await client.get(_status_url(str(job.id)), headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "completed"
        assert body["clip_ids"] == clip_ids
        assert len(body["audio_urls"]) == 2
        assert "error" not in body

    async def test_failed_job_includes_error(self, client, settings) -> None:
        user = await _make_user("jobs-failed@example.com")
        job = await _insert_job(user, status=JobStatus.FAILED, error="model overloaded")

        resp = await client.get(_status_url(str(job.id)), headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "failed"
        assert body["error"] == "model overloaded"
        assert "clip_ids" not in body
        assert "audio_urls" not in body


@pytest.mark.integration
class TestStatusNotFound:
    async def test_unknown_job_returns_404(self, client, settings) -> None:
        user = await _make_user("jobs-unknown@example.com")
        resp = await client.get(_status_url(str(PydanticObjectId())), headers=_auth_headers(user, settings))
        assert resp.status_code == 404

    async def test_malformed_id_returns_404(self, client, settings) -> None:
        user = await _make_user("jobs-malformed@example.com")
        resp = await client.get(_status_url("not-an-object-id"), headers=_auth_headers(user, settings))
        assert resp.status_code == 404

    async def test_other_users_job_returns_404(self, client, settings) -> None:
        owner = await _make_user("jobs-owner@example.com")
        other = await _make_user("jobs-other@example.com")
        job = await _insert_job(owner, status=JobStatus.COMPLETED, result={"clip_ids": []})

        resp = await client.get(_status_url(str(job.id)), headers=_auth_headers(other, settings))
        assert resp.status_code == 404
