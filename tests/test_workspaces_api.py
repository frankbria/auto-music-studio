"""Tests for the workspace CRUD endpoints (US-9.4, issue #78).

The 401 auth-gate tests run in CI (the router dependency rejects before any DB
access; plain ``TestClient`` does not run the lifespan). The CRUD tests are
``integration``: they drive the real app with ``httpx.AsyncClient`` over a local
MongoDB (``mongo_db``), mirroring ``tests/test_jobs_api.py``.
"""

import httpx
import pytest
from beanie import PydanticObjectId
from fastapi.testclient import TestClient

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.models import Clip, Workspace
from acemusic.api.services import users as user_service
from acemusic.api.settings import ApiSettings
from acemusic.storage import get_storage_backend

WORKSPACES_URL = f"{API_V1_PREFIX}/workspaces"


# ---------------------------------------------------------------------------
# Auth gate — runs in CI (no DB)
# ---------------------------------------------------------------------------


class TestAuthGate:
    @pytest.mark.parametrize(
        ("method", "url"),
        [
            ("GET", WORKSPACES_URL),
            ("POST", WORKSPACES_URL),
            ("GET", f"{WORKSPACES_URL}/{PydanticObjectId()}"),
            ("PATCH", f"{WORKSPACES_URL}/{PydanticObjectId()}"),
            ("DELETE", f"{WORKSPACES_URL}/{PydanticObjectId()}"),
        ],
    )
    def test_missing_auth_header_returns_401(self, method: str, url: str) -> None:
        client = TestClient(create_app())
        resp = client.request(method, url)
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


@pytest.fixture
def local_storage(monkeypatch, tmp_path):
    """Point the storage backend at a throwaway local root."""
    monkeypatch.setenv("ACEMUSIC_STORAGE_BACKEND", "local")
    monkeypatch.setenv("ACEMUSIC_STORAGE_LOCAL_ROOT", str(tmp_path))
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


async def _insert_workspace(user, name: str, *, is_default: bool = False) -> Workspace:
    workspace = Workspace(name=name, user_id=user.id, is_default=is_default)
    await workspace.insert()
    return workspace


async def _insert_clip(user, workspace: Workspace, *, store_bytes: bytes | None = None) -> Clip:
    clip_id = PydanticObjectId()
    file_path = f"{user.id}/{workspace.id}/clips/{clip_id}.wav"
    if store_bytes is not None:
        get_storage_backend().upload(file_path, store_bytes)
    clip = Clip(id=clip_id, user_id=user.id, workspace_id=workspace.id, file_path=file_path, format="wav")
    await clip.insert()
    return clip


@pytest.mark.integration
class TestCreateWorkspace:
    async def test_create_returns_201_with_workspace(self, client, settings) -> None:
        user = await _make_user("ws-create@example.com")
        resp = await client.post(WORKSPACES_URL, json={"name": "Beats"}, headers=_auth_headers(user, settings))
        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "Beats"
        assert body["clip_count"] == 0
        assert body["is_default"] is False
        assert body["id"]
        assert body["created_at"]

    async def test_duplicate_name_for_same_user_returns_409(self, client, settings) -> None:
        user = await _make_user("ws-dup@example.com")
        first = await client.post(WORKSPACES_URL, json={"name": "Beats"}, headers=_auth_headers(user, settings))
        assert first.status_code == 201
        second = await client.post(WORKSPACES_URL, json={"name": "Beats"}, headers=_auth_headers(user, settings))
        assert second.status_code == 409

    async def test_same_name_for_different_users_is_allowed(self, client, settings) -> None:
        alice = await _make_user("ws-alice@example.com")
        bob = await _make_user("ws-bob@example.com")
        assert (
            await client.post(WORKSPACES_URL, json={"name": "Beats"}, headers=_auth_headers(alice, settings))
        ).status_code == 201
        assert (
            await client.post(WORKSPACES_URL, json={"name": "Beats"}, headers=_auth_headers(bob, settings))
        ).status_code == 201

    @pytest.mark.parametrize("payload", [{}, {"name": ""}, {"name": "   "}])
    async def test_missing_or_blank_name_returns_422(self, client, settings, payload: dict) -> None:
        user = await _make_user("ws-blank@example.com")
        resp = await client.post(WORKSPACES_URL, json=payload, headers=_auth_headers(user, settings))
        assert resp.status_code == 422


