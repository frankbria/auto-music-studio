"""Tests for the studio export endpoints (US-19.6, issue #212).

Covers ``POST /studio/mixdown``, ``POST /studio/export/daw`` (enqueue arrangement
jobs) and ``GET /studio/export/daw/{job_id}`` (download the assembled ZIP). The
request-model validation, storage-key helper and the 401 auth-gate run in CI (no
DB); the enqueue/ownership/download flows are ``integration`` and drive the real
app with ``httpx.AsyncClient`` over a local MongoDB.
"""

from __future__ import annotations

import pytest
from beanie import PydanticObjectId
from fastapi.testclient import TestClient
from pydantic import ValidationError

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.models import Clip, Job, JobStatus, Workspace
from acemusic.api.services import users as user_service
from acemusic.api.services.studio import (
    MAX_PLACEMENTS_PER_TRACK,
    MAX_TRACKS,
    STUDIO_DAW_EXPORT_JOB_TYPE,
    STUDIO_MIXDOWN_JOB_TYPE,
    StudioDawExportRequest,
    StudioMixdownRequest,
    clip_ids_in,
    studio_export_storage_path,
)
from acemusic.api.settings import ApiSettings
from acemusic.storage import get_storage_backend

STUDIO_URL = f"{API_V1_PREFIX}/studio"


def _track(clip_id: str, **overrides) -> dict:
    track = {
        "name": "Melody",
        "track_type": "melody",
        "volume_db": 0.0,
        "pan": 0.0,
        "muted": False,
        "solo": False,
        "placements": [{"clip_id": clip_id, "start_sec": 0.0, "duration_sec": None}],
    }
    track.update(overrides)
    return track


# ---------------------------------------------------------------------------
# Request-model validation — CI (no DB)
# ---------------------------------------------------------------------------


class TestRequestModels:
    def test_mixdown_defaults(self) -> None:
        req = StudioMixdownRequest(workspace_id="w", project_name="Song", tracks=[_track("c")])
        assert req.format == "wav"
        assert req.bpm is None
        assert len(req.tracks) == 1

    def test_mixdown_rejects_unknown_format(self) -> None:
        with pytest.raises(ValidationError):
            StudioMixdownRequest(workspace_id="w", project_name="Song", format="ogg", tracks=[_track("c")])

    def test_mixdown_rejects_blank_project_name(self) -> None:
        with pytest.raises(ValidationError):
            StudioMixdownRequest(workspace_id="w", project_name="", tracks=[_track("c")])

    def test_empty_tracks_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StudioMixdownRequest(workspace_id="w", project_name="Song", tracks=[])

    def test_tracks_without_placements_rejected(self) -> None:
        with pytest.raises(ValidationError, match="no clip placements"):
            StudioDawExportRequest(
                workspace_id="w",
                project_name="Song",
                tracks=[_track("c", placements=[]), _track("c", placements=[])],
            )

    def test_track_count_capped(self) -> None:
        with pytest.raises(ValidationError):
            StudioMixdownRequest(
                workspace_id="w",
                project_name="Song",
                tracks=[_track("c") for _ in range(MAX_TRACKS + 1)],
            )

    def test_placement_count_capped(self) -> None:
        placements = [
            {"clip_id": "c", "start_sec": float(i), "duration_sec": None} for i in range(MAX_PLACEMENTS_PER_TRACK + 1)
        ]
        with pytest.raises(ValidationError):
            StudioMixdownRequest(
                workspace_id="w",
                project_name="Song",
                tracks=[_track("c", placements=placements)],
            )

    @pytest.mark.parametrize("bad", [-61.0, 7.0])
    def test_volume_db_bounds(self, bad: float) -> None:
        with pytest.raises(ValidationError):
            StudioMixdownRequest(
                workspace_id="w",
                project_name="Song",
                tracks=[_track("c", volume_db=bad)],
            )

    @pytest.mark.parametrize("bad", [-1.5, 1.5])
    def test_pan_bounds(self, bad: float) -> None:
        with pytest.raises(ValidationError):
            StudioMixdownRequest(workspace_id="w", project_name="Song", tracks=[_track("c", pan=bad)])

    def test_negative_start_sec_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StudioMixdownRequest(
                workspace_id="w",
                project_name="Song",
                tracks=[{"name": "n", "track_type": "melody", "placements": [{"clip_id": "c", "start_sec": -1.0}]}],
            )

    def test_start_sec_capped(self) -> None:
        with pytest.raises(ValidationError):
            StudioMixdownRequest(
                workspace_id="w",
                project_name="Song",
                tracks=[{"name": "n", "track_type": "melody", "placements": [{"clip_id": "c", "start_sec": 1e9}]}],
            )

    def test_empty_clip_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StudioMixdownRequest(
                workspace_id="w",
                project_name="Song",
                tracks=[{"name": "n", "track_type": "melody", "placements": [{"clip_id": "", "start_sec": 0.0}]}],
            )

    def test_daw_request_has_no_format_field(self) -> None:
        assert "format" not in StudioDawExportRequest.model_fields

    def test_clip_ids_distinct_and_ordered(self) -> None:
        req = StudioMixdownRequest(
            workspace_id="w",
            project_name="Song",
            tracks=[
                {
                    "name": "a",
                    "track_type": "melody",
                    "placements": [
                        {"clip_id": "c1", "start_sec": 0.0},
                        {"clip_id": "c2", "start_sec": 1.0},
                    ],
                },
                {"name": "b", "track_type": "bass", "placements": [{"clip_id": "c1", "start_sec": 2.0}]},
            ],
        )
        assert clip_ids_in(req.tracks) == ["c1", "c2"]


