"""Integration tests for the video generation endpoints (US-22.1).

Covers ``POST /api/v1/videos/generate`` (each request validates against an
owned source clip, gates on resolution/duration-tiered credits, and enqueues a
queued ``video`` job returning 202 with a trackable job id) and
``GET /api/v1/videos/{job_id}/status`` (maps the job lifecycle plus the
provider's ``progress_detail`` onto queued/rendering/encoding/complete/failed
with progress % and ETA). The 401 auth-gate tests run in CI (no DB); the rest
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
from acemusic.api.services.video import VIDEO_JOB_TYPE
from acemusic.api.settings import ApiSettings

GENERATE_URL = f"{API_V1_PREFIX}/videos/generate"


def _status_url(job_id: str) -> str:
    return f"{API_V1_PREFIX}/videos/{job_id}/status"


# ---------------------------------------------------------------------------
# Auth gate — runs in CI (no DB; plain TestClient does not run the lifespan)
# ---------------------------------------------------------------------------


class TestAuthGate:
    def test_generate_without_auth_returns_401(self) -> None:
        client = TestClient(create_app())
        resp = client.post(GENERATE_URL, json={"clip_id": str(PydanticObjectId()), "prompt": "neon"})
        assert resp.status_code == 401

    def test_status_without_auth_returns_401(self) -> None:
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


async def _insert_clip(user, workspace: Workspace, *, duration: float = 10.0) -> Clip:
    clip_id = PydanticObjectId()
    clip = Clip(
        id=clip_id,
        user_id=user.id,
        workspace_id=workspace.id,
        file_path=f"{user.id}/{workspace.id}/clips/{clip_id}.wav",
        format="wav",
        duration=duration,
    )
    await clip.insert()
    return clip


async def _user_with_clip(email: str, *, balance: float | None = None, duration: float = 10.0):
    user = await _make_user(email, balance=balance)
    workspace = Workspace(name="WS", user_id=user.id)
    await workspace.insert()
    clip = await _insert_clip(user, workspace, duration=duration)
    return user, workspace, clip


async def _reload(user):
    return await user_service.get_user_by_id(str(user.id))


def _valid_body(clip, **overrides) -> dict:
    body = {"clip_id": str(clip.id), "prompt": "neon city at night"}
    body.update(overrides)
    return body


# ---------------------------------------------------------------------------
# Submission — 202 + queued job persisted with all parameters
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSuccessfulSubmission:
    async def test_returns_202_with_job_id(self, client, settings) -> None:
        user, _ws, clip = await _user_with_clip("video-ok@example.com", balance=10.0)
        resp = await client.post(GENERATE_URL, json=_valid_body(clip), headers=_auth_headers(user, settings))
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "queued"
        job = await Job.get(PydanticObjectId(body["job_id"]))
        assert job is not None and job.job_type == VIDEO_JOB_TYPE and job.status == JobStatus.QUEUED

    async def test_full_options_snapshot_persisted(self, client, settings) -> None:
        user, _ws, clip = await _user_with_clip("video-params@example.com", balance=10.0)
        body = _valid_body(
            clip,
            style_preset="cinematic",
            reference_image_urls=["https://img.test/a.png", "https://img.test/b.png"],
            lyrics_sync=True,
            aspect_ratio="9:16",
            resolution="1080p",
            frame_rate=60,
            transitions="fade",
        )
        resp = await client.post(GENERATE_URL, json=body, headers=_auth_headers(user, settings))
        assert resp.status_code == 202
        job = await Job.get(PydanticObjectId(resp.json()["job_id"]))
        params = job.input_params
        assert params["clip_id"] == str(clip.id)
        assert params["style_preset"] == "cinematic"
        assert params["reference_image_urls"] == ["https://img.test/a.png", "https://img.test/b.png"]
        assert params["lyrics_sync"] is True
        assert params["aspect_ratio"] == "9:16"
        assert params["resolution"] == "1080p"
        assert params["frame_rate"] == 60
        assert params["transitions"] == "fade"

    async def test_charges_resolution_cost_and_records_ledger(self, client, settings) -> None:
        user, _ws, clip = await _user_with_clip("video-charge@example.com", balance=10.0)
        resp = await client.post(
            GENERATE_URL,
            json=_valid_body(clip, resolution="1080p"),
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 202
        assert (await _reload(user)).credits_balance == 3.0  # 10 - 7 (1080p base)
        txns = await CreditTransaction.find(CreditTransaction.user_id == user.id).to_list()
        assert len(txns) == 1
        assert txns[0].amount == -7.0
        assert txns[0].action_type == VIDEO_JOB_TYPE
        assert txns[0].job_id == resp.json()["job_id"]

    async def test_long_song_pays_duration_surcharge(self, client, settings) -> None:
        user, _ws, clip = await _user_with_clip("video-long@example.com", balance=10.0, duration=200.0)
        resp = await client.post(GENERATE_URL, json=_valid_body(clip), headers=_auth_headers(user, settings))
        assert resp.status_code == 202
        assert (await _reload(user)).credits_balance == 3.0  # 10 - (5 + 2 surcharge)


# ---------------------------------------------------------------------------
# Validation — 422
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestValidation:
    async def test_unknown_field_rejected(self, client, settings) -> None:
        user, _ws, clip = await _user_with_clip("video-extra@example.com", balance=10.0)
        resp = await client.post(
            GENERATE_URL,
            json=_valid_body(clip, codec="h265"),
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 422

    async def test_prompt_or_preset_required(self, client, settings) -> None:
        user, _ws, clip = await _user_with_clip("video-noprompt@example.com", balance=10.0)
        resp = await client.post(
            GENERATE_URL,
            json={"clip_id": str(clip.id)},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 422

    async def test_invalid_resolution_rejected(self, client, settings) -> None:
        user, _ws, clip = await _user_with_clip("video-badres@example.com", balance=10.0)
        resp = await client.post(
            GENERATE_URL,
            json=_valid_body(clip, resolution="8k"),
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 422

    async def test_too_many_reference_images_rejected(self, client, settings) -> None:
        user, _ws, clip = await _user_with_clip("video-refs@example.com", balance=10.0)
        resp = await client.post(
            GENERATE_URL,
            json=_valid_body(clip, reference_image_urls=[f"https://img.test/{i}.png" for i in range(6)]),
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Credit gating — 402
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestInsufficientCredits:
    async def test_returns_402_with_balance_payload(self, client, settings) -> None:
        user, _ws, clip = await _user_with_clip("video-poor@example.com", balance=1.0)
        resp = await client.post(GENERATE_URL, json=_valid_body(clip), headers=_auth_headers(user, settings))
        assert resp.status_code == 402
        detail = resp.json()["detail"]
        assert detail["error"] == "insufficient_credits"
        assert detail["balance"] == 1.0
        assert detail["required"] == 5.0

    async def test_no_job_or_charge_on_insufficient_credits(self, client, settings) -> None:
        user, _ws, clip = await _user_with_clip("video-poor-noop@example.com", balance=1.0)
        resp = await client.post(GENERATE_URL, json=_valid_body(clip), headers=_auth_headers(user, settings))
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
        user = await _make_user("video-noclip@example.com", balance=10.0)
        resp = await client.post(
            GENERATE_URL,
            json={"clip_id": str(PydanticObjectId()), "prompt": "neon"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 404
        assert (await _reload(user)).credits_balance == 10.0

    async def test_other_users_clip_returns_404(self, client, settings) -> None:
        _owner, _ws, clip = await _user_with_clip("video-owner@example.com", balance=10.0)
        thief = await _make_user("video-thief@example.com", balance=10.0)
        resp = await client.post(
            GENERATE_URL,
            json=_valid_body(clip),
            headers=_auth_headers(thief, settings),
        )
        assert resp.status_code == 404
        assert (await _reload(thief)).credits_balance == 10.0


# ---------------------------------------------------------------------------
# Status endpoint — the queued/rendering/encoding/complete/failed vocabulary
# ---------------------------------------------------------------------------


async def _submit(client, settings, user, clip) -> str:
    resp = await client.post(GENERATE_URL, json=_valid_body(clip), headers=_auth_headers(user, settings))
    assert resp.status_code == 202
    return resp.json()["job_id"]


@pytest.mark.integration
class TestStatusEndpoint:
    async def test_queued_job_reports_queued(self, client, settings) -> None:
        user, _ws, clip = await _user_with_clip("video-st-q@example.com", balance=10.0)
        job_id = await _submit(client, settings, user, clip)
        resp = await client.get(_status_url(job_id), headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "queued"
        assert body["progress"] == 0
        assert "video_id" not in body and "error" not in body

    async def test_processing_job_reports_provider_state(self, client, settings) -> None:
        user, _ws, clip = await _user_with_clip("video-st-r@example.com", balance=10.0)
        job_id = await _submit(client, settings, user, clip)
        job = await Job.get(PydanticObjectId(job_id))
        await job.set(
            {
                Job.status: JobStatus.PROCESSING,
                Job.progress_detail: {"state": "rendering", "progress": 42, "eta_seconds": 30.0},
            }
        )
        body = (await client.get(_status_url(job_id), headers=_auth_headers(user, settings))).json()
        assert body["status"] == "rendering"
        assert body["progress"] == 42
        assert body["eta_seconds"] == 30.0

    async def test_encoding_state_surfaces(self, client, settings) -> None:
        user, _ws, clip = await _user_with_clip("video-st-e@example.com", balance=10.0)
        job_id = await _submit(client, settings, user, clip)
        job = await Job.get(PydanticObjectId(job_id))
        await job.set({Job.status: JobStatus.PROCESSING, Job.progress_detail: {"state": "encoding", "progress": 90}})
        body = (await client.get(_status_url(job_id), headers=_auth_headers(user, settings))).json()
        assert body["status"] == "encoding"
        assert body["progress"] == 90

    async def test_processing_without_detail_defaults_to_rendering(self, client, settings) -> None:
        user, _ws, clip = await _user_with_clip("video-st-d@example.com", balance=10.0)
        job_id = await _submit(client, settings, user, clip)
        job = await Job.get(PydanticObjectId(job_id))
        await job.set({Job.status: JobStatus.PROCESSING})
        body = (await client.get(_status_url(job_id), headers=_auth_headers(user, settings))).json()
        assert body["status"] == "rendering"
        assert body["progress"] == 0

    async def test_completed_job_reports_complete_with_video_id(self, client, settings) -> None:
        user, _ws, clip = await _user_with_clip("video-st-c@example.com", balance=10.0)
        job_id = await _submit(client, settings, user, clip)
        job = await Job.get(PydanticObjectId(job_id))
        await job.set(
            {
                Job.status: JobStatus.COMPLETED,
                Job.result: {"video_ids": ["665f00000000000000000001"], "storage_path": "p.mp4"},
            }
        )
        body = (await client.get(_status_url(job_id), headers=_auth_headers(user, settings))).json()
        assert body["status"] == "complete"
        assert body["progress"] == 100
        assert body["video_id"] == "665f00000000000000000001"

    async def test_failed_job_reports_failed_with_error(self, client, settings) -> None:
        user, _ws, clip = await _user_with_clip("video-st-f@example.com", balance=10.0)
        job_id = await _submit(client, settings, user, clip)
        job = await Job.get(PydanticObjectId(job_id))
        await job.set({Job.status: JobStatus.FAILED, Job.error: "Video rendering failed: provider says no"})
        body = (await client.get(_status_url(job_id), headers=_auth_headers(user, settings))).json()
        assert body["status"] == "failed"
        assert body["error"] == "Video rendering failed: provider says no"

    async def test_unowned_job_returns_404(self, client, settings) -> None:
        user, _ws, clip = await _user_with_clip("video-st-own@example.com", balance=10.0)
        job_id = await _submit(client, settings, user, clip)
        other = await _make_user("video-st-other@example.com")
        resp = await client.get(_status_url(job_id), headers=_auth_headers(other, settings))
        assert resp.status_code == 404

    async def test_non_video_job_returns_404(self, client, settings) -> None:
        user, _ws, clip = await _user_with_clip("video-st-type@example.com", balance=10.0)
        job = Job(user_id=user.id, workspace_id=clip.workspace_id, job_type="mastering")
        await job.insert()
        resp = await client.get(_status_url(str(job.id)), headers=_auth_headers(user, settings))
        assert resp.status_code == 404

    async def test_malformed_job_id_returns_404(self, client, settings) -> None:
        user = await _make_user("video-st-bad@example.com")
        resp = await client.get(_status_url("not-an-id"), headers=_auth_headers(user, settings))
        assert resp.status_code == 404