@pytest.mark.integration
class TestListWorkspaces:
    async def test_lists_only_own_workspaces_with_clip_counts(self, client, settings) -> None:
        user = await _make_user("ws-list@example.com")
        other = await _make_user("ws-list-other@example.com")
        ws_a = await _insert_workspace(user, "A")
        ws_b = await _insert_workspace(user, "B")
        await _insert_workspace(other, "Theirs")
        await _insert_clip(user, ws_a)
        await _insert_clip(user, ws_a)

        resp = await client.get(WORKSPACES_URL, headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        by_id = {w["id"]: w for w in body["workspaces"]}
        assert set(by_id) == {str(ws_a.id), str(ws_b.id)}
        assert by_id[str(ws_a.id)]["clip_count"] == 2
        assert by_id[str(ws_b.id)]["clip_count"] == 0

    async def test_empty_list_for_new_user(self, client, settings) -> None:
        user = await _make_user("ws-list-empty@example.com")
        resp = await client.get(WORKSPACES_URL, headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        assert resp.json() == {"workspaces": [], "total": 0}


@pytest.mark.integration
class TestGetWorkspace:
    async def test_get_own_workspace_returns_200(self, client, settings) -> None:
        user = await _make_user("ws-get@example.com")
        workspace = await _insert_workspace(user, "Mine")
        await _insert_clip(user, workspace)

        resp = await client.get(f"{WORKSPACES_URL}/{workspace.id}", headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == str(workspace.id)
        assert body["name"] == "Mine"
        assert body["clip_count"] == 1

    async def test_unknown_workspace_returns_404(self, client, settings) -> None:
        user = await _make_user("ws-get-unknown@example.com")
        resp = await client.get(f"{WORKSPACES_URL}/{PydanticObjectId()}", headers=_auth_headers(user, settings))
        assert resp.status_code == 404

    async def test_malformed_id_returns_404(self, client, settings) -> None:
        user = await _make_user("ws-get-malformed@example.com")
        resp = await client.get(f"{WORKSPACES_URL}/not-an-object-id", headers=_auth_headers(user, settings))
        assert resp.status_code == 404

    async def test_other_users_workspace_returns_404(self, client, settings) -> None:
        owner = await _make_user("ws-get-owner@example.com")
        other = await _make_user("ws-get-other@example.com")
        workspace = await _insert_workspace(owner, "Private")
        resp = await client.get(f"{WORKSPACES_URL}/{workspace.id}", headers=_auth_headers(other, settings))
        assert resp.status_code == 404


@pytest.mark.integration
class TestUpdateWorkspace:
    async def test_rename_returns_updated_workspace(self, client, settings) -> None:
        user = await _make_user("ws-rename@example.com")
        workspace = await _insert_workspace(user, "Old Name")

        resp = await client.patch(
            f"{WORKSPACES_URL}/{workspace.id}",
            json={"name": "New Name"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "New Name"
        assert body["updated_at"] is not None

        fetched = await Workspace.get(workspace.id)
        assert fetched.name == "New Name"

    async def test_rename_to_existing_name_returns_409(self, client, settings) -> None:
        user = await _make_user("ws-rename-dup@example.com")
        await _insert_workspace(user, "Taken")
        workspace = await _insert_workspace(user, "Original")

        resp = await client.patch(
            f"{WORKSPACES_URL}/{workspace.id}",
            json={"name": "Taken"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 409

    async def test_unknown_workspace_returns_404(self, client, settings) -> None:
        user = await _make_user("ws-rename-unknown@example.com")
        resp = await client.patch(
            f"{WORKSPACES_URL}/{PydanticObjectId()}",
            json={"name": "X"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 404

    async def test_other_users_workspace_returns_404(self, client, settings) -> None:
        owner = await _make_user("ws-rename-owner@example.com")
        other = await _make_user("ws-rename-other@example.com")
        workspace = await _insert_workspace(owner, "Private")
        resp = await client.patch(
            f"{WORKSPACES_URL}/{workspace.id}",
            json={"name": "Hijacked"},
            headers=_auth_headers(other, settings),
        )
        assert resp.status_code == 404

    async def test_blank_name_returns_422(self, client, settings) -> None:
        user = await _make_user("ws-rename-blank@example.com")
        workspace = await _insert_workspace(user, "Fine")
        resp = await client.patch(
            f"{WORKSPACES_URL}/{workspace.id}",
            json={"name": "  "},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 422


@pytest.mark.integration
class TestDeleteWorkspace:
    async def test_delete_empty_workspace_returns_204(self, client, settings) -> None:
        user = await _make_user("ws-del@example.com")
        keep = await _insert_workspace(user, "Keep")
        doomed = await _insert_workspace(user, "Doomed")

        resp = await client.delete(f"{WORKSPACES_URL}/{doomed.id}", headers=_auth_headers(user, settings))
        assert resp.status_code == 204
        assert await Workspace.get(doomed.id) is None
        assert await Workspace.get(keep.id) is not None

    async def test_delete_non_empty_without_force_returns_409(self, client, settings, local_storage) -> None:
        user = await _make_user("ws-del-409@example.com")
        await _insert_workspace(user, "Keep")
        workspace = await _insert_workspace(user, "Full")
        await _insert_clip(user, workspace, store_bytes=b"abc")

        resp = await client.delete(f"{WORKSPACES_URL}/{workspace.id}", headers=_auth_headers(user, settings))
        assert resp.status_code == 409
        assert await Workspace.get(workspace.id) is not None

    async def test_delete_non_empty_with_force_cascades(self, client, settings, local_storage) -> None:
        user = await _make_user("ws-del-force@example.com")
        await _insert_workspace(user, "Keep")
        workspace = await _insert_workspace(user, "Full")
        clip = await _insert_clip(user, workspace, store_bytes=b"abc")
        stored_file = local_storage / clip.file_path
        assert stored_file.exists()

        resp = await client.delete(
            f"{WORKSPACES_URL}/{workspace.id}",
            params={"force": "true"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 204
        assert await Workspace.get(workspace.id) is None
        assert await Clip.get(clip.id) is None
        assert not stored_file.exists()

    async def test_delete_last_workspace_returns_400(self, client, settings) -> None:
        user = await _make_user("ws-del-last@example.com")
        only = await _insert_workspace(user, "Only One")

        resp = await client.delete(f"{WORKSPACES_URL}/{only.id}", headers=_auth_headers(user, settings))
        assert resp.status_code == 400
        assert await Workspace.get(only.id) is not None

    async def test_delete_last_workspace_with_force_still_returns_400(self, client, settings) -> None:
        user = await _make_user("ws-del-last-force@example.com")
        only = await _insert_workspace(user, "Only One")

        resp = await client.delete(
            f"{WORKSPACES_URL}/{only.id}",
            params={"force": "true"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 400
        assert await Workspace.get(only.id) is not None

    async def test_unknown_workspace_returns_404(self, client, settings) -> None:
        user = await _make_user("ws-del-unknown@example.com")
        resp = await client.delete(f"{WORKSPACES_URL}/{PydanticObjectId()}", headers=_auth_headers(user, settings))
        assert resp.status_code == 404

    async def test_other_users_workspace_returns_404(self, client, settings) -> None:
        owner = await _make_user("ws-del-owner@example.com")
        other = await _make_user("ws-del-other@example.com")
        workspace = await _insert_workspace(owner, "Private")
        resp = await client.delete(f"{WORKSPACES_URL}/{workspace.id}", headers=_auth_headers(other, settings))
        assert resp.status_code == 404
        assert await Workspace.get(workspace.id) is not None
