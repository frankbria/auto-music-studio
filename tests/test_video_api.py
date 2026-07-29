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
from acemusic.api.models import Clip, CreditTransaction, Job, JobStatus, Video, VisibilityState, Workspace
from acemusic.api.services import users as user_service
from acemusic.api.services.video import VIDEO_JOB_TYPE
from acemusic.api.settings import ApiSettings
from acemusic.storage import get_storage_backend

GENERATE_URL = f"{API_V1_PREFIX}/videos/generate"


def _status_url(job_id: str) -> str:
    return f"{API_V1_PREFIX}/videos/{job_id}/status"


def _video_url(video_id: str) -> str:
    return f"{API_V1_PREFIX}/videos/{video_id}"


def _stream_url(video_id: str) -> str:
    return f"{API_V1_PREFIX}/videos/{video_id}/stream"


def _publish_url(video_id: str) -> str:
    return f"{API_V1_PREFIX}/videos/{video_id}/publish"


def _for_clip_url(clip_id: str) -> str:
    return f"{API_V1_PREFIX}/videos/for-clip/{clip_id}"


def _edit_url(video_id: str) -> str:
    return f"{API_V1_PREFIX}/videos/{video_id}/edit"


def _versions_url(video_id: str) -> str:
    return f"{API_V1_PREFIX}/videos/{video_id}/versions"


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
            # The generate endpoint 503s before any charge when the provider is
            # unconfigured (see TestNotConfigured), so these tests configure it.
            "video_api_url": "https://video.test",
            "video_api_key": "vk-test",
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

    async def test_non_http_reference_url_rejected(self, client, settings) -> None:
        user, _ws, clip = await _user_with_clip("video-ssrf@example.com", balance=10.0)
        for url in ("file:///etc/passwd", "ftp://x.test/a.png", "javascript:alert(1)"):
            resp = await client.post(
                GENERATE_URL,
                json=_valid_body(clip, reference_image_urls=[url]),
                headers=_auth_headers(user, settings),
            )
            assert resp.status_code == 422, url

    async def test_overlong_prompt_rejected(self, client, settings) -> None:
        user, _ws, clip = await _user_with_clip("video-longprompt@example.com", balance=10.0)
        resp = await client.post(
            GENERATE_URL,
            json=_valid_body(clip, prompt="x" * 2001),
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
# Unconfigured provider — 503 before any charge
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestNotConfigured:
    async def test_returns_503_with_no_charge_or_job(self, settings) -> None:
        """An unconfigured deployment must refuse up front: the worker would fail
        every claimed video job with "not configured", so charging first would be
        a guaranteed charge for nothing."""
        user, _ws, clip = await _user_with_clip("video-nocfg@example.com", balance=10.0)
        bare = settings.model_copy(update={"video_api_url": None, "video_api_key": None})
        async with _async_client(create_app(bare)) as client:
            resp = await client.post(GENERATE_URL, json=_valid_body(clip), headers=_auth_headers(user, bare))
        assert resp.status_code == 503
        assert "not configured" in resp.json()["detail"]
        assert (await _reload(user)).credits_balance == 10.0
        assert await Job.find(Job.user_id == user.id).count() == 0


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


# ---------------------------------------------------------------------------
# US-22.3 delivery: publish, metadata, playback/download, for-clip
# ---------------------------------------------------------------------------

_MP4_BYTES = b"\x00\x00\x00\x18ftypmp42" + b"\xde\xad\xbe\xef" * 64  # any non-audio bytes; the endpoint sets the type


@pytest.fixture
def local_storage(monkeypatch, tmp_path):
    """Point the storage backend at a throwaway local root."""
    monkeypatch.setenv("ACEMUSIC_STORAGE_BACKEND", "local")
    monkeypatch.setenv("ACEMUSIC_STORAGE_LOCAL_ROOT", str(tmp_path))
    return tmp_path


async def _make_public(clip: Clip) -> Clip:
    clip.is_public = True
    clip.visibility = VisibilityState.PUBLIC
    await clip.save()
    return clip


async def _insert_video(
    user,
    clip: Clip,
    *,
    published: bool = False,
    store: bool = True,
    data: bytes = _MP4_BYTES,
    resolution: str = "1080p",
    parent_video_id: PydanticObjectId | None = None,
    edit: dict | None = None,
    duration: float | None = None,
) -> Video:
    video_id = PydanticObjectId()
    job_id = PydanticObjectId()
    storage_path = f"{user.id}/{clip.workspace_id}/videos/{clip.id}/{job_id}.mp4"
    if store:
        get_storage_backend().upload(storage_path, data)
    video = Video(
        id=video_id,
        clip_id=clip.id,
        user_id=user.id,
        job_id=job_id,
        storage_path=storage_path,
        resolution=resolution,
        aspect_ratio="16:9",
        published=published,
        parent_video_id=parent_video_id,
        edit=edit,
        duration=duration,
    )
    await video.insert()
    return video


class TestDeliveryAuthGate:
    def test_publish_without_auth_returns_401(self) -> None:
        client = TestClient(create_app())
        resp = client.post(_publish_url(str(PydanticObjectId())))
        assert resp.status_code == 401


@pytest.mark.integration
class TestPublish:
    async def test_owner_publishes_video(self, client, settings, local_storage) -> None:
        user, _ws, clip = await _user_with_clip("video-pub@example.com")
        video = await _insert_video(user, clip, published=False)
        resp = await client.post(_publish_url(str(video.id)), headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        body = resp.json()
        assert body["published"] is True
        assert body["id"] == str(video.id)
        assert body["clip_id"] == str(clip.id)
        # Persisted, not just echoed back.
        assert (await Video.get(video.id)).published is True

    async def test_publish_is_idempotent(self, client, settings, local_storage) -> None:
        user, _ws, clip = await _user_with_clip("video-pub-idem@example.com")
        video = await _insert_video(user, clip, published=True)
        resp = await client.post(_publish_url(str(video.id)), headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        assert resp.json()["published"] is True

    async def test_other_users_video_returns_404_and_stays_private(self, client, settings, local_storage) -> None:
        owner, _ws, clip = await _user_with_clip("video-pub-owner@example.com")
        thief = await _make_user("video-pub-thief@example.com")
        video = await _insert_video(owner, clip, published=False)
        resp = await client.post(_publish_url(str(video.id)), headers=_auth_headers(thief, settings))
        assert resp.status_code == 404
        assert (await Video.get(video.id)).published is False

    async def test_unknown_video_returns_404(self, client, settings, local_storage) -> None:
        user = await _make_user("video-pub-unknown@example.com")
        resp = await client.post(_publish_url(str(PydanticObjectId())), headers=_auth_headers(user, settings))
        assert resp.status_code == 404


@pytest.mark.integration
class TestVideoDetail:
    async def test_owner_reads_own_unpublished_video(self, client, settings, local_storage) -> None:
        user, _ws, clip = await _user_with_clip("video-det-own@example.com")
        video = await _insert_video(user, clip, published=False)
        resp = await client.get(_video_url(str(video.id)), headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == str(video.id)
        assert body["resolution"] == "1080p"
        assert body["aspect_ratio"] == "16:9"
        assert body["published"] is False

    async def test_stranger_cannot_read_unpublished_video(self, client, settings, local_storage) -> None:
        owner, _ws, clip = await _user_with_clip("video-det-owner@example.com")
        stranger = await _make_user("video-det-stranger@example.com")
        video = await _insert_video(owner, clip, published=False)
        resp = await client.get(_video_url(str(video.id)), headers=_auth_headers(stranger, settings))
        assert resp.status_code == 404

    async def test_anyone_reads_published_video_on_public_clip(self, client, settings, local_storage) -> None:
        owner, _ws, clip = await _user_with_clip("video-det-pub@example.com")
        await _make_public(clip)
        video = await _insert_video(owner, clip, published=True)
        # Anonymous (no auth header) may read it — the song page is public.
        resp = await client.get(_video_url(str(video.id)))
        assert resp.status_code == 200
        assert resp.json()["published"] is True

    async def test_unknown_video_returns_404(self, client, settings, local_storage) -> None:
        resp = await client.get(_video_url(str(PydanticObjectId())))
        assert resp.status_code == 404


@pytest.mark.integration
class TestVideoStream:
    async def test_owner_streams_playable_mp4(self, client, settings, local_storage) -> None:
        user, _ws, clip = await _user_with_clip("video-str-own@example.com")
        video = await _insert_video(user, clip, published=False)
        resp = await client.get(_stream_url(str(video.id)), headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "video/mp4"
        assert resp.headers["accept-ranges"] == "bytes"
        assert resp.content == _MP4_BYTES

    async def test_range_request_returns_206_partial(self, client, settings, local_storage) -> None:
        user, _ws, clip = await _user_with_clip("video-str-range@example.com")
        video = await _insert_video(user, clip)
        headers = {**_auth_headers(user, settings), "Range": "bytes=0-9"}
        resp = await client.get(_stream_url(str(video.id)), headers=headers)
        assert resp.status_code == 206
        assert resp.content == _MP4_BYTES[:10]
        assert resp.headers["content-range"] == f"bytes 0-9/{len(_MP4_BYTES)}"

    async def test_download_sets_content_disposition(self, client, settings, local_storage) -> None:
        user, _ws, clip = await _user_with_clip("video-str-dl@example.com")
        video = await _insert_video(user, clip)
        resp = await client.get(
            _stream_url(str(video.id)), params={"download": "true"}, headers=_auth_headers(user, settings)
        )
        assert resp.status_code == 200
        assert resp.headers["content-disposition"] == f'attachment; filename="video-{video.id}.mp4"'

    async def test_stranger_cannot_stream_unpublished(self, client, settings, local_storage) -> None:
        owner, _ws, clip = await _user_with_clip("video-str-owner@example.com")
        stranger = await _make_user("video-str-stranger@example.com")
        video = await _insert_video(owner, clip, published=False)
        resp = await client.get(_stream_url(str(video.id)), headers=_auth_headers(stranger, settings))
        assert resp.status_code == 404

    async def test_published_video_on_private_clip_hidden_from_stranger(self, client, settings, local_storage) -> None:
        # Published but the source clip stays private: strangers still get 403
        # (the clip's own visibility governs a published video's reach).
        owner, _ws, clip = await _user_with_clip("video-str-privclip@example.com")
        stranger = await _make_user("video-str-privclip-other@example.com")
        video = await _insert_video(owner, clip, published=True)
        resp = await client.get(_stream_url(str(video.id)), headers=_auth_headers(stranger, settings))
        assert resp.status_code == 403

    async def test_anonymous_streams_published_public_video(self, client, settings, local_storage) -> None:
        owner, _ws, clip = await _user_with_clip("video-str-anon@example.com")
        await _make_public(clip)
        video = await _insert_video(owner, clip, published=True)
        resp = await client.get(_stream_url(str(video.id)))
        assert resp.status_code == 200
        assert resp.content == _MP4_BYTES

    async def test_missing_object_returns_404(self, client, settings, local_storage) -> None:
        user, _ws, clip = await _user_with_clip("video-str-nofile@example.com")
        video = await _insert_video(user, clip, store=False)
        resp = await client.get(_stream_url(str(video.id)), headers=_auth_headers(user, settings))
        assert resp.status_code == 404

    async def test_malformed_video_id_returns_404(self, client, settings, local_storage) -> None:
        user = await _make_user("video-str-bad@example.com")
        resp = await client.get(_stream_url("not-an-id"), headers=_auth_headers(user, settings))
        assert resp.status_code == 404

    async def test_unsatisfiable_range_returns_416(self, client, settings, local_storage) -> None:
        # A wholly-unsatisfiable Range must 416 with the resource length so a
        # seeking player can retry (mirrors the clip-audio endpoint).
        user, _ws, clip = await _user_with_clip("video-str-416@example.com")
        video = await _insert_video(user, clip)
        headers = {**_auth_headers(user, settings), "Range": "bytes=999999-"}
        resp = await client.get(_stream_url(str(video.id)), headers=headers)
        assert resp.status_code == 416
        assert resp.headers["content-range"] == f"bytes */{len(_MP4_BYTES)}"

    async def test_multi_range_returns_206_multipart(self, client, settings, local_storage) -> None:
        user, _ws, clip = await _user_with_clip("video-str-multi@example.com")
        video = await _insert_video(user, clip)
        headers = {**_auth_headers(user, settings), "Range": "bytes=0-3,8-11"}
        resp = await client.get(_stream_url(str(video.id)), headers=headers)
        assert resp.status_code == 206
        assert resp.headers["content-type"].startswith("multipart/byteranges")
        # Both requested slices appear in the multipart body.
        assert _MP4_BYTES[0:4] in resp.content
        assert _MP4_BYTES[8:12] in resp.content


@pytest.mark.integration
class TestForClip:
    async def test_owner_gets_published_video_for_clip(self, client, settings, local_storage) -> None:
        user, _ws, clip = await _user_with_clip("video-fc-own@example.com")
        video = await _insert_video(user, clip, published=True)
        resp = await client.get(_for_clip_url(str(clip.id)), headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        assert resp.json()["id"] == str(video.id)

    async def test_anonymous_gets_published_video_on_public_clip(self, client, settings, local_storage) -> None:
        owner, _ws, clip = await _user_with_clip("video-fc-pub@example.com")
        await _make_public(clip)
        video = await _insert_video(owner, clip, published=True)
        resp = await client.get(_for_clip_url(str(clip.id)))
        assert resp.status_code == 200
        assert resp.json()["id"] == str(video.id)

    async def test_unpublished_video_is_not_returned(self, client, settings, local_storage) -> None:
        user, _ws, clip = await _user_with_clip("video-fc-unpub@example.com")
        await _insert_video(user, clip, published=False)
        resp = await client.get(_for_clip_url(str(clip.id)), headers=_auth_headers(user, settings))
        assert resp.status_code == 404

    async def test_no_video_for_clip_returns_404(self, client, settings, local_storage) -> None:
        user, _ws, clip = await _user_with_clip("video-fc-none@example.com")
        resp = await client.get(_for_clip_url(str(clip.id)), headers=_auth_headers(user, settings))
        assert resp.status_code == 404

    async def test_private_clip_hidden_from_stranger(self, client, settings, local_storage) -> None:
        owner, _ws, clip = await _user_with_clip("video-fc-priv@example.com")
        stranger = await _make_user("video-fc-priv-other@example.com")
        await _insert_video(owner, clip, published=True)
        resp = await client.get(_for_clip_url(str(clip.id)), headers=_auth_headers(stranger, settings))
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# US-22.4 editing: POST /videos/{video_id}/edit + GET /videos/{video_id}/versions
# ---------------------------------------------------------------------------


class TestEditAuthGate:
    def test_edit_without_auth_returns_401(self) -> None:
        client = TestClient(create_app())
        resp = client.post(_edit_url(str(PydanticObjectId())), json={"operation": "trim"})
        assert resp.status_code == 401

    def test_versions_without_auth_returns_401(self) -> None:
        client = TestClient(create_app())
        resp = client.get(_versions_url(str(PydanticObjectId())))
        assert resp.status_code == 401


@pytest.mark.integration
class TestVideoEdit:
    async def test_trim_returns_202_and_persists_edit_job(self, client, settings, local_storage) -> None:
        user, ws, clip = await _user_with_clip("video-edit-trim@example.com", balance=100)
        source = await _insert_video(user, clip, resolution="1080p")
        body = {"operation": "trim", "start_seconds": 2.0, "end_seconds": 8.0}
        resp = await client.post(_edit_url(str(source.id)), json=body, headers=_auth_headers(user, settings))
        assert resp.status_code == 202
        job_id = resp.json()["job_id"]
        job = await Job.get(PydanticObjectId(job_id))
        assert job is not None
        assert job.job_type == VIDEO_JOB_TYPE
        assert job.status == JobStatus.QUEUED
        assert job.workspace_id == ws.id
        params = job.input_params
        assert params["source_video_id"] == str(source.id)
        assert params["clip_id"] == str(clip.id)
        assert params["edit"] == {"operation": "trim", "start_seconds": 2.0, "end_seconds": 8.0}
        # Source video is never mutated by enqueuing an edit.
        assert (await Video.get(source.id)).parent_video_id is None

    async def test_replace_scene_carries_prompt_only(self, client, settings, local_storage) -> None:
        user, _ws, clip = await _user_with_clip("video-edit-scene@example.com", balance=100)
        source = await _insert_video(user, clip)
        body = {"operation": "replace_scene", "start_seconds": 1.0, "end_seconds": 4.0, "prompt": "sunset over waves"}
        resp = await client.post(_edit_url(str(source.id)), json=body, headers=_auth_headers(user, settings))
        assert resp.status_code == 202
        job = await Job.get(PydanticObjectId(resp.json()["job_id"]))
        assert job.input_params["edit"] == {
            "operation": "replace_scene",
            "start_seconds": 1.0,
            "end_seconds": 4.0,
            "prompt": "sunset over waves",
        }

    async def test_lyrics_overlay_toggle(self, client, settings, local_storage) -> None:
        user, _ws, clip = await _user_with_clip("video-edit-lyrics@example.com", balance=100)
        source = await _insert_video(user, clip)
        resp = await client.post(
            _edit_url(str(source.id)),
            json={"operation": "lyrics_overlay", "lyrics_enabled": True},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 202
        job = await Job.get(PydanticObjectId(resp.json()["job_id"]))
        assert job.input_params["edit"] == {"operation": "lyrics_overlay", "lyrics_enabled": True}

    async def test_transitions_markers(self, client, settings, local_storage) -> None:
        user, _ws, clip = await _user_with_clip("video-edit-trans@example.com", balance=100)
        source = await _insert_video(user, clip)
        resp = await client.post(
            _edit_url(str(source.id)),
            json={"operation": "transitions", "transition_markers": [1.5, 3.0]},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 202
        job = await Job.get(PydanticObjectId(resp.json()["job_id"]))
        assert job.input_params["edit"] == {"operation": "transitions", "transition_markers": [1.5, 3.0]}

    async def test_charges_source_resolution_cost(self, client, settings, local_storage) -> None:
        user, _ws, clip = await _user_with_clip("video-edit-cost@example.com", balance=100, duration=10.0)
        source = await _insert_video(user, clip, resolution="1080p")
        resp = await client.post(
            _edit_url(str(source.id)),
            json={"operation": "trim", "start_seconds": 0.0, "end_seconds": 5.0},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 202
        # 1080p base cost is 7 credits (short song, no surcharge).
        assert (await _reload(user)).credits_balance == pytest.approx(93.0)
        txns = await CreditTransaction.find(CreditTransaction.user_id == user.id).to_list()
        assert any(t.amount == pytest.approx(-7.0) for t in txns)

    async def test_edit_range_past_song_returns_422_no_charge(self, client, settings, local_storage) -> None:
        user, _ws, clip = await _user_with_clip("video-edit-oob@example.com", balance=100, duration=10.0)
        source = await _insert_video(user, clip)
        resp = await client.post(
            _edit_url(str(source.id)),
            json={"operation": "trim", "start_seconds": 5.0, "end_seconds": 30.0},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 422
        assert (await _reload(user)).credits_balance == 100

    async def test_chained_edit_validated_against_edited_length_not_song(self, client, settings, local_storage) -> None:
        # An already-trimmed version is 8s even though the song is 30s: editing it
        # with a range past 8s must 422 (validated against the video, not the song).
        user, _ws, clip = await _user_with_clip("video-edit-chain@example.com", balance=100, duration=30.0)
        trimmed = await _insert_video(
            user, clip, edit={"operation": "trim", "start_seconds": 0.0, "end_seconds": 8.0}, duration=8.0
        )
        past = await client.post(
            _edit_url(str(trimmed.id)),
            json={"operation": "trim", "start_seconds": 5.0, "end_seconds": 20.0},
            headers=_auth_headers(user, settings),
        )
        assert past.status_code == 422
        assert (await _reload(user)).credits_balance == 100
        # A range inside the trimmed length is still accepted.
        within = await client.post(
            _edit_url(str(trimmed.id)),
            json={"operation": "trim", "start_seconds": 2.0, "end_seconds": 6.0},
            headers=_auth_headers(user, settings),
        )
        assert within.status_code == 202

    async def test_unknown_video_returns_404_no_charge(self, client, settings, local_storage) -> None:
        user = await _make_user("video-edit-unknown@example.com", balance=100)
        resp = await client.post(
            _edit_url(str(PydanticObjectId())),
            json={"operation": "trim", "start_seconds": 0.0, "end_seconds": 5.0},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 404
        assert (await _reload(user)).credits_balance == 100

    async def test_other_users_video_returns_404(self, client, settings, local_storage) -> None:
        owner, _ws, clip = await _user_with_clip("video-edit-owner@example.com")
        thief = await _make_user("video-edit-thief@example.com", balance=100)
        source = await _insert_video(owner, clip)
        resp = await client.post(
            _edit_url(str(source.id)),
            json={"operation": "trim", "start_seconds": 0.0, "end_seconds": 5.0},
            headers=_auth_headers(thief, settings),
        )
        assert resp.status_code == 404

    async def test_insufficient_credits_returns_402(self, client, settings, local_storage) -> None:
        user, _ws, clip = await _user_with_clip("video-edit-broke@example.com", balance=1.0)
        source = await _insert_video(user, clip, resolution="1080p")
        resp = await client.post(
            _edit_url(str(source.id)),
            json={"operation": "trim", "start_seconds": 0.0, "end_seconds": 5.0},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 402
        assert resp.json()["detail"]["error"] == "insufficient_credits"

    async def test_not_configured_returns_503_no_charge(self, mongo_db, mongo_settings, local_storage) -> None:
        cfg = mongo_settings.model_copy(
            update={
                "jwt_secret_key": "test-secret-key-at-least-32-bytes-long-xx",
                "job_processor_enabled": False,
                "video_api_url": None,
                "video_api_key": None,
            }
        )
        user, _ws, clip = await _user_with_clip("video-edit-503@example.com", balance=100)
        source = await _insert_video(user, clip)
        async with _async_client(create_app(cfg)) as ac:
            resp = await ac.post(
                _edit_url(str(source.id)),
                json={"operation": "trim", "start_seconds": 0.0, "end_seconds": 5.0},
                headers=_auth_headers(user, cfg),
            )
        assert resp.status_code == 503
        assert (await _reload(user)).credits_balance == 100

    @pytest.mark.parametrize(
        "body",
        [
            {"operation": "trim", "start_seconds": 1.0},  # missing end
            {"operation": "trim", "start_seconds": 5.0, "end_seconds": 2.0},  # end <= start
            {"operation": "replace_scene", "start_seconds": 1.0, "end_seconds": 4.0},  # no prompt
            {"operation": "lyrics_overlay"},  # no lyrics_enabled
            {"operation": "transitions"},  # no markers
            {"operation": "transitions", "transition_markers": [-1.0]},  # negative marker
            {"operation": "bogus"},  # unknown operation
            {"operation": "trim", "start_seconds": 0.0, "end_seconds": 5.0, "surprise": 1},  # extra field
        ],
    )
    async def test_invalid_bodies_return_422(self, client, settings, local_storage, body) -> None:
        user, _ws, clip = await _user_with_clip(
            f"video-edit-invalid-{hash(str(body)) & 0xffff}@example.com", balance=100
        )
        source = await _insert_video(user, clip)
        resp = await client.post(_edit_url(str(source.id)), json=body, headers=_auth_headers(user, settings))
        assert resp.status_code == 422


@pytest.mark.integration
class TestVideoVersions:
    async def test_lists_versions_newest_first_with_lineage(self, client, settings, local_storage) -> None:
        user, _ws, clip = await _user_with_clip("video-ver-list@example.com")
        original = await _insert_video(user, clip, resolution="1080p")
        edited = await _insert_video(
            user,
            clip,
            resolution="1080p",
            parent_video_id=original.id,
            edit={"operation": "trim", "start_seconds": 1.0, "end_seconds": 5.0},
        )
        resp = await client.get(_versions_url(str(original.id)), headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        items = resp.json()
        assert [i["id"] for i in items] == [str(edited.id), str(original.id)]
        # The edit carries its lineage; the original omits the null fields.
        assert items[0]["parent_video_id"] == str(original.id)
        assert items[0]["edit"]["operation"] == "trim"
        assert "parent_video_id" not in items[1]
        assert "edit" not in items[1]
        assert all("created_at" in i for i in items)

    async def test_from_edited_video_lists_the_same_lineage(self, client, settings, local_storage) -> None:
        # Asking for versions of any member returns the whole clip's history.
        user, _ws, clip = await _user_with_clip("video-ver-any@example.com")
        original = await _insert_video(user, clip)
        edited = await _insert_video(user, clip, parent_video_id=original.id, edit={"operation": "lyrics_overlay"})
        resp = await client.get(_versions_url(str(edited.id)), headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        assert {i["id"] for i in resp.json()} == {str(original.id), str(edited.id)}

    async def test_unknown_video_returns_404(self, client, settings, local_storage) -> None:
        user = await _make_user("video-ver-unknown@example.com")
        resp = await client.get(_versions_url(str(PydanticObjectId())), headers=_auth_headers(user, settings))
        assert resp.status_code == 404

    async def test_other_users_video_returns_404(self, client, settings, local_storage) -> None:
        owner, _ws, clip = await _user_with_clip("video-ver-owner@example.com")
        stranger = await _make_user("video-ver-stranger@example.com")
        source = await _insert_video(owner, clip)
        resp = await client.get(_versions_url(str(source.id)), headers=_auth_headers(stranger, settings))
        assert resp.status_code == 404
