"""Integration tests for the mastering endpoint (US-12.1).

Covers ``POST /api/v1/mastering/jobs``: each request validates against an owned
source clip, gates on per-service credits, and enqueues a queued job returning
202 with a trackable job id. The 401 auth-gate test runs in CI (no DB); the rest
are ``integration`` and drive the real app over a local MongoDB.
"""

import io

import httpx
import pytest
from beanie import PydanticObjectId
from fastapi.testclient import TestClient

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.models import Clip, CreditTransaction, Job, JobStatus, Workspace
from acemusic.api.services import mastering as mastering_service, users as user_service
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
        # The IDOR path must not charge the intruder (no credit leak).
        assert (await _reload(intruder)).credits_balance == 10.0


# ---------------------------------------------------------------------------
# Job-creation failure — credit is refunded
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestJobCreationFailure:
    async def test_credit_refunded_when_job_creation_raises(self, client, settings, monkeypatch) -> None:
        # If the deduction lands but the job never gets created, the router must
        # give the credit back rather than charge for work that will never run.
        user, _ws, clip = await _user_with_clip("master-refund@example.com", balance=10.0)

        async def _boom(**_kwargs):
            raise RuntimeError("job store down")

        monkeypatch.setattr(mastering_service, "create_mastering_job", _boom)
        # The ASGI test transport re-raises app exceptions; the refund happens in
        # the router's ``except`` before the error propagates.
        with pytest.raises(RuntimeError):
            await client.post(
                MASTERING_URL,
                json={"clip_id": str(clip.id), "profile": "streaming"},
                headers=_auth_headers(user, settings),
            )
        # Deducted (dolby=3) then refunded back to the original balance.
        assert (await _reload(user)).credits_balance == 10.0
        assert await Job.find(Job.user_id == user.id).count() == 0
        assert await CreditTransaction.find(CreditTransaction.user_id == user.id).count() == 0


# ===========================================================================
# US-12.4 — mastering preview / A/B comparison and approval
#
# Built on the as-built single-master pipeline: each mastering job produces ONE
# mastered clip, so "previews" are the completed mastered candidates for a source
# clip (one per job), and approval *promotes* an existing mastered clip to
# ``generation_mode="mastered"``.
# ===========================================================================

# The canonical metrics shape every backend normalises to (see test_mastering_tasks).
_MASTER_METRICS = {
    "loudness": -13.5,
    "eq_bands": [float(i) for i in range(16)],
    "stereo": {"width": 0.8, "balance": 0.0},
}


def _detail_url(job_id: str) -> str:
    return f"{API_V1_PREFIX}/mastering/jobs/{job_id}"


def _previews_url(job_id: str) -> str:
    return f"{API_V1_PREFIX}/mastering/jobs/{job_id}/previews"


def _approve_url(job_id: str) -> str:
    return f"{API_V1_PREFIX}/mastering/jobs/{job_id}/approve"


def _wav_bytes(seconds: float = 1.0, sr: int = 22050) -> bytes:
    """A short stereo tone, long enough for pyloudnorm's 400ms integration block."""
    import numpy as np
    import soundfile as sf

    t = np.linspace(0, seconds, int(sr * seconds), endpoint=False)
    tone = 0.2 * np.sin(2 * np.pi * 220 * t)
    stereo = np.column_stack([tone, tone])
    buf = io.BytesIO()
    sf.write(buf, stereo, sr, format="WAV", subtype="PCM_16")
    return buf.getvalue()


@pytest.fixture
def local_storage(monkeypatch, tmp_path):
    """Point the storage backend at a throwaway local root for get_url()/loudness."""
    monkeypatch.setenv("ACEMUSIC_STORAGE_BACKEND", "local")
    monkeypatch.setenv("ACEMUSIC_STORAGE_LOCAL_ROOT", str(tmp_path))
    return tmp_path


async def _insert_clip_doc(user, workspace_id, *, store_bytes=None, generation_mode=None, parents=None) -> Clip:
    from acemusic.storage import get_storage_backend

    clip_id = PydanticObjectId()
    file_path = f"{user.id}/{workspace_id}/clips/{clip_id}.wav"
    if store_bytes is not None:
        get_storage_backend().upload(file_path, store_bytes)
    clip = Clip(
        id=clip_id,
        user_id=user.id,
        workspace_id=workspace_id,
        file_path=file_path,
        format="wav",
        duration=10.0,
        parent_clip_ids=parents or [],
        generation_mode=generation_mode,
    )
    await clip.insert()
    return clip


