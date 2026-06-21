"""Integration tests for batch mastering (US-12.5).

Covers ``POST /api/v1/mastering/batch`` and ``GET
/api/v1/mastering/batch/{id}/status``: one mastering job per owned clip under a
single :class:`BatchJob`, upfront per-clip credit charging with partial-failure
tolerance, and live status aggregation. The auth-gate tests run in CI (no DB);
the rest are ``integration`` and drive the real app over a local MongoDB.
"""

import httpx
import pytest
from beanie import PydanticObjectId
from fastapi.testclient import TestClient

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.models import BatchClipEntry, BatchJob, Clip, CreditTransaction, Job, JobStatus, Workspace
from acemusic.api.services import users as user_service
from acemusic.api.settings import ApiSettings

BATCH_URL = f"{API_V1_PREFIX}/mastering/batch"


# ---------------------------------------------------------------------------
# Auth gate — runs in CI (no DB; plain TestClient does not run the lifespan)
# ---------------------------------------------------------------------------


class TestAuthGate:
    def test_post_missing_auth_returns_401(self) -> None:
        client = TestClient(create_app())
        resp = client.post(BATCH_URL, json={"clip_ids": [str(PydanticObjectId())], "profile": "streaming"})
        assert resp.status_code == 401

    def test_status_missing_auth_returns_401(self) -> None:
        client = TestClient(create_app())
        resp = client.get(f"{BATCH_URL}/{PydanticObjectId()}/status")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Integration — real MongoDB
# ---------------------------------------------------------------------------


def _async_client(app) -> httpx.AsyncClient:
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


async def _user_with_clips(email: str, n: int, *, balance: float | None = None):
    user = await _make_user(email, balance=balance)
    workspace = await _make_workspace(user)
    clips = [await _insert_clip(user, workspace) for _ in range(n)]
    return user, workspace, clips


async def _reload(user):
    return await user_service.get_user_by_id(str(user.id))


