"""Tests for the iterative generation endpoints (US-10.3, issue #83).

Covers the seven AI-powered iterative modes — ``extend``, ``cover``, ``remix``,
``repaint``, ``sample``, ``add-vocal`` (clip-scoped) and ``mashup`` (standalone,
multi-source). Each validates against its source clip(s), deducts credits at
queue time, enqueues a job and returns 202 with a trackable job id.

The 401 auth-gate tests run in CI (no DB); the rest are ``integration`` and
drive the real app with ``httpx.AsyncClient`` over a local MongoDB.
"""

import asyncio
import io
import time

import httpx
import numpy as np
import pytest
import soundfile as sf
from beanie import PydanticObjectId
from fastapi.testclient import TestClient

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.models import Clip, CreditTransaction, Job, User, Workspace
from acemusic.api.services import users as user_service
from acemusic.api.settings import ApiSettings
from acemusic.storage import get_storage_backend

CLIPS_URL = f"{API_V1_PREFIX}/clips"
MASHUP_URL = f"{API_V1_PREFIX}/mashup"

# Clip-scoped operations and a minimal valid body for each (used where the test
# target is not the payload itself). ``mashup`` is exercised separately.
CLIP_OPS = ["extend", "cover", "remix", "repaint", "sample", "add-vocal"]
VALID_BODIES = {
    "extend": {"duration": "30s"},
    "cover": {"style": "jazz"},
    "remix": {"style": "lofi"},
    "repaint": {"start": "1s", "end": "5s", "prompt": "add strings"},
    "sample": {"start": "1s", "end": "3s", "role": "loop-bed", "prompt": "build a beat"},
    "add-vocal": {"lyrics": "la la la"},
}
# Endpoint path segment (with hyphen) → job_type (with underscore).
JOB_TYPE = {
    "extend": "extend",
    "cover": "cover",
    "remix": "remix",
    "repaint": "repaint",
    "sample": "sample",
    "add-vocal": "add_vocal",
}


def _op_url(clip_id, operation: str) -> str:
    return f"{CLIPS_URL}/{clip_id}/{operation}"


# ---------------------------------------------------------------------------
# Auth gate — runs in CI (no DB; plain TestClient does not run the lifespan)
# ---------------------------------------------------------------------------


class TestAuthGate:
    @pytest.mark.parametrize("operation", CLIP_OPS)
    def test_missing_auth_header_returns_401(self, operation: str) -> None:
        client = TestClient(create_app())
        resp = client.post(_op_url(PydanticObjectId(), operation), json=VALID_BODIES[operation])
        assert resp.status_code == 401

    def test_mashup_missing_auth_header_returns_401(self) -> None:
        client = TestClient(create_app())
        resp = client.post(MASHUP_URL, json={"clip_ids": [str(PydanticObjectId()), str(PydanticObjectId())]})
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


async def _insert_clip(
    user,
    workspace: Workspace,
    *,
    duration: float | None = 10.0,
    bpm: int | None = 120,
    key: str | None = "C",
    fmt: str | None = "wav",
) -> Clip:
    clip_id = PydanticObjectId()
    file_path = f"{user.id}/{workspace.id}/clips/{clip_id}.{fmt or 'wav'}"
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


async def _user_with_clip(email: str, *, balance: float = 10.0, **clip_kwargs):
    user = await _make_user(email, balance=balance)
    workspace = await _make_workspace(user)
    clip = await _insert_clip(user, workspace, **clip_kwargs)
    return user, workspace, clip