class TestStoragePath:
    def test_keyed_by_job(self) -> None:
        u, w, j = PydanticObjectId(), PydanticObjectId(), PydanticObjectId()
        assert studio_export_storage_path(u, w, j) == f"{u}/{w}/exports/studio_{j}.zip"


# ---------------------------------------------------------------------------
# Auth gate — CI (no DB; plain TestClient does not run the lifespan)
# ---------------------------------------------------------------------------


class TestAuthGate:
    def test_mixdown_requires_auth(self) -> None:
        client = TestClient(create_app())
        resp = client.post(f"{STUDIO_URL}/mixdown", json={"workspace_id": "w", "project_name": "S"})
        assert resp.status_code == 401

    def test_daw_export_requires_auth(self) -> None:
        client = TestClient(create_app())
        resp = client.post(f"{STUDIO_URL}/export/daw", json={"workspace_id": "w", "project_name": "S"})
        assert resp.status_code == 401

    def test_daw_download_requires_auth(self) -> None:
        client = TestClient(create_app())
        resp = client.get(f"{STUDIO_URL}/export/daw/{PydanticObjectId()}")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Integration — real MongoDB
# ---------------------------------------------------------------------------


def _async_client(app):
    import httpx

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


@pytest.fixture
def local_storage(monkeypatch, tmp_path):
    monkeypatch.setenv("ACEMUSIC_STORAGE_BACKEND", "local")
    monkeypatch.setenv("ACEMUSIC_STORAGE_LOCAL_ROOT", str(tmp_path / "storage"))
    return tmp_path


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


async def _insert_clip(user, workspace, *, title="Song", fmt="wav") -> Clip:
    clip_id = PydanticObjectId()
    clip = Clip(
        id=clip_id,
        user_id=user.id,
        workspace_id=workspace.id,
        file_path=f"{user.id}/{workspace.id}/clips/{clip_id}.{fmt}",
        title=title,
        format=fmt,
        duration=2.0,
        bpm=120,
        key="C",
    )
    await clip.insert()
    return clip


def _body(workspace, clip, *, with_format=True) -> dict:
    body = {
        "workspace_id": str(workspace.id),
        "project_name": "My Mix",
        "bpm": 128.0,
        "markers": [{"name": "Verse", "time_sec": 4.0}],
        "tracks": [_track(str(clip.id))],
    }
    if with_format:
        body["format"] = "wav"
    return body


