"""Tests for the cover-art endpoints (US-13.1, issue #132).

Covers ``POST /clips/{id}/artwork/generate`` (202 + job), ``POST /clips/{id}/artwork``
(select), ``PUT /clips/{id}/artwork/upload`` (validated upload), ``GET
/clips/{id}/artwork`` (stream), and the artwork enrichment of the job-status
endpoint. The 401 auth-gate tests run in CI; the rest are ``integration`` and
drive the real app over a local MongoDB + LocalStorage.
"""

import io

import httpx
import pytest
from beanie import PydanticObjectId
from fastapi.testclient import TestClient
from PIL import Image

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.models import ArtworkOption, Clip, Job, JobStatus, Workspace
from acemusic.api.services import users as user_service
from acemusic.api.services.artwork import ARTWORK_JOB_TYPE
from acemusic.api.settings import ApiSettings
from acemusic.storage import get_storage_backend

CLIPS_URL = f"{API_V1_PREFIX}/clips"
JOBS_URL = f"{API_V1_PREFIX}/jobs"


def _png(size=(3000, 3000), fmt: str = "PNG") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, "indigo").save(buf, format=fmt)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Auth gate — CI (no DB; plain TestClient does not run the lifespan)
# ---------------------------------------------------------------------------


class TestAuthGate:
    def test_generate_requires_auth(self) -> None:
        client = TestClient(create_app())
        resp = client.post(f"{CLIPS_URL}/{PydanticObjectId()}/artwork/generate", json={})
        assert resp.status_code == 401

    def test_select_requires_auth(self) -> None:
        client = TestClient(create_app())
        resp = client.post(f"{CLIPS_URL}/{PydanticObjectId()}/artwork", json={"artwork_id": "x"})
        assert resp.status_code == 401

    def test_get_requires_auth(self) -> None:
        client = TestClient(create_app())
        resp = client.get(f"{CLIPS_URL}/{PydanticObjectId()}/artwork")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Integration — real MongoDB + LocalStorage
# ---------------------------------------------------------------------------


def _async_client(app) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


@pytest.fixture
def settings(mongo_db, mongo_settings) -> ApiSettings:
    return mongo_settings.model_copy(
        update={"jwt_secret_key": "test-secret-key-at-least-32-bytes-long-xx", "job_processor_enabled": False}
    )


@pytest.fixture
async def client(settings):
    async with _async_client(create_app(settings)) as ac:
        yield ac


@pytest.fixture
def local_storage(monkeypatch, tmp_path):
    monkeypatch.setenv("ACEMUSIC_STORAGE_BACKEND", "local")
    monkeypatch.setenv("ACEMUSIC_STORAGE_LOCAL_ROOT", str(tmp_path))
    return tmp_path


def _auth_headers(user, settings: ApiSettings) -> dict[str, str]:
    token = create_access_token(
        user_id=str(user.id), email=user.email, subscription_tier=user.subscription_tier, settings=settings
    )
    return {"Authorization": f"Bearer {token}"}


async def _make_user(email: str = "art@example.com"):
    return await user_service.get_or_create_user(email=email, provider="google", oauth_id=f"g-{email}", name="T")


async def _make_clip(user) -> Clip:
    workspace = Workspace(name="WS", user_id=user.id)
    await workspace.insert()
    clip = Clip(
        user_id=user.id,
        workspace_id=workspace.id,
        file_path=f"{user.id}/{workspace.id}/clips/c.wav",
        title="Song",
        style_tags=["lofi"],
    )
    await clip.insert()
    return clip


@pytest.mark.integration
class TestGenerate:
    async def test_returns_202_with_job_id(self, client, settings, local_storage) -> None:
        user = await _make_user()
        clip = await _make_clip(user)
        resp = await client.post(
            f"{CLIPS_URL}/{clip.id}/artwork/generate", json={}, headers=_auth_headers(user, settings)
        )
        assert resp.status_code == 202
        job_id = resp.json()["job_id"]
        job = await Job.get(PydanticObjectId(job_id))
        assert job.job_type == ARTWORK_JOB_TYPE

    async def test_other_users_clip_returns_404(self, client, settings, local_storage) -> None:
        owner = await _make_user("owner@example.com")
        clip = await _make_clip(owner)
        intruder = await _make_user("intruder@example.com")
        resp = await client.post(
            f"{CLIPS_URL}/{clip.id}/artwork/generate", json={}, headers=_auth_headers(intruder, settings)
        )
        assert resp.status_code == 404


