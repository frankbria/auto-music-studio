"""Tests for the audio editing endpoints (US-10.1, issue #81).

Covers ``POST /clips/{id}/crop``, ``POST /clips/{id}/speed`` and
``POST /clips/{id}/remaster``: each validates against the source clip, enqueues
an editing job and returns 202 with a trackable job id.

The 401 auth-gate tests run in CI (no DB); the rest are ``integration`` and
drive the real app with ``httpx.AsyncClient`` over a local MongoDB.
"""

import logging

import httpx
import pytest
from beanie import PydanticObjectId
from fastapi.testclient import TestClient

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.models import Clip, Job, JobStatus, Workspace
from acemusic.api.services import users as user_service
from acemusic.api.settings import ApiSettings

CLIPS_URL = f"{API_V1_PREFIX}/clips"

# Minimal valid bodies, used where the test target is not the payload itself.
VALID_BODIES = {
    "crop": {"start": "0s", "end": "1s"},
    "speed": {"multiplier": 1.5},
    "remaster": {},
}


def _edit_url(clip_id, operation: str) -> str:
    return f"{CLIPS_URL}/{clip_id}/{operation}"


# ---------------------------------------------------------------------------
# Auth gate — runs in CI (no DB; plain TestClient does not run the lifespan)
# ---------------------------------------------------------------------------