# ---------------------------------------------------------------------------
# Submission — 202 + one queued job per clip
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSubmission:
    async def test_queues_one_job_per_clip(self, client, settings) -> None:
        user, _ws, clips = await _user_with_clips("batch-ok@example.com", 3, balance=100.0)
        resp = await client.post(
            BATCH_URL,
            json={"clip_ids": [str(c.id) for c in clips], "profile": "streaming"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body["batch_id"]
        assert len(body["jobs"]) == 3
        assert all(j["job_id"] for j in body["jobs"])
        # Each is a real queued mastering job carrying the batch's params.
        for job_item in body["jobs"]:
            job = await Job.get(job_item["job_id"])
            assert job.job_type == "mastering"
            assert job.status is JobStatus.QUEUED
            assert job.input_params["profile"] == "streaming"
            assert job.input_params["target_lufs"] == -14.0

    async def test_charges_per_clip_with_ledger_rows(self, client, settings) -> None:
        # dolby = 3 credits; 2 clips → 6 deducted, 2 ledger rows.
        user, _ws, clips = await _user_with_clips("batch-charge@example.com", 2, balance=10.0)
        resp = await client.post(
            BATCH_URL,
            json={"clip_ids": [str(c.id) for c in clips], "profile": "club", "service": "dolby"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 202
        assert (await _reload(user)).credits_balance == 4.0
        txns = await CreditTransaction.find(CreditTransaction.user_id == user.id).to_list()
        assert len(txns) == 2
        assert all(t.amount == -3.0 and t.action_type == "mastering" for t in txns)
        # Each row carries its own running balance (10 → 7 → 4), not a flat figure.
        assert {t.balance_after for t in txns} == {7.0, 4.0}

    async def test_custom_profile_persists_supplied_lufs(self, client, settings) -> None:
        user, _ws, clips = await _user_with_clips("batch-custom@example.com", 1, balance=100.0)
        resp = await client.post(
            BATCH_URL,
            json={"clip_ids": [str(clips[0].id)], "profile": "custom", "target_lufs": -9.0},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 202
        job = await Job.get(resp.json()["jobs"][0]["job_id"])
        assert job.input_params["target_lufs"] == -9.0


# ---------------------------------------------------------------------------
# Partial failure — one bad clip never halts the batch
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestPartialFailure:
    async def test_unknown_clip_becomes_failed_entry_and_is_not_charged(self, client, settings) -> None:
        user, _ws, clips = await _user_with_clips("batch-partial@example.com", 1, balance=100.0)
        unknown = str(PydanticObjectId())
        resp = await client.post(
            BATCH_URL,
            json={"clip_ids": [str(clips[0].id), unknown], "profile": "streaming", "service": "landr"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 202
        jobs = {j["clip_id"]: j for j in resp.json()["jobs"]}
        assert jobs[str(clips[0].id)]["job_id"]
        assert jobs[unknown]["job_id"] is None
        assert jobs[unknown]["error"]
        # Only the one owned clip was charged (landr = 2).
        assert (await _reload(user)).credits_balance == 98.0


# ---------------------------------------------------------------------------
# Validation / credits — 422 and 402
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestValidation:
    async def test_over_limit_returns_422(self, client, settings) -> None:
        user, _ws, _clips = await _user_with_clips("batch-toomany@example.com", 0, balance=100.0)
        resp = await client.post(
            BATCH_URL,
            json={"clip_ids": [str(PydanticObjectId()) for _ in range(21)], "profile": "streaming"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 422

    async def test_duplicate_clip_ids_returns_422(self, client, settings) -> None:
        user, _ws, clips = await _user_with_clips("batch-dup@example.com", 1, balance=100.0)
        cid = str(clips[0].id)
        resp = await client.post(
            BATCH_URL,
            json={"clip_ids": [cid, cid], "profile": "streaming"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 422

    async def test_insufficient_credits_returns_402_and_charges_nothing(self, client, settings) -> None:
        # 3 clips * dolby(3) = 9 required, only 5 available.
        user, _ws, clips = await _user_with_clips("batch-broke@example.com", 3, balance=5.0)
        resp = await client.post(
            BATCH_URL,
            json={"clip_ids": [str(c.id) for c in clips], "profile": "streaming", "service": "dolby"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 402
        detail = resp.json()["detail"]
        assert detail["error"] == "insufficient_credits"
        assert detail["required"] == 9.0
        assert detail["balance"] == 5.0
        # No jobs created, balance untouched.
        assert (await _reload(user)).credits_balance == 5.0
        assert await Job.find(Job.user_id == user.id).to_list() == []


# ---------------------------------------------------------------------------
# Status aggregation
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestStatus:
    async def test_aggregates_counts_and_progress(self, client, settings) -> None:
        user, _ws, clips = await _user_with_clips("batch-status@example.com", 3, balance=100.0)
        post = await client.post(
            BATCH_URL,
            json={"clip_ids": [str(c.id) for c in clips], "profile": "streaming"},
            headers=_auth_headers(user, settings),
        )
        batch_id = post.json()["batch_id"]
        job_ids = [j["job_id"] for j in post.json()["jobs"]]

        # Drive two sub-jobs to terminal states; one stays queued.
        done = await Job.get(job_ids[0])
        done.status = JobStatus.COMPLETED
        done.result = {"clip_ids": ["mastered-child-1"]}
        await done.save()
        bad = await Job.get(job_ids[1])
        bad.status = JobStatus.FAILED
        bad.error = "boom"
        await bad.save()

        resp = await client.get(f"{BATCH_URL}/{batch_id}/status", headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 3
        assert body["completed"] == 1
        assert body["failed"] == 1
        assert body["queued"] == 1
        assert body["progress"] == pytest.approx(2 / 3)
        by_job = {j["job_id"]: j for j in body["jobs"]}
        assert by_job[job_ids[0]]["mastered_clip_id"] == "mastered-child-1"
        assert by_job[job_ids[1]]["error"] == "boom"

    async def test_unknown_batch_returns_404(self, client, settings) -> None:
        user = await _make_user("batch-404@example.com")
        resp = await client.get(f"{BATCH_URL}/{PydanticObjectId()}/status", headers=_auth_headers(user, settings))
        assert resp.status_code == 404

    async def test_other_users_batch_returns_404(self, client, settings) -> None:
        owner, _ws, clips = await _user_with_clips("batch-owner@example.com", 1, balance=100.0)
        post = await client.post(
            BATCH_URL,
            json={"clip_ids": [str(clips[0].id)], "profile": "streaming"},
            headers=_auth_headers(owner, settings),
        )
        batch_id = post.json()["batch_id"]
        intruder = await _make_user("batch-intruder@example.com")
        resp = await client.get(f"{BATCH_URL}/{batch_id}/status", headers=_auth_headers(intruder, settings))
        assert resp.status_code == 404

    async def test_non_mastering_batch_returns_404(self, client, settings) -> None:
        # A stems/export batch must not be readable via the mastering status route.
        user = await _make_user("batch-wrongop@example.com")
        batch = BatchJob(
            user_id=user.id,
            operation="export",
            format="mp3",
            entries=[BatchClipEntry(clip_id=str(PydanticObjectId()), job_id=str(PydanticObjectId()))],
        )
        await batch.insert()
        resp = await client.get(f"{BATCH_URL}/{batch.id}/status", headers=_auth_headers(user, settings))
        assert resp.status_code == 404