@pytest.mark.integration
class TestSelect:
    async def test_select_sets_artwork_and_get_streams_it(self, client, settings, local_storage) -> None:
        user = await _make_user()
        clip = await _make_clip(user)
        path = f"{user.id}/{clip.workspace_id}/artwork/{clip.id}/0.png"
        get_storage_backend().upload(path, _png())
        option = ArtworkOption(
            clip_id=clip.id, user_id=user.id, job_id=PydanticObjectId(), storage_path=path, option_index=0
        )
        await option.insert()

        resp = await client.post(
            f"{CLIPS_URL}/{clip.id}/artwork", json={"artwork_id": str(option.id)}, headers=_auth_headers(user, settings)
        )
        assert resp.status_code == 200
        assert resp.json()["clip_id"] == str(clip.id)

        got = await client.get(f"{CLIPS_URL}/{clip.id}/artwork", headers=_auth_headers(user, settings))
        assert got.status_code == 200
        assert got.headers["content-type"] == "image/png"

    async def test_unknown_option_returns_404(self, client, settings, local_storage) -> None:
        user = await _make_user()
        clip = await _make_clip(user)
        resp = await client.post(
            f"{CLIPS_URL}/{clip.id}/artwork",
            json={"artwork_id": str(PydanticObjectId())},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 404


@pytest.mark.integration
class TestUpload:
    async def test_valid_upload_succeeds(self, client, settings, local_storage) -> None:
        user = await _make_user()
        clip = await _make_clip(user)
        resp = await client.put(
            f"{CLIPS_URL}/{clip.id}/artwork/upload",
            files={"file": ("art.png", _png(), "image/png")},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 200
        got = await client.get(f"{CLIPS_URL}/{clip.id}/artwork", headers=_auth_headers(user, settings))
        assert got.status_code == 200

    async def test_below_min_resolution_rejected_with_message(self, client, settings, local_storage) -> None:
        user = await _make_user()
        clip = await _make_clip(user)
        resp = await client.put(
            f"{CLIPS_URL}/{clip.id}/artwork/upload",
            files={"file": ("small.png", _png(size=(1024, 1024)), "image/png")},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 422
        assert "3000" in resp.json()["detail"]

    async def test_corrupt_file_rejected(self, client, settings, local_storage) -> None:
        user = await _make_user()
        clip = await _make_clip(user)
        resp = await client.put(
            f"{CLIPS_URL}/{clip.id}/artwork/upload",
            files={"file": ("bad.png", b"not really an image", "image/png")},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 422

    async def test_unsupported_format_rejected(self, client, settings, local_storage) -> None:
        user = await _make_user()
        clip = await _make_clip(user)
        resp = await client.put(
            f"{CLIPS_URL}/{clip.id}/artwork/upload",
            files={"file": ("art.gif", _png(size=(3000, 3000), fmt="GIF"), "image/gif")},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 422


@pytest.mark.integration
class TestGetArtworkMissing:
    async def test_no_artwork_returns_404(self, client, settings, local_storage) -> None:
        user = await _make_user()
        clip = await _make_clip(user)
        resp = await client.get(f"{CLIPS_URL}/{clip.id}/artwork", headers=_auth_headers(user, settings))
        assert resp.status_code == 404


@pytest.mark.integration
class TestJobStatusEnrichment:
    async def test_completed_artwork_job_lists_options(self, client, settings, local_storage) -> None:
        user = await _make_user()
        clip = await _make_clip(user)
        ids = []
        for idx in range(2):
            path = f"{user.id}/{clip.workspace_id}/artwork/{clip.id}/{idx}.png"
            get_storage_backend().upload(path, _png())
            option = ArtworkOption(
                clip_id=clip.id, user_id=user.id, job_id=PydanticObjectId(), storage_path=path, option_index=idx
            )
            await option.insert()
            ids.append(str(option.id))
        job = Job(
            user_id=user.id,
            workspace_id=clip.workspace_id,
            job_type=ARTWORK_JOB_TYPE,
            status=JobStatus.COMPLETED,
            input_params={"clip_id": str(clip.id)},
            result={"artwork_option_ids": ids},
        )
        await job.insert()

        resp = await client.get(f"{JOBS_URL}/{job.id}/status", headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        options = resp.json()["artwork_options"]
        assert {o["artwork_id"] for o in options} == set(ids)
        assert all(o["url"] for o in options)
