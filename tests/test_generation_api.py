"""Integration tests for the generation endpoint (US-9.1).

Drives the real app with ``httpx.AsyncClient`` over ``ASGITransport`` against a
local MongoDB (the ``mongo_db`` fixture), mirroring ``tests/test_users_api.py``.
Covers the 202/job-id contract for all three creation modes, MongoDB job
persistence, default-workspace creation, and the 401 auth gate.
"""

import httpx
import pytest

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.models import Job, JobStatus, Workspace
from acemusic.api.services import users as user_service
from acemusic.api.settings import ApiSettings

pytestmark = pytest.mark.integration

GENERATE_URL = f"{API_V1_PREFIX}/generate"


def _async_client(app) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


@pytest.fixture
def settings(mongo_db, mongo_settings) -> ApiSettings:
    # mongo_db initialises Beanie against the isolated DB on this test's loop.
    return mongo_settings.model_copy(update={"jwt_secret_key": "test-secret-key-at-least-32-bytes-long-xx"})


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


async def _make_user(email: str, name: str = "Test User"):
    return await user_service.get_or_create_user(email=email, provider="google", oauth_id=f"g-{email}", name=name)


class TestSuccessfulGeneration:
    async def test_minimal_song_returns_202_with_job_id(self, client, settings):
        user = await _make_user("gen-min@example.com")
        resp = await client.post(
            GENERATE_URL,
            json={"prompt": "a calm piano ballad"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body["job_id"]
        assert body["status"] == "queued"
        assert isinstance(body["estimated_time_seconds"], int)

    async def test_full_song_parameter_set_returns_202(self, client, settings):
        user = await _make_user("gen-full@example.com")
        resp = await client.post(
            GENERATE_URL,
            json={
                "prompt": "epic orchestral",
                "style": "cinematic",
                "lyrics": "ooh ah",
                "bpm": 120,
                "key": "C minor",
                "time_signature": "4/4",
                "duration": 90.0,
                "seed": 42,
                "inference_steps": 64,
                "model": "xl-base",
                "weirdness": 70,
                "style_influence": 30,
                "format": "flac",
                "thinking": True,
                "mode": "song",
            },
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 202

    async def test_sound_one_shot_returns_202(self, client, settings):
        user = await _make_user("gen-oneshot@example.com")
        resp = await client.post(
            GENERATE_URL,
            json={"prompt": "punchy kick drum", "mode": "sound", "sound_type": "one-shot"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 202

    async def test_sound_loop_with_bpm_returns_202(self, client, settings):
        user = await _make_user("gen-loop@example.com")
        resp = await client.post(
            GENERATE_URL,
            json={"prompt": "house loop", "mode": "sound", "sound_type": "loop", "bpm": 124, "key": "A minor"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 202


class TestJobPersistence:
    async def test_job_record_created_as_queued(self, client, settings):
        user = await _make_user("gen-persist@example.com")
        resp = await client.post(
            GENERATE_URL,
            json={"prompt": "lofi beat", "model": "turbo", "bpm": 90},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 202
        job_id = resp.json()["job_id"]

        job = await Job.get(job_id)
        assert job is not None
        assert job.status == JobStatus.QUEUED
        assert job.job_type == "generate"
        assert str(job.user_id) == str(user.id)
        assert job.input_params["prompt"] == "lofi beat"
        assert job.input_params["model"] == "turbo"
        assert job.input_params["bpm"] == 90
        assert job.workspace_id is not None

    async def test_default_workspace_created_and_reused(self, client, settings):
        user = await _make_user("gen-ws@example.com")
        headers = _auth_headers(user, settings)
        first = await client.post(GENERATE_URL, json={"prompt": "one"}, headers=headers)
        second = await client.post(GENERATE_URL, json={"prompt": "two"}, headers=headers)
        assert first.status_code == 202 and second.status_code == 202

        workspaces = await Workspace.find(Workspace.user_id == user.id).to_list()
        assert len(workspaces) == 1
        assert workspaces[0].is_default is True

        # Both jobs share the one default workspace.
        job_one = await Job.get(first.json()["job_id"])
        job_two = await Job.get(second.json()["job_id"])
        assert job_one.workspace_id == workspaces[0].id == job_two.workspace_id


class TestWorkspaceRace:
    async def test_concurrent_first_generation_creates_single_default(self, settings):
        """Two concurrent first-time generations converge on one default workspace.

        Exercises the unique-index + ``DuplicateKeyError`` re-read path in
        ``get_or_create_default_workspace`` against a real MongoDB (no mocking):
        both calls miss the initial lookup, race the insert, and one falls back
        to re-reading the winner.
        """
        import asyncio

        from acemusic.api.services import generation as gen_service

        user = await _make_user("gen-race@example.com")
        a, b = await asyncio.gather(
            gen_service.get_or_create_default_workspace(user.id),
            gen_service.get_or_create_default_workspace(user.id),
        )
        workspaces = await Workspace.find(Workspace.user_id == user.id).to_list()
        assert len(workspaces) == 1
        assert a.id == b.id == workspaces[0].id


class TestValidationErrors:
    async def test_bpm_out_of_range_returns_422(self, client, settings):
        user = await _make_user("gen-bpm@example.com")
        resp = await client.post(
            GENERATE_URL,
            json={"prompt": "x", "bpm": 999},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert any("bpm" in str(d.get("loc", "")) for d in detail)

    async def test_sound_without_sound_type_returns_422(self, client, settings):
        user = await _make_user("gen-missing-type@example.com")
        resp = await client.post(
            GENERATE_URL,
            json={"prompt": "x", "mode": "sound"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 422

    async def test_invalid_format_returns_422(self, client, settings):
        user = await _make_user("gen-fmt@example.com")
        resp = await client.post(
            GENERATE_URL,
            json={"prompt": "x", "format": "mp4"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 422


class TestAuthentication:
    async def test_missing_auth_header_returns_401(self, client, settings):
        resp = await client.post(GENERATE_URL, json={"prompt": "x"})
        assert resp.status_code == 401

    async def test_invalid_token_returns_401(self, client, settings):
        resp = await client.post(
            GENERATE_URL,
            json={"prompt": "x"},
            headers={"Authorization": "Bearer not-a-real-token"},
        )
        assert resp.status_code == 401


class TestStaleToken:
    """Token signature/expiry are valid, but the principal cannot be resolved."""

    def _token_headers(self, sub: str, settings: ApiSettings) -> dict[str, str]:
        token = create_access_token(
            user_id=sub,
            email="ghost@example.com",
            subscription_tier="free",
            settings=settings,
        )
        return {"Authorization": f"Bearer {token}"}

    async def test_deleted_user_returns_404(self, client, settings):
        from bson import ObjectId

        # A well-formed user id that does not exist (e.g. deleted account): the
        # endpoint must not persist an orphaned job/workspace.
        resp = await client.post(
            GENERATE_URL,
            json={"prompt": "x"},
            headers=self._token_headers(str(ObjectId()), settings),
        )
        assert resp.status_code == 404

    async def test_malformed_subject_returns_404(self, client, settings):
        # A non-ObjectId subject must resolve to "no such user", not crash (500).
        resp = await client.post(
            GENERATE_URL,
            json={"prompt": "x"},
            headers=self._token_headers("not-an-object-id", settings),
        )
        assert resp.status_code == 404

    async def test_no_orphan_workspace_created_for_deleted_user(self, client, settings):
        from bson import ObjectId

        ghost = ObjectId()
        await client.post(
            GENERATE_URL,
            json={"prompt": "x"},
            headers=self._token_headers(str(ghost), settings),
        )
        assert await Workspace.find(Workspace.user_id == ghost).to_list() == []