# ---------------------------------------------------------------------------
# 404 — unknown / malformed / other-user clip ids
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestClipNotFound:
    @pytest.mark.parametrize("operation", CLIP_OPS)
    async def test_unknown_clip_returns_404(self, client, settings, operation: str) -> None:
        user = await _make_user(f"iter-404-{operation}@example.com", balance=10.0)
        resp = await client.post(
            _op_url(PydanticObjectId(), operation),
            json=VALID_BODIES[operation],
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 404
        assert await Job.count() == 0

    @pytest.mark.parametrize("operation", CLIP_OPS)
    async def test_malformed_id_returns_404(self, client, settings, operation: str) -> None:
        user = await _make_user(f"iter-malformed-{operation}@example.com", balance=10.0)
        resp = await client.post(
            _op_url("not-an-object-id", operation),
            json=VALID_BODIES[operation],
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 404

    @pytest.mark.parametrize("operation", CLIP_OPS)
    async def test_other_users_clip_returns_404(self, client, settings, operation: str) -> None:
        _, _, clip = await _user_with_clip(f"iter-owner-{operation}@example.com")
        other = await _make_user(f"iter-other-{operation}@example.com", balance=10.0)
        resp = await client.post(
            _op_url(clip.id, operation),
            json=VALID_BODIES[operation],
            headers=_auth_headers(other, settings),
        )
        assert resp.status_code == 404
        # No credit was spent on a clip the requester cannot see.
        assert (await _reload_user(other)).credits_balance == 10.0
        assert await Job.count() == 0


async def _reload_user(user) -> User:
    return await User.get(user.id)


# ---------------------------------------------------------------------------
# 202 — happy path: job persisted, params forwarded, credits deducted
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestEnqueueSuccess:
    @pytest.mark.parametrize("operation", CLIP_OPS)
    async def test_returns_202_with_job_id(self, client, settings, operation: str) -> None:
        user, _, clip = await _user_with_clip(f"iter-202-{operation}@example.com")
        resp = await client.post(
            _op_url(clip.id, operation),
            json=VALID_BODIES[operation],
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "queued"
        assert body["job_id"]
        assert body["estimated_time_seconds"] > 0

    @pytest.mark.parametrize("operation", CLIP_OPS)
    async def test_persists_job_with_clip_lineage_param(self, client, settings, operation: str) -> None:
        user, workspace, clip = await _user_with_clip(f"iter-job-{operation}@example.com")
        resp = await client.post(
            _op_url(clip.id, operation),
            json=VALID_BODIES[operation],
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 202
        jobs = await Job.find_all().to_list()
        assert len(jobs) == 1
        job = jobs[0]
        assert job.job_type == JOB_TYPE[operation]
        assert job.user_id == user.id
        assert job.workspace_id == workspace.id
        assert job.input_params["clip_id"] == str(clip.id)

    async def test_extend_forwards_duration(self, client, settings) -> None:
        user, _, clip = await _user_with_clip("iter-extend-params@example.com")
        resp = await client.post(
            _op_url(clip.id, "extend"),
            json={"duration": "45s", "lyrics": "ooh"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 202
        job = (await Job.find_all().to_list())[0]
        assert job.input_params["duration"] == "45s"
        assert job.input_params["from_point"] == "end"
        assert job.input_params["lyrics"] == "ooh"

    async def test_repaint_forwards_resolved_ms_bounds(self, client, settings) -> None:
        user, _, clip = await _user_with_clip("iter-repaint-params@example.com")
        resp = await client.post(
            _op_url(clip.id, "repaint"),
            json={"start": "2s", "end": "5s", "prompt": "add a guitar solo"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 202
        job = (await Job.find_all().to_list())[0]
        assert job.input_params["start_ms"] == 2000
        assert job.input_params["end_ms"] == 5000
        assert job.input_params["prompt"] == "add a guitar solo"

    async def test_deducts_one_credit(self, client, settings) -> None:
        user, _, clip = await _user_with_clip("iter-credit@example.com", balance=10.0)
        resp = await client.post(
            _op_url(clip.id, "cover"),
            json={"style": "jazz"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 202
        assert (await _reload_user(user)).credits_balance == 9.0
        txns = await CreditTransaction.find(CreditTransaction.user_id == user.id).to_list()
        assert len(txns) == 1
        assert txns[0].amount == -1.0
        assert txns[0].action_type == "cover"

    async def test_status_endpoint_reports_iterative_eta(self, client, settings) -> None:
        # A queued iterative job keeps a real ETA when polled (not the 0 fallback).
        user, _, clip = await _user_with_clip("iter-eta@example.com")
        accepted = await client.post(
            _op_url(clip.id, "cover"), json={"style": "jazz"}, headers=_auth_headers(user, settings)
        )
        assert accepted.status_code == 202
        job_id = accepted.json()["job_id"]
        status = await client.get(f"{API_V1_PREFIX}/jobs/{job_id}/status", headers=_auth_headers(user, settings))
        assert status.status_code == 200
        assert status.json()["estimated_time_seconds"] == 45

    async def test_status_endpoint_scales_sample_eta(self, client, settings) -> None:
        user, _, clip = await _user_with_clip("iter-eta-sample@example.com")
        accepted = await client.post(
            _op_url(clip.id, "sample"),
            json={"start": "1s", "end": "3s", "role": "loop-bed", "prompt": "beat", "num_clips": 2},
            headers=_auth_headers(user, settings),
        )
        assert accepted.status_code == 202
        job_id = accepted.json()["job_id"]
        status = await client.get(f"{API_V1_PREFIX}/jobs/{job_id}/status", headers=_auth_headers(user, settings))
        assert status.json()["estimated_time_seconds"] == 90

    async def test_sample_cost_scales_with_num_clips(self, client, settings) -> None:
        user, _, clip = await _user_with_clip("iter-sample-cost@example.com", balance=10.0)
        resp = await client.post(
            _op_url(clip.id, "sample"),
            json={"start": "1s", "end": "3s", "role": "loop-bed", "prompt": "beat", "num_clips": 3},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 202
        assert (await _reload_user(user)).credits_balance == 7.0
        job = (await Job.find_all().to_list())[0]
        assert job.input_params["num_clips"] == 3


# ---------------------------------------------------------------------------
# 402 — insufficient credits
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestInsufficientCredits:
    async def test_returns_402_with_balance_payload(self, client, settings) -> None:
        user, _, clip = await _user_with_clip("iter-poor@example.com", balance=0.25)
        resp = await client.post(
            _op_url(clip.id, "cover"),
            json={"style": "jazz"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 402
        detail = resp.json()["detail"]
        assert detail["error"] == "insufficient_credits"
        assert detail["balance"] == 0.25
        assert detail["required"] == 1.0
        assert await Job.count() == 0

    async def test_balance_unchanged_on_402(self, client, settings) -> None:
        user, _, clip = await _user_with_clip("iter-poor-nojob@example.com", balance=0.25)
        resp = await client.post(
            _op_url(clip.id, "extend"),
            json={"duration": "30s"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 402
        assert (await _reload_user(user)).credits_balance == 0.25


# ---------------------------------------------------------------------------
# 422 — validation matrix
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestValidation:
    @pytest.mark.parametrize(
        "operation,body",
        [
            ("extend", {"duration": "soon"}),  # unparseable time
            ("extend", {"duration": "0s"}),  # zero-length no-op
            ("extend", {"duration": "0"}),  # zero-length no-op (plain seconds)
            ("extend", {}),  # missing required duration
            ("extend", {"duration": "30s", "bogus": 1}),  # extra="forbid"
            ("cover", {}),  # missing required style
            ("cover", {"style": ""}),  # empty style
            ("cover", {"style": "jazz", "voice_id": "v1"}),  # voice_id dropped (US-15.7), extra="forbid"
            ("remix", {}),  # missing required style
            ("repaint", {"start": "1s", "end": "5s"}),  # missing prompt
            ("repaint", {"start": "x", "end": "5s", "prompt": "p"}),  # unparseable start
            ("sample", {"start": "1s", "end": "3s", "prompt": "p"}),  # missing role
            ("sample", {"start": "1s", "end": "3s", "role": "bogus", "prompt": "p"}),  # bad enum
            ("sample", {"start": "1s", "end": "3s", "role": "loop-bed", "prompt": "p", "num_clips": 0}),  # num < 1
            ("add-vocal", {}),  # missing lyrics
            ("add-vocal", {"lyrics": ""}),  # empty lyrics
            ("add-vocal", {"lyrics": "la", "voice_id": "v1"}),  # voice_id dropped (US-15.7), extra="forbid"
        ],
    )
    async def test_invalid_body_returns_422(self, client, settings, operation: str, body: dict) -> None:
        user, _, clip = await _user_with_clip(f"iter-422-{operation}-{len(body)}@example.com")
        resp = await client.post(_op_url(clip.id, operation), json=body, headers=_auth_headers(user, settings))
        assert resp.status_code == 422
        assert await Job.count() == 0

    @pytest.mark.parametrize("operation", ["repaint", "sample"])
    async def test_start_not_before_end_returns_422(self, client, settings, operation: str) -> None:
        user, _, clip = await _user_with_clip(f"iter-range-{operation}@example.com", duration=10.0)
        body = {**VALID_BODIES[operation], "start": "5s", "end": "5s"}
        resp = await client.post(_op_url(clip.id, operation), json=body, headers=_auth_headers(user, settings))
        assert resp.status_code == 422
        assert await Job.count() == 0

    @pytest.mark.parametrize("operation", ["repaint", "sample"])
    async def test_end_beyond_duration_returns_422(self, client, settings, operation: str) -> None:
        user, _, clip = await _user_with_clip(f"iter-beyond-{operation}@example.com", duration=10.0)
        body = {**VALID_BODIES[operation], "start": "1s", "end": "20s"}
        resp = await client.post(_op_url(clip.id, operation), json=body, headers=_auth_headers(user, settings))
        assert resp.status_code == 422

    async def test_sample_elevenlabs_backend_rejected(self, client, settings) -> None:
        user, _, clip = await _user_with_clip("iter-sample-el@example.com", duration=10.0)
        resp = await client.post(
            _op_url(clip.id, "sample"),
            json={"start": "1s", "end": "3s", "role": "loop-bed", "prompt": "p", "backend": "elevenlabs"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 422
        assert await Job.count() == 0

    async def test_extend_target_exceeding_max_duration_returns_422(self, client, settings) -> None:
        # from_point(end=10s) + duration(9999s) far exceeds DURATION_MAX (240s);
        # reject before charging so no oversized GPU job is queued.
        user, _, clip = await _user_with_clip("iter-extend-toolong@example.com", balance=10.0, duration=10.0)
        resp = await client.post(
            _op_url(clip.id, "extend"),
            json={"duration": "9999s"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 422
        assert await Job.count() == 0
        assert (await _reload_user(user)).credits_balance == 10.0

    @pytest.mark.parametrize("from_point", ["0s", "0", "20s"])
    async def test_extend_from_point_out_of_range_returns_422(self, client, settings, from_point: str) -> None:
        # 0 would trim to a zero-length prefix (worker error); past the end has no
        # audio to continue from — both must be rejected before charging.
        user, _, clip = await _user_with_clip("iter-extend-from@example.com", balance=10.0, duration=10.0)
        resp = await client.post(
            _op_url(clip.id, "extend"),
            json={"duration": "5s", "from_point": from_point},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 422
        assert await Job.count() == 0
        assert (await _reload_user(user)).credits_balance == 10.0

    @pytest.mark.parametrize("operation", CLIP_OPS)
    async def test_without_duration_metadata_returns_422_no_charge(self, client, settings, operation: str) -> None:
        # Every mode feeds the source duration to ACE-Step; a clip with no
        # duration metadata must be rejected before charging, not enqueued.
        user, _, clip = await _user_with_clip(f"iter-nodur-{operation}@example.com", balance=10.0, duration=None)
        resp = await client.post(
            _op_url(clip.id, operation),
            json=VALID_BODIES[operation],
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 422
        assert await Job.count() == 0
        assert (await _reload_user(user)).credits_balance == 10.0

    @pytest.mark.parametrize("operation", ["cover", "remix", "repaint", "add-vocal"])
    async def test_oversized_source_duration_returns_422_no_charge(self, client, settings, operation: str) -> None:
        # Modes that submit source.duration as ACE-Step audio_duration must reject
        # a source longer than the generation cap (240s) before charging.
        user, _, clip = await _user_with_clip(f"iter-toolong-{operation}@example.com", balance=10.0, duration=480.0)
        resp = await client.post(
            _op_url(clip.id, operation),
            json=VALID_BODIES[operation],
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 422
        assert await Job.count() == 0
        assert (await _reload_user(user)).credits_balance == 10.0

    @pytest.mark.parametrize("operation", ["extend", "sample"])
    async def test_oversized_source_allowed_for_trimming_modes(self, client, settings, operation: str) -> None:
        # extend trims to a prefix and sample works on a bounded range, so an
        # oversized source is fine as long as the request stays within the cap.
        user, _, clip = await _user_with_clip(f"iter-long-ok-{operation}@example.com", balance=10.0, duration=480.0)
        bodies = {
            "extend": {"duration": "5s", "from_point": "10s"},
            "sample": {"start": "1s", "end": "3s", "role": "loop-bed", "prompt": "beat"},
        }
        resp = await client.post(
            _op_url(clip.id, operation), json=bodies[operation], headers=_auth_headers(user, settings)
        )
        assert resp.status_code == 202

    async def test_oversized_free_text_returns_422(self, client, settings) -> None:
        # Free-text fields are persisted verbatim; an unbounded string must be
        # rejected (matches the generation API's caps) rather than bloating Mongo.
        user, _, clip = await _user_with_clip("iter-oversized@example.com", duration=10.0)
        resp = await client.post(
            _op_url(clip.id, "cover"),
            json={"style": "x" * 10_001},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 422
        assert await Job.count() == 0

    async def test_non_wav_source_returns_422(self, client, settings) -> None:
        user, _, clip = await _user_with_clip("iter-nonwav@example.com", fmt="mp3")
        resp = await client.post(
            _op_url(clip.id, "cover"),
            json={"style": "jazz"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 422
        assert await Job.count() == 0


# ---------------------------------------------------------------------------
# Mashup — multi-source rules
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestMashup:
    async def test_two_clips_returns_202_with_lineage(self, client, settings) -> None:
        user = await _make_user("iter-mashup-ok@example.com", balance=10.0)
        ws = await _make_workspace(user)
        a = await _insert_clip(user, ws)
        b = await _insert_clip(user, ws)
        resp = await client.post(
            MASHUP_URL,
            json={"clip_ids": [str(a.id), str(b.id)]},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 202
        job = (await Job.find_all().to_list())[0]
        assert job.job_type == "mashup"
        assert job.input_params["clip_ids"] == [str(a.id), str(b.id)]
        assert job.workspace_id == a.workspace_id
        # Mashup costs 2 credits per the documented pricing (blends >1 source).
        assert (await _reload_user(user)).credits_balance == 8.0
        txns = await CreditTransaction.find(CreditTransaction.user_id == user.id).to_list()
        assert txns[0].amount == -2.0

    async def test_too_many_clips_returns_422(self, client, settings) -> None:
        # The source list is capped to keep one request's work bounded.
        user = await _make_user("iter-mashup-many@example.com", balance=10.0)
        ws = await _make_workspace(user)
        clips = [await _insert_clip(user, ws) for _ in range(9)]
        resp = await client.post(
            MASHUP_URL,
            json={"clip_ids": [str(c.id) for c in clips]},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 422
        assert await Job.count() == 0

    async def test_no_duration_source_returns_422(self, client, settings) -> None:
        user = await _make_user("iter-mashup-nodur@example.com", balance=10.0)
        ws = await _make_workspace(user)
        a = await _insert_clip(user, ws, duration=10.0)
        b = await _insert_clip(user, ws, duration=None)
        resp = await client.post(
            MASHUP_URL,
            json={"clip_ids": [str(a.id), str(b.id)]},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 422
        assert await Job.count() == 0
        assert (await _reload_user(user)).credits_balance == 10.0

    async def test_fewer_than_two_clips_returns_422(self, client, settings) -> None:
        user, _, clip = await _user_with_clip("iter-mashup-one@example.com")
        resp = await client.post(
            MASHUP_URL,
            json={"clip_ids": [str(clip.id)]},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 422
        assert await Job.count() == 0

    @pytest.mark.parametrize("second", [lambda c: str(c.id), lambda c: str(c.id).upper()])
    async def test_duplicate_clip_ids_returns_422(self, client, settings, second) -> None:
        # The same id — even in different hex casing (ObjectId is case-insensitive)
        # — must be rejected as a duplicate source.
        user, _, clip = await _user_with_clip("iter-mashup-dup@example.com")
        resp = await client.post(
            MASHUP_URL,
            json={"clip_ids": [str(clip.id), second(clip)]},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 422
        assert await Job.count() == 0

    async def test_unowned_source_returns_404(self, client, settings) -> None:
        user = await _make_user("iter-mashup-unowned@example.com", balance=10.0)
        ws = await _make_workspace(user)
        mine = await _insert_clip(user, ws)
        other = await _make_user("iter-mashup-other@example.com")
        ws2 = await _make_workspace(other)
        theirs = await _insert_clip(other, ws2)
        resp = await client.post(
            MASHUP_URL,
            json={"clip_ids": [str(mine.id), str(theirs.id)]},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 404
        assert await Job.count() == 0


# ---------------------------------------------------------------------------
# End-to-end — endpoint → queued job → JobProcessor → completed clip
# ---------------------------------------------------------------------------


def _wav_bytes(duration_s: float = 2.0, freq: float = 440.0, sr: int = 44100) -> bytes:
    t = np.linspace(0, duration_s, int(sr * duration_s), endpoint=False)
    mono = (0.3 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    buf = io.BytesIO()
    sf.write(buf, np.column_stack([mono, mono]), sr, format="WAV")
    return buf.getvalue()


class _FakeAce:
    """Stand-in ACE-Step client: returns a canned WAV without a live server."""

    def __init__(self, output: bytes) -> None:
        self.output = output
        self._n = 1

    def submit_task(self, **kwargs) -> str:
        self._n = kwargs.get("num_clips", 1) or 1
        return "task-1"

    def query_result(self, task_id: str) -> dict:
        return {"status": "completed", "audio_urls": [f"u{i}" for i in range(self._n)], "error": None}

    def download_audio(self, url: str) -> bytes:
        return self.output


@pytest.fixture
def local_storage(monkeypatch, tmp_path):
    """Point the storage backend at a throwaway local root."""
    monkeypatch.setenv("ACEMUSIC_STORAGE_BACKEND", "local")
    monkeypatch.setenv("ACEMUSIC_STORAGE_LOCAL_ROOT", str(tmp_path / "storage"))
    return tmp_path


@pytest.mark.integration
class TestIterativeLifecycleEndToEnd:
    """The cover job runs queued → completed via the real JobProcessor.

    ``httpx.ASGITransport`` does not run the app lifespan, so the production
    :class:`JobProcessor` is started directly — here with a fake ACE-Step client
    factory (no live server) over the same local storage the endpoint wrote to.
    """

    async def test_cover_runs_to_completed_via_status_endpoint(self, client, settings, local_storage) -> None:
        from acemusic.api.tasks.processor import JobProcessor

        user = await _make_user("iter-e2e-cover@example.com", balance=10.0)
        workspace = await _make_workspace(user)
        clip_id = PydanticObjectId()
        file_path = f"{user.id}/{workspace.id}/clips/{clip_id}.wav"
        get_storage_backend().upload(file_path, _wav_bytes(2.0))
        clip = Clip(
            id=clip_id,
            user_id=user.id,
            workspace_id=workspace.id,
            file_path=file_path,
            format="wav",
            duration=2.0,
            bpm=120,
            key="C",
        )
        await clip.insert()
        headers = _auth_headers(user, settings)

        accepted = await client.post(_op_url(clip.id, "cover"), json={"style": "jazz"}, headers=headers)
        assert accepted.status_code == 202
        job_id = accepted.json()["job_id"]

        processor = JobProcessor(
            concurrency=1,
            poll_interval=0.05,
            ace_poll_interval=0.01,
            client_factory=lambda: _FakeAce(_wav_bytes(2.0)),
        )
        await processor.start()
        try:
            status_body = None
            deadline = time.monotonic() + 30.0
            while time.monotonic() < deadline:
                resp = await client.get(f"{API_V1_PREFIX}/jobs/{job_id}/status", headers=headers)
                assert resp.status_code == 200
                status_body = resp.json()
                assert status_body["status"] in {"queued", "processing", "completed"}, status_body.get("error")
                if status_body["status"] == "completed":
                    break
                await asyncio.sleep(0.05)
        finally:
            await processor.stop()

        assert status_body is not None and status_body["status"] == "completed", "job never completed"
        assert len(status_body["clip_ids"]) == 1
        new_clip = await Clip.get(PydanticObjectId(status_body["clip_ids"][0]))
        assert new_clip.parent_clip_ids == [clip.id]
        assert new_clip.generation_mode == "cover"
        assert new_clip.generation_params["style"] == "jazz"
