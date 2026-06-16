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
from acemusic.api.services import routing, users as user_service
from acemusic.api.settings import ApiSettings

pytestmark = pytest.mark.integration

GENERATE_URL = f"{API_V1_PREFIX}/generate"
JOBS_URL = f"{API_V1_PREFIX}/jobs"


def _set_availability(monkeypatch, *, local: bool, remote: bool = False) -> None:
    """Stub the routing probes so endpoint tests control where a request routes."""

    async def _local(url, timeout=routing.LOCAL_AVAILABILITY_TIMEOUT):
        return local

    async def _remote():
        return remote

    monkeypatch.setattr(routing, "check_local_availability", _local)
    monkeypatch.setattr(routing, "check_remote_availability", _remote)


@pytest.fixture(autouse=True)
def _local_compute_available(monkeypatch):
    """Default the routing probe (US-11.1) to a reachable local backend.

    Most generation tests assert the job-creation contract, not compute
    availability; without a stub they would 503 (no local server runs in CI).
    Routing-specific tests below re-stub availability per case.
    """
    _set_availability(monkeypatch, local=True, remote=False)


def _async_client(app) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


@pytest.fixture
def settings(mongo_db, mongo_settings) -> ApiSettings:
    # mongo_db initialises Beanie against the isolated DB on this test's loop.
    # Disable the background processor (US-9.2): these tests assert jobs stay
    # ``queued``, so a worker claiming them mid-test would make them flaky.
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


class TestComputeRouting:
    """Compute routing engine (US-11.1).

    Availability is stubbed (no ACE-Step/RunPod runs in CI); each test asserts
    the routing decision the engine makes and how it surfaces on the job record
    and status response.
    """

    @staticmethod
    async def _client_for(settings: ApiSettings):
        return _async_client(create_app(settings))

    async def test_local_first_routes_local_when_available(self, monkeypatch, settings):
        _set_availability(monkeypatch, local=True, remote=False)
        s = settings.model_copy(update={"compute_preference": "local_first"})
        async with await self._client_for(s) as client:
            user = await _make_user("route-lf-local@example.com")
            resp = await client.post(GENERATE_URL, json={"prompt": "x"}, headers=_auth_headers(user, s))
            assert resp.status_code == 202
            job = await Job.get(resp.json()["job_id"])
            assert job.compute_target == "local"

    async def test_local_first_falls_back_to_remote_when_local_down(self, monkeypatch, settings):
        _set_availability(monkeypatch, local=False, remote=True)
        s = settings.model_copy(update={"compute_preference": "local_first"})
        async with await self._client_for(s) as client:
            user = await _make_user("route-lf-remote@example.com")
            resp = await client.post(GENERATE_URL, json={"prompt": "x"}, headers=_auth_headers(user, s))
            assert resp.status_code == 202
            job = await Job.get(resp.json()["job_id"])
            assert job.compute_target == "remote"

    async def test_remote_first_routes_remote_when_available(self, monkeypatch, settings):
        _set_availability(monkeypatch, local=True, remote=True)
        s = settings.model_copy(update={"compute_preference": "remote_first"})
        async with await self._client_for(s) as client:
            user = await _make_user("route-rf-remote@example.com")
            resp = await client.post(GENERATE_URL, json={"prompt": "x"}, headers=_auth_headers(user, s))
            assert resp.status_code == 202
            job = await Job.get(resp.json()["job_id"])
            assert job.compute_target == "remote"

    async def test_remote_first_falls_back_to_local_when_remote_down(self, monkeypatch, settings):
        _set_availability(monkeypatch, local=True, remote=False)
        s = settings.model_copy(update={"compute_preference": "remote_first"})
        async with await self._client_for(s) as client:
            user = await _make_user("route-rf-local@example.com")
            resp = await client.post(GENERATE_URL, json={"prompt": "x"}, headers=_auth_headers(user, s))
            assert resp.status_code == 202
            job = await Job.get(resp.json()["job_id"])
            assert job.compute_target == "local"

    async def test_local_only_returns_503_when_local_unavailable(self, monkeypatch, settings):
        _set_availability(monkeypatch, local=False, remote=True)
        s = settings.model_copy(update={"compute_preference": "local_only"})
        async with await self._client_for(s) as client:
            user = await _make_user("route-local-only@example.com")
            before = user.credits_balance
            resp = await client.post(GENERATE_URL, json={"prompt": "x"}, headers=_auth_headers(user, s))
            assert resp.status_code == 503
            assert "local" in resp.json()["detail"]
            # No job created and no credit charged for an unavailable backend.
            assert await Job.find(Job.user_id == user.id).to_list() == []
            fresh = await user_service.get_user_by_id(str(user.id))
            assert fresh.credits_balance == before

    async def test_remote_only_returns_503_when_remote_unavailable(self, monkeypatch, settings):
        _set_availability(monkeypatch, local=True, remote=False)
        s = settings.model_copy(update={"compute_preference": "remote_only"})
        async with await self._client_for(s) as client:
            user = await _make_user("route-remote-only@example.com")
            resp = await client.post(GENERATE_URL, json={"prompt": "x"}, headers=_auth_headers(user, s))
            assert resp.status_code == 503
            assert "remote" in resp.json()["detail"]

    async def test_per_request_local_overrides_remote_first_preference(self, monkeypatch, settings):
        _set_availability(monkeypatch, local=True, remote=True)
        s = settings.model_copy(update={"compute_preference": "remote_first"})
        async with await self._client_for(s) as client:
            user = await _make_user("route-override-local@example.com")
            resp = await client.post(
                GENERATE_URL,
                json={"prompt": "x", "compute_target": "local"},
                headers=_auth_headers(user, s),
            )
            assert resp.status_code == 202
            job = await Job.get(resp.json()["job_id"])
            assert job.compute_target == "local"

    async def test_per_request_local_503s_when_local_down_no_fallback(self, monkeypatch, settings):
        _set_availability(monkeypatch, local=False, remote=True)
        s = settings.model_copy(update={"compute_preference": "local_first"})
        async with await self._client_for(s) as client:
            user = await _make_user("route-override-local-down@example.com")
            resp = await client.post(
                GENERATE_URL,
                json={"prompt": "x", "compute_target": "local"},
                headers=_auth_headers(user, s),
            )
            assert resp.status_code == 503

    async def test_resolved_target_visible_in_job_status(self, monkeypatch, settings):
        _set_availability(monkeypatch, local=True, remote=False)
        s = settings.model_copy(update={"compute_preference": "local_first"})
        async with await self._client_for(s) as client:
            user = await _make_user("route-status@example.com")
            headers = _auth_headers(user, s)
            job_id = (await client.post(GENERATE_URL, json={"prompt": "x"}, headers=headers)).json()["job_id"]
            status_resp = await client.get(f"{JOBS_URL}/{job_id}/status", headers=headers)
            assert status_resp.status_code == 200
            assert status_resp.json()["compute_target"] == "local"

    async def test_compute_target_not_leaked_into_input_params(self, monkeypatch, settings):
        # The routing hint is not a creative param; it must not pollute the job
        # snapshot forwarded to the worker.
        _set_availability(monkeypatch, local=True, remote=True)
        s = settings.model_copy(update={"compute_preference": "remote_first"})
        async with await self._client_for(s) as client:
            user = await _make_user("route-no-leak@example.com")
            resp = await client.post(
                GENERATE_URL,
                json={"prompt": "x", "compute_target": "local"},
                headers=_auth_headers(user, s),
            )
            job = await Job.get(resp.json()["job_id"])
            assert "compute_target" not in job.input_params
