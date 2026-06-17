"""Integration tests for the mastering endpoint (US-12.1).

Covers ``POST /api/v1/mastering/jobs``: each request validates against an owned
source clip, gates on per-service credits, and enqueues a queued job returning
202 with a trackable job id. The 401 auth-gate test runs in CI (no DB); the rest
are ``integration`` and drive the real app over a local MongoDB.
"""

import httpx
import pytest
from beanie import PydanticObjectId
from fastapi.testclient import TestClient

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.models import Clip, CreditTransaction, Job, JobStatus, Workspace
from acemusic.api.services import users as user_service
from acemusic.api.settings import ApiSettings

MASTERING_URL = f"{API_V1_PREFIX}/mastering/jobs"


# ---------------------------------------------------------------------------
# Auth gate — runs in CI (no DB; plain TestClient does not run the lifespan)
# ---------------------------------------------------------------------------


class TestAuthGate:
    def test_missing_auth_header_returns_401(self) -> None:
        client = TestClient(create_app())
        resp = client.post(MASTERING_URL, json={"clip_id": str(PydanticObjectId()), "profile": "streaming"})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Integration — real MongoDB
# ---------------------------------------------------------------------------


def _async_client(app) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


@pytest.fixture
def settings(mongo_db, mongo_settings) -> ApiSettings:
    # Disable the background processor: these tests assert on the queued job
    # record and do not want a worker claiming it out from under them.
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


async def _make_user(email: str, *, balance: float | None = None):
    user = await user_service.get_or_create_user(email=email, provider="google", oauth_id=f"g-{email}", name="T")
    if balance is not None:
        user.credits_balance = balance
        await user.save()
    return user


async def _make_workspace(user, name: str = "WS") -> Workspace:
    workspace = Workspace(name=name, user_id=user.id)
    await workspace.insert()
    return workspace


async def _insert_clip(user, workspace: Workspace, *, fmt: str | None = "wav") -> Clip:
    clip_id = PydanticObjectId()
    clip = Clip(
        id=clip_id,
        user_id=user.id,
        workspace_id=workspace.id,
        file_path=f"{user.id}/{workspace.id}/clips/{clip_id}.{fmt or 'wav'}",
        format=fmt,
        duration=10.0,
    )
    await clip.insert()
    return clip


async def _user_with_clip(email: str, *, balance: float | None = None):
    user = await _make_user(email, balance=balance)
    workspace = await _make_workspace(user)
    clip = await _insert_clip(user, workspace)
    return user, workspace, clip


async def _reload(user):
    return await user_service.get_user_by_id(str(user.id))