async def _insert_mastering_job(
    user,
    *,
    source_clip_id,
    workspace_id,
    status=JobStatus.COMPLETED,
    profile="streaming",
    service="dolby",
    mastered_clip=None,
    metrics=None,
    job_type="mastering",
) -> Job:
    result = None
    if status == JobStatus.COMPLETED:
        result = {
            "clip_ids": [str(mastered_clip.id)] if mastered_clip is not None else [],
            "service": service,
            "target_lufs": -14.0,
            "metrics": metrics if metrics is not None else _MASTER_METRICS,
        }
    job = Job(
        user_id=user.id,
        workspace_id=workspace_id,
        job_type=job_type,
        status=status,
        input_params={
            "clip_id": source_clip_id,
            "profile": profile,
            "service": service,
            "format": "wav",
            "target_lufs": -14.0,
        },
        result=result,
    )
    await job.insert()
    return job


class TestPreviewAuthGate:
    def test_get_detail_missing_auth_returns_401(self) -> None:
        client = TestClient(create_app())
        assert client.get(_detail_url(str(PydanticObjectId()))).status_code == 401

    def test_get_previews_missing_auth_returns_401(self) -> None:
        client = TestClient(create_app())
        assert client.get(_previews_url(str(PydanticObjectId()))).status_code == 401

    def test_approve_missing_auth_returns_401(self) -> None:
        client = TestClient(create_app())
        resp = client.post(_approve_url(str(PydanticObjectId())), json={"preview_id": str(PydanticObjectId())})
        assert resp.status_code == 401