@pytest.mark.integration
class TestMixdownEnqueue:
    async def test_returns_202_and_persists_job(self, client, settings) -> None:
        user = await _make_user("studio-mix@example.com")
        workspace = await _make_workspace(user)
        clip = await _insert_clip(user, workspace)
        resp = await client.post(
            f"{STUDIO_URL}/mixdown", json=_body(workspace, clip), headers=_auth_headers(user, settings)
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "queued"

        jobs = await Job.find_all().to_list()
        assert len(jobs) == 1
        job = jobs[0]
        assert str(job.id) == body["job_id"]
        assert job.job_type == STUDIO_MIXDOWN_JOB_TYPE
        assert job.status == JobStatus.QUEUED
        assert job.workspace_id == workspace.id
        assert job.input_params["project_name"] == "My Mix"
        assert job.input_params["format"] == "wav"

    async def test_unknown_clip_returns_404_and_no_job(self, client, settings) -> None:
        user = await _make_user("studio-mix-404@example.com")
        workspace = await _make_workspace(user)
        body = {
            "workspace_id": str(workspace.id),
            "project_name": "X",
            "tracks": [_track(str(PydanticObjectId()))],
        }
        resp = await client.post(f"{STUDIO_URL}/mixdown", json=body, headers=_auth_headers(user, settings))
        assert resp.status_code == 404
        assert await Job.count() == 0

    async def test_unowned_workspace_returns_404(self, client, settings) -> None:
        owner = await _make_user("studio-ws-owner@example.com")
        workspace = await _make_workspace(owner)
        clip = await _insert_clip(owner, workspace)
        other = await _make_user("studio-ws-other@example.com")
        resp = await client.post(
            f"{STUDIO_URL}/mixdown", json=_body(workspace, clip), headers=_auth_headers(other, settings)
        )
        assert resp.status_code == 404
        assert await Job.count() == 0

    async def test_other_users_clip_returns_404(self, client, settings) -> None:
        owner = await _make_user("studio-clip-owner@example.com")
        ws_owner = await _make_workspace(owner)
        clip = await _insert_clip(owner, ws_owner)
        other = await _make_user("studio-clip-other@example.com")
        ws_other = await _make_workspace(other)
        body = {
            "workspace_id": str(ws_other.id),
            "project_name": "X",
            "tracks": [_track(str(clip.id))],
        }
        resp = await client.post(f"{STUDIO_URL}/mixdown", json=body, headers=_auth_headers(other, settings))
        assert resp.status_code == 404
        assert await Job.count() == 0


@pytest.mark.integration
class TestDawExportEnqueue:
    async def test_returns_202_and_persists_daw_job(self, client, settings) -> None:
        user = await _make_user("studio-daw@example.com")
        workspace = await _make_workspace(user)
        clip = await _insert_clip(user, workspace)
        resp = await client.post(
            f"{STUDIO_URL}/export/daw",
            json=_body(workspace, clip, with_format=False),
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 202
        job = (await Job.find_all().to_list())[0]
        assert job.job_type == STUDIO_DAW_EXPORT_JOB_TYPE
        assert "format" not in job.input_params


@pytest.mark.integration
class TestDawDownload:
    async def test_unknown_job_returns_404(self, client, settings, local_storage) -> None:
        user = await _make_user("studio-dl-404@example.com")
        resp = await client.get(f"{STUDIO_URL}/export/daw/{PydanticObjectId()}", headers=_auth_headers(user, settings))
        assert resp.status_code == 404

    async def test_queued_job_returns_409(self, client, settings, local_storage) -> None:
        user = await _make_user("studio-dl-409@example.com")
        workspace = await _make_workspace(user)
        job = Job(
            user_id=user.id,
            workspace_id=workspace.id,
            job_type=STUDIO_DAW_EXPORT_JOB_TYPE,
            status=JobStatus.QUEUED,
            input_params={"project_name": "P"},
        )
        await job.insert()
        resp = await client.get(f"{STUDIO_URL}/export/daw/{job.id}", headers=_auth_headers(user, settings))
        assert resp.status_code == 409

    async def test_completed_job_returns_zip(self, client, settings, local_storage) -> None:
        user = await _make_user("studio-dl-ok@example.com")
        workspace = await _make_workspace(user)
        job = Job(
            user_id=user.id,
            workspace_id=workspace.id,
            job_type=STUDIO_DAW_EXPORT_JOB_TYPE,
            status=JobStatus.COMPLETED,
            input_params={"project_name": "Cool Track"},
        )
        await job.insert()
        export_key = studio_export_storage_path(user.id, workspace.id, job.id)
        get_storage_backend().upload(export_key, b"PK\x03\x04 zip-bytes")

        resp = await client.get(f"{STUDIO_URL}/export/daw/{job.id}", headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/zip"
        assert resp.headers["content-disposition"] == 'attachment; filename="cool-track_Export.zip"'
        assert resp.content == b"PK\x03\x04 zip-bytes"

    async def test_completed_but_missing_object_returns_404(self, client, settings, local_storage) -> None:
        user = await _make_user("studio-dl-missing@example.com")
        workspace = await _make_workspace(user)
        job = Job(
            user_id=user.id,
            workspace_id=workspace.id,
            job_type=STUDIO_DAW_EXPORT_JOB_TYPE,
            status=JobStatus.COMPLETED,
            input_params={"project_name": "P"},
        )
        await job.insert()
        resp = await client.get(f"{STUDIO_URL}/export/daw/{job.id}", headers=_auth_headers(user, settings))
        assert resp.status_code == 404

    async def test_other_users_job_returns_404(self, client, settings, local_storage) -> None:
        owner = await _make_user("studio-dl-owner@example.com")
        workspace = await _make_workspace(owner)
        job = Job(
            user_id=owner.id,
            workspace_id=workspace.id,
            job_type=STUDIO_DAW_EXPORT_JOB_TYPE,
            status=JobStatus.COMPLETED,
            input_params={"project_name": "P"},
        )
        await job.insert()
        get_storage_backend().upload(studio_export_storage_path(owner.id, workspace.id, job.id), b"PK")
        other = await _make_user("studio-dl-intruder@example.com")
        resp = await client.get(f"{STUDIO_URL}/export/daw/{job.id}", headers=_auth_headers(other, settings))
        assert resp.status_code == 404