class TestAuthGate:
    @pytest.mark.parametrize("operation", ["crop", "speed", "remaster"])
    def test_missing_auth_header_returns_401(self, operation: str) -> None:
        client = TestClient(create_app())
        resp = client.post(_edit_url(PydanticObjectId(), operation), json=VALID_BODIES[operation])
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
    fmt: str = "wav",
) -> Clip:
    clip_id = PydanticObjectId()
    clip = Clip(
        id=clip_id,
        user_id=user.id,
        workspace_id=workspace.id,
        file_path=f"{user.id}/{workspace.id}/clips/{clip_id}.{fmt}",
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


# ---------------------------------------------------------------------------
# 404 — unknown / malformed / other-user clip ids
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestClipNotFound:
    @pytest.mark.parametrize("operation", ["crop", "speed", "remaster"])
    async def test_unknown_clip_returns_404(self, client, settings, operation: str) -> None:
        user = await _make_user(f"edit-404-{operation}@example.com")
        resp = await client.post(
            _edit_url(PydanticObjectId(), operation),
            json=VALID_BODIES[operation],
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 404

    @pytest.mark.parametrize("operation", ["crop", "speed", "remaster"])
    async def test_malformed_id_returns_404(self, client, settings, operation: str) -> None:
        user = await _make_user(f"edit-malformed-{operation}@example.com")
        resp = await client.post(
            _edit_url("not-an-object-id", operation),
            json=VALID_BODIES[operation],
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 404

    @pytest.mark.parametrize("operation", ["crop", "speed", "remaster"])
    async def test_other_users_clip_returns_404(self, client, settings, operation: str) -> None:
        owner, _, clip = await _user_with_clip(f"edit-owner-{operation}@example.com")
        other = await _make_user(f"edit-other-{operation}@example.com")

        resp = await client.post(
            _edit_url(clip.id, operation),
            json=VALID_BODIES[operation],
            headers=_auth_headers(other, settings),
        )
        assert resp.status_code == 404
        assert await Job.count() == 0


# ---------------------------------------------------------------------------
# 422 — validation matrix
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCropValidation:
    @pytest.mark.parametrize(
        "body",
        [
            {"start": "abc", "end": "5s"},  # unparseable start
            {"start": "1s", "end": "later"},  # unparseable end
            {"start": "1s", "end": "5s", "fade_in": "x"},  # unparseable fade
            {"end": "5s"},  # missing start
            {"start": "1s"},  # missing end
            {"start": "5s", "end": "5s"},  # start == end
            {"start": "6s", "end": "5s"},  # start > end
            {"start": "1s", "end": "11s"},  # end beyond clip duration (10s)
            {"start": "1s", "end": "5s", "bogus": True},  # extra="forbid"
        ],
    )
    async def test_invalid_request_returns_422(self, client, settings, body: dict) -> None:
        user, _, clip = await _user_with_clip("edit-crop-422@example.com", duration=10.0)
        resp = await client.post(_edit_url(clip.id, "crop"), json=body, headers=_auth_headers(user, settings))
        assert resp.status_code == 422
        assert await Job.count() == 0

    async def test_snap_to_beat_without_bpm_returns_422(self, client, settings) -> None:
        user, _, clip = await _user_with_clip("edit-crop-snap-nobpm@example.com", duration=10.0, bpm=None)
        resp = await client.post(
            _edit_url(clip.id, "crop"),
            json={"start": "1s", "end": "5s", "snap_to_beat": True},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 422
        assert await Job.count() == 0

    async def test_snap_collapsing_range_returns_422(self, client, settings) -> None:
        # bpm=120 → beat every 500ms; both 0.1s and 0.2s snap to 0ms.
        user, _, clip = await _user_with_clip("edit-crop-snap-collapse@example.com", duration=10.0, bpm=120)
        resp = await client.post(
            _edit_url(clip.id, "crop"),
            json={"start": "0.1s", "end": "0.2s", "snap_to_beat": True},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 422
        assert await Job.count() == 0

    async def test_clip_without_duration_returns_422(self, client, settings) -> None:
        user, _, clip = await _user_with_clip("edit-crop-nodur@example.com", duration=None)
        resp = await client.post(
            _edit_url(clip.id, "crop"),
            json={"start": "1s", "end": "5s"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 422
        assert await Job.count() == 0


@pytest.mark.integration
class TestSpeedValidation:
    @pytest.mark.parametrize(
        "body",
        [
            {},  # neither multiplier nor target_bpm
            {"multiplier": 1.2, "target_bpm": 100},  # both
            {"multiplier": 0.4},  # below range
            {"multiplier": 2.5},  # above range
            {"multiplier": 0},  # not positive
            {"multiplier": 1.2, "bogus": True},  # extra="forbid"
            {"target_bpm": 0},  # not positive
        ],
    )
    async def test_invalid_request_returns_422(self, client, settings, body: dict) -> None:
        user, _, clip = await _user_with_clip("edit-speed-422@example.com", duration=10.0, bpm=120)
        resp = await client.post(_edit_url(clip.id, "speed"), json=body, headers=_auth_headers(user, settings))
        assert resp.status_code == 422
        assert await Job.count() == 0

    async def test_target_bpm_without_source_bpm_returns_422(self, client, settings) -> None:
        user, _, clip = await _user_with_clip("edit-speed-nobpm@example.com", duration=10.0, bpm=None)
        resp = await client.post(
            _edit_url(clip.id, "speed"),
            json={"target_bpm": 100},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 422
        assert await Job.count() == 0

    async def test_target_bpm_yielding_out_of_range_rate_returns_422(self, client, settings) -> None:
        # 120 → 30 BPM needs rate 0.25, below the allowed 0.5–2.0 window.
        user, _, clip = await _user_with_clip("edit-speed-range@example.com", duration=10.0, bpm=120)
        resp = await client.post(
            _edit_url(clip.id, "speed"),
            json={"target_bpm": 30},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 422
        # The error must name the offending BPM (mirrors the CLI message).
        assert "30" in str(resp.json()["detail"])
        assert await Job.count() == 0

    async def test_clip_without_duration_returns_422(self, client, settings) -> None:
        user, _, clip = await _user_with_clip("edit-speed-nodur@example.com", duration=None)
        resp = await client.post(
            _edit_url(clip.id, "speed"),
            json={"multiplier": 1.5},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 422
        assert await Job.count() == 0


@pytest.mark.integration
class TestRemasterValidation:
    async def test_non_wav_clip_returns_422(self, client, settings) -> None:
        user, _, clip = await _user_with_clip("edit-remaster-mp3@example.com", fmt="mp3")
        resp = await client.post(_edit_url(clip.id, "remaster"), json={}, headers=_auth_headers(user, settings))
        assert resp.status_code == 422
        assert await Job.count() == 0

    async def test_extra_field_returns_422(self, client, settings) -> None:
        user, _, clip = await _user_with_clip("edit-remaster-extra@example.com")
        resp = await client.post(
            _edit_url(clip.id, "remaster"),
            json={"bogus": True},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 422
        assert await Job.count() == 0


# ---------------------------------------------------------------------------
# 202 — job creation
# ---------------------------------------------------------------------------


async def _get_only_job() -> Job:
    jobs = await Job.find_all().to_list()
    assert len(jobs) == 1
    return jobs[0]


@pytest.mark.integration
class TestCropEnqueue:
    async def test_returns_202_and_persists_resolved_params(self, client, settings) -> None:
        user, workspace, clip = await _user_with_clip("edit-crop-202@example.com", duration=10.0)

        resp = await client.post(
            _edit_url(clip.id, "crop"),
            json={"start": "1s", "end": "2.5s", "fade_out": "0.5s"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "queued"

        job = await _get_only_job()
        assert str(job.id) == body["job_id"]
        assert job.job_type == "crop"
        assert job.status == JobStatus.QUEUED
        assert job.user_id == user.id
        assert job.workspace_id == workspace.id
        assert job.input_params == {
            "clip_id": str(clip.id),
            "start_ms": 1000,
            "end_ms": 2500,
            "fade_in_ms": 0,
            "fade_out_ms": 500,
        }

    async def test_snap_to_beat_resolves_snapped_bounds(self, client, settings) -> None:
        # bpm=120 → beat every 500ms; 0.6s snaps to 500ms, 1.7s to 1500ms.
        user, _, clip = await _user_with_clip("edit-crop-snap@example.com", duration=10.0, bpm=120)

        resp = await client.post(
            _edit_url(clip.id, "crop"),
            json={"start": "0.6s", "end": "1.7s", "snap_to_beat": True},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 202

        job = await _get_only_job()
        assert job.input_params["start_ms"] == 500
        assert job.input_params["end_ms"] == 1500


@pytest.mark.integration
class TestSpeedEnqueue:
    async def test_multiplier_returns_202_and_persists_params(self, client, settings) -> None:
        user, workspace, clip = await _user_with_clip("edit-speed-202@example.com", duration=10.0)

        resp = await client.post(
            _edit_url(clip.id, "speed"),
            json={"multiplier": 1.5},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "queued"

        job = await _get_only_job()
        assert str(job.id) == body["job_id"]
        assert job.job_type == "speed"
        assert job.status == JobStatus.QUEUED
        assert job.workspace_id == workspace.id
        assert job.input_params == {
            "clip_id": str(clip.id),
            "multiplier": 1.5,
            "preserve_pitch": True,
        }

    async def test_target_bpm_resolves_final_multiplier(self, client, settings) -> None:
        user, _, clip = await _user_with_clip("edit-speed-bpm@example.com", duration=10.0, bpm=100)

        resp = await client.post(
            _edit_url(clip.id, "speed"),
            json={"target_bpm": 150},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 202

        job = await _get_only_job()
        assert job.input_params["multiplier"] == pytest.approx(1.5)

    async def test_preserve_pitch_false_logs_warning(self, client, settings, caplog, monkeypatch) -> None:
        user, _, clip = await _user_with_clip("edit-speed-pitch@example.com", duration=10.0)

        # The app pins acemusic logs to its own handler (propagate=False in
        # _ensure_app_logging); caplog listens on the root logger, so re-enable
        # propagation for this assertion (mirrors test_credits_api).
        monkeypatch.setattr(logging.getLogger("acemusic"), "propagate", True)

        with caplog.at_level(logging.WARNING, logger="acemusic.api.routers.editing"):
            resp = await client.post(
                _edit_url(clip.id, "speed"),
                json={"multiplier": 1.5, "preserve_pitch": False},
                headers=_auth_headers(user, settings),
            )
        assert resp.status_code == 202
        assert any("preserve_pitch" in record.getMessage() for record in caplog.records)

        job = await _get_only_job()
        assert job.input_params["preserve_pitch"] is False


@pytest.mark.integration
class TestRemasterEnqueue:
    async def test_returns_202_with_default_target_lufs(self, client, settings) -> None:
        user, workspace, clip = await _user_with_clip("edit-remaster-202@example.com")

        resp = await client.post(_edit_url(clip.id, "remaster"), json={}, headers=_auth_headers(user, settings))
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "queued"

        job = await _get_only_job()
        assert str(job.id) == body["job_id"]
        assert job.job_type == "remaster"
        assert job.status == JobStatus.QUEUED
        assert job.workspace_id == workspace.id
        assert job.input_params == {"clip_id": str(clip.id), "target_lufs": -14.0}

    async def test_custom_target_lufs_is_persisted(self, client, settings) -> None:
        user, _, clip = await _user_with_clip("edit-remaster-lufs@example.com")

        resp = await client.post(
            _edit_url(clip.id, "remaster"),
            json={"target_lufs": -16.0},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 202

        job = await _get_only_job()
        assert job.input_params["target_lufs"] == -16.0