# ---------------------------------------------------------------------------
# Success — 202 + queued job persisted with all parameters
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSuccessfulSubmission:
    async def test_returns_202_with_queued_job_id(self, client, settings) -> None:
        user, _ws, clip = await _user_with_clip("master-ok@example.com")
        resp = await client.post(
            MASTERING_URL,
            json={"clip_id": str(clip.id), "profile": "streaming"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body["job_id"]
        assert body["status"] == "queued"

    async def test_job_record_created_in_mongo_with_all_params(self, client, settings) -> None:
        user, ws, clip = await _user_with_clip("master-persist@example.com")
        resp = await client.post(
            MASTERING_URL,
            json={"clip_id": str(clip.id), "profile": "soundcloud", "service": "landr", "format": "flac"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 202
        job = await Job.get(resp.json()["job_id"])
        assert job is not None
        assert job.status is JobStatus.QUEUED
        assert job.job_type == "mastering"
        assert job.workspace_id == ws.id
        assert job.input_params["clip_id"] == str(clip.id)
        assert job.input_params["profile"] == "soundcloud"
        assert job.input_params["service"] == "landr"
        assert job.input_params["format"] == "flac"
        assert job.input_params["target_lufs"] == -12.0

    @pytest.mark.parametrize(
        ("profile", "expected_lufs"),
        [("streaming", -14.0), ("soundcloud", -12.0), ("club", -6.0), ("vinyl", -18.0)],
    )
    async def test_each_profile_persists_correct_lufs(self, client, settings, profile, expected_lufs) -> None:
        user, _ws, clip = await _user_with_clip(f"master-{profile}@example.com")
        resp = await client.post(
            MASTERING_URL,
            json={"clip_id": str(clip.id), "profile": profile},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 202
        job = await Job.get(resp.json()["job_id"])
        assert job.input_params["target_lufs"] == expected_lufs

    async def test_custom_profile_uses_supplied_lufs(self, client, settings) -> None:
        user, _ws, clip = await _user_with_clip("master-custom@example.com")
        resp = await client.post(
            MASTERING_URL,
            json={"clip_id": str(clip.id), "profile": "custom", "target_lufs": -9.0},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 202
        job = await Job.get(resp.json()["job_id"])
        assert job.input_params["target_lufs"] == -9.0

    async def test_service_specific_credits_deducted(self, client, settings) -> None:
        # bakuage costs 5; a 10-credit balance should drop to 5.
        user, _ws, clip = await _user_with_clip("master-charge@example.com", balance=10.0)
        resp = await client.post(
            MASTERING_URL,
            json={"clip_id": str(clip.id), "profile": "streaming", "service": "bakuage"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 202
        assert (await _reload(user)).credits_balance == 5.0
        txns = await CreditTransaction.find(CreditTransaction.user_id == user.id).to_list()
        assert len(txns) == 1
        assert txns[0].amount == -5.0
        assert txns[0].action_type == "mastering"


# ---------------------------------------------------------------------------
# Validation — 422
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestValidation:
    async def test_invalid_profile_returns_422(self, client, settings) -> None:
        user, _ws, clip = await _user_with_clip("master-badprofile@example.com")
        resp = await client.post(
            MASTERING_URL,
            json={"clip_id": str(clip.id), "profile": "ultraloud"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 422

    async def test_invalid_service_returns_422(self, client, settings) -> None:
        user, _ws, clip = await _user_with_clip("master-badservice@example.com")
        resp = await client.post(
            MASTERING_URL,
            json={"clip_id": str(clip.id), "profile": "streaming", "service": "izotope"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 422

    async def test_custom_profile_without_target_lufs_returns_422(self, client, settings) -> None:
        user, _ws, clip = await _user_with_clip("master-custom-missing@example.com")
        resp = await client.post(
            MASTERING_URL,
            json={"clip_id": str(clip.id), "profile": "custom"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 422

    async def test_target_lufs_on_standard_profile_returns_422(self, client, settings) -> None:
        user, _ws, clip = await _user_with_clip("master-stray-lufs@example.com")
        resp = await client.post(
            MASTERING_URL,
            json={"clip_id": str(clip.id), "profile": "streaming", "target_lufs": -10.0},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 422

    async def test_custom_lufs_out_of_range_returns_422(self, client, settings) -> None:
        user, _ws, clip = await _user_with_clip("master-lufs-range@example.com")
        resp = await client.post(
            MASTERING_URL,
            json={"clip_id": str(clip.id), "profile": "custom", "target_lufs": 5.0},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Credit gating — 402
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestInsufficientCredits:
    async def test_returns_402_with_balance_payload(self, client, settings) -> None:
        user, _ws, clip = await _user_with_clip("master-poor@example.com", balance=1.0)
        resp = await client.post(
            MASTERING_URL,
            json={"clip_id": str(clip.id), "profile": "streaming", "service": "dolby"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 402
        detail = resp.json()["detail"]
        assert detail["error"] == "insufficient_credits"
        assert detail["balance"] == 1.0
        assert detail["required"] == 3.0

    async def test_no_job_or_charge_on_insufficient_credits(self, client, settings) -> None:
        user, _ws, clip = await _user_with_clip("master-poor-noop@example.com", balance=1.0)
        resp = await client.post(
            MASTERING_URL,
            json={"clip_id": str(clip.id), "profile": "streaming"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 402
        assert (await _reload(user)).credits_balance == 1.0
        assert await Job.find(Job.user_id == user.id).count() == 0
        assert await CreditTransaction.find(CreditTransaction.user_id == user.id).count() == 0


# ---------------------------------------------------------------------------
# Ownership — 404
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestClipOwnership:
    async def test_unknown_clip_returns_404_and_no_charge(self, client, settings) -> None:
        user = await _make_user("master-noclip@example.com", balance=10.0)
        resp = await client.post(
            MASTERING_URL,
            json={"clip_id": str(PydanticObjectId()), "profile": "streaming"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 404
        assert (await _reload(user)).credits_balance == 10.0

    async def test_other_users_clip_returns_404(self, client, settings) -> None:
        owner, _ws, clip = await _user_with_clip("master-owner@example.com")
        intruder = await _make_user("master-intruder@example.com", balance=10.0)
        resp = await client.post(
            MASTERING_URL,
            json={"clip_id": str(clip.id), "profile": "streaming"},
            headers=_auth_headers(intruder, settings),
        )
        assert resp.status_code == 404