@pytest.mark.integration
class TestMasteringJobDetail:
    async def test_unknown_job_returns_404(self, client, settings) -> None:
        user = await _make_user("m124-detail-unknown@example.com")
        resp = await client.get(_detail_url(str(PydanticObjectId())), headers=_auth_headers(user, settings))
        assert resp.status_code == 404

    async def test_other_users_job_returns_404(self, client, settings) -> None:
        owner = await _make_user("m124-detail-owner@example.com")
        other = await _make_user("m124-detail-other@example.com")
        job = await _insert_mastering_job(
            owner, source_clip_id=str(PydanticObjectId()), workspace_id=PydanticObjectId()
        )
        resp = await client.get(_detail_url(str(job.id)), headers=_auth_headers(other, settings))
        assert resp.status_code == 404

    async def test_non_mastering_job_returns_404(self, client, settings) -> None:
        user = await _make_user("m124-detail-wrongtype@example.com")
        job = await _insert_mastering_job(
            user, source_clip_id=str(PydanticObjectId()), workspace_id=PydanticObjectId(), job_type="generate"
        )
        resp = await client.get(_detail_url(str(job.id)), headers=_auth_headers(user, settings))
        assert resp.status_code == 404

    async def test_queued_job_is_minimal(self, client, settings) -> None:
        user = await _make_user("m124-detail-queued@example.com")
        ws = PydanticObjectId()
        src = await _insert_clip_doc(user, ws)
        job = await _insert_mastering_job(user, source_clip_id=str(src.id), workspace_id=ws, status=JobStatus.QUEUED)
        resp = await client.get(_detail_url(str(job.id)), headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "queued"
        assert body["source_clip_id"] == str(src.id)
        assert body["profile"] == "streaming"
        assert "metrics" not in body
        assert "mastered_clip_id" not in body

    async def test_completed_job_has_metrics_and_mastered_clip(self, client, settings) -> None:
        user = await _make_user("m124-detail-done@example.com")
        ws = PydanticObjectId()
        src = await _insert_clip_doc(user, ws)
        mastered = await _insert_clip_doc(user, ws, generation_mode="mastering", parents=[src.id])
        job = await _insert_mastering_job(user, source_clip_id=str(src.id), workspace_id=ws, mastered_clip=mastered)
        resp = await client.get(_detail_url(str(job.id)), headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "completed"
        assert body["mastered_clip_id"] == str(mastered.id)
        assert body["metrics"]["loudness"] == _MASTER_METRICS["loudness"]
        assert body["service"] == "dolby"


@pytest.mark.integration
class TestMasteringPreviews:
    async def test_unowned_job_returns_404(self, client, settings) -> None:
        owner = await _make_user("m124-prev-owner@example.com")
        other = await _make_user("m124-prev-other@example.com")
        job = await _insert_mastering_job(
            owner, source_clip_id=str(PydanticObjectId()), workspace_id=PydanticObjectId()
        )
        resp = await client.get(_previews_url(str(job.id)), headers=_auth_headers(other, settings))
        assert resp.status_code == 404

    async def test_returns_original_and_candidate_metrics(self, client, settings, local_storage) -> None:
        user = await _make_user("m124-prev-ab@example.com")
        ws = PydanticObjectId()
        src = await _insert_clip_doc(user, ws, store_bytes=_wav_bytes())
        mastered = await _insert_clip_doc(user, ws, generation_mode="mastering", parents=[src.id])
        job = await _insert_mastering_job(user, source_clip_id=str(src.id), workspace_id=ws, mastered_clip=mastered)
        resp = await client.get(_previews_url(str(job.id)), headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        body = resp.json()
        assert body["original_audio_url"]
        # Original-side metric is measured locally: integrated LUFS is a finite float.
        assert isinstance(body["original_metrics"]["loudness"], float)
        assert len(body["previews"]) == 1
        preview = body["previews"][0]
        assert preview["preview_id"] == str(mastered.id)
        assert preview["audio_url"]
        assert preview["metrics"]["loudness"] == _MASTER_METRICS["loudness"]

    async def test_aggregates_multiple_candidates_for_one_source(self, client, settings, local_storage) -> None:
        user = await _make_user("m124-prev-multi@example.com")
        ws = PydanticObjectId()
        src = await _insert_clip_doc(user, ws, store_bytes=_wav_bytes())
        m1 = await _insert_clip_doc(user, ws, generation_mode="mastering", parents=[src.id])
        m2 = await _insert_clip_doc(user, ws, generation_mode="mastering", parents=[src.id])
        await _insert_mastering_job(
            user, source_clip_id=str(src.id), workspace_id=ws, profile="streaming", mastered_clip=m1
        )
        job2 = await _insert_mastering_job(
            user, source_clip_id=str(src.id), workspace_id=ws, profile="club", mastered_clip=m2
        )
        resp = await client.get(_previews_url(str(job2.id)), headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        ids = {p["preview_id"] for p in resp.json()["previews"]}
        assert ids == {str(m1.id), str(m2.id)}


@pytest.mark.integration
class TestMasteringApprove:
    async def test_unowned_job_returns_404(self, client, settings) -> None:
        owner = await _make_user("m124-appr-owner@example.com")
        other = await _make_user("m124-appr-other@example.com")
        job = await _insert_mastering_job(
            owner, source_clip_id=str(PydanticObjectId()), workspace_id=PydanticObjectId()
        )
        resp = await client.post(
            _approve_url(str(job.id)),
            json={"preview_id": str(PydanticObjectId())},
            headers=_auth_headers(other, settings),
        )
        assert resp.status_code == 404

    async def test_invalid_preview_id_returns_404(self, client, settings) -> None:
        user = await _make_user("m124-appr-bad@example.com")
        ws = PydanticObjectId()
        src = await _insert_clip_doc(user, ws)
        mastered = await _insert_clip_doc(user, ws, generation_mode="mastering", parents=[src.id])
        job = await _insert_mastering_job(user, source_clip_id=str(src.id), workspace_id=ws, mastered_clip=mastered)
        resp = await client.post(
            _approve_url(str(job.id)),
            json={"preview_id": str(PydanticObjectId())},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 404

    async def test_approve_promotes_clip(self, client, settings, local_storage) -> None:
        user = await _make_user("m124-appr-ok@example.com")
        ws = PydanticObjectId()
        src = await _insert_clip_doc(user, ws)
        mastered = await _insert_clip_doc(user, ws, generation_mode="mastering", parents=[src.id])
        job = await _insert_mastering_job(user, source_clip_id=str(src.id), workspace_id=ws, mastered_clip=mastered)
        resp = await client.post(
            _approve_url(str(job.id)),
            json={"preview_id": str(mastered.id)},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["clip_id"] == str(mastered.id)
        assert body["audio_url"]
        # Promotion: the existing clip becomes the final master, lineage preserved.
        refreshed = await Clip.get(mastered.id)
        assert refreshed.generation_mode == "mastered"
        assert refreshed.parent_clip_ids == [src.id]

    async def test_approve_is_idempotent(self, client, settings, local_storage) -> None:
        user = await _make_user("m124-appr-idem@example.com")
        ws = PydanticObjectId()
        src = await _insert_clip_doc(user, ws)
        mastered = await _insert_clip_doc(user, ws, generation_mode="mastering", parents=[src.id])
        job = await _insert_mastering_job(user, source_clip_id=str(src.id), workspace_id=ws, mastered_clip=mastered)
        headers = _auth_headers(user, settings)
        first = await client.post(_approve_url(str(job.id)), json={"preview_id": str(mastered.id)}, headers=headers)
        second = await client.post(_approve_url(str(job.id)), json={"preview_id": str(mastered.id)}, headers=headers)
        assert first.status_code == 200
        assert second.status_code == 200
        assert (await Clip.get(mastered.id)).generation_mode == "mastered"
