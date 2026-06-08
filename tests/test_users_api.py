"""Integration tests for the user profile endpoints (US-8.4).

Drives the real app with ``httpx.AsyncClient`` over ``ASGITransport`` against a
local MongoDB (the ``mongo_db`` fixture), mirroring ``tests/test_auth_routes.py``.
``AsyncClient`` (not Starlette's ``TestClient``) is required so requests run on
the same event loop the Mongo client was initialised on.
"""

import httpx
import pytest

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.services import users as user_service
from acemusic.api.settings import ApiSettings

pytestmark = pytest.mark.integration


def _async_client(app) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


@pytest.fixture
def settings(mongo_db, mongo_settings) -> ApiSettings:
    # mongo_db initialises Beanie against the isolated DB on this test's loop.
    return mongo_settings.model_copy(update={"jwt_secret_key": "test-secret-key-at-least-32-bytes-long-xx"})


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


async def _make_user(email: str, name: str = "Test User"):
    return await user_service.get_or_create_user(email=email, provider="google", oauth_id=f"g-{email}", name=name)


class TestGetProfile:
    async def test_returns_full_profile(self, client, settings):
        user = await _make_user("get-me@example.com", name="Getter")
        resp = await client.get(f"{API_V1_PREFIX}/users/me", headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        body = resp.json()
        assert body["email"] == "get-me@example.com"
        assert body["display_name"] == "Getter"
        assert body["id"] == str(user.id)
        assert "handle" in body and "bio" in body and "style_tags" in body and "avatar_url" in body

    async def test_requires_authentication(self, client, settings):
        resp = await client.get(f"{API_V1_PREFIX}/users/me")
        assert resp.status_code == 401


class TestUpdateProfile:
    async def test_updates_fields_and_returns_updated_profile(self, client, settings):
        user = await _make_user("patch-me@example.com")
        resp = await client.patch(
            f"{API_V1_PREFIX}/users/me",
            json={"display_name": "Patched", "handle": "patched-one", "bio": "b", "style_tags": ["edm"]},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["display_name"] == "Patched"
        assert body["handle"] == "patched-one"
        assert body["bio"] == "b"
        assert body["style_tags"] == ["edm"]

    async def test_invalid_handle_returns_422(self, client, settings):
        user = await _make_user("bad-handle@example.com")
        resp = await client.patch(
            f"{API_V1_PREFIX}/users/me",
            json={"handle": "no spaces"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 422
        # Error mentions the format requirement, not a generic message.
        detail = resp.json()["detail"]
        assert any("letters" in str(d).lower() or "hyphen" in str(d).lower() for d in detail)

    async def test_too_short_handle_returns_422(self, client, settings):
        user = await _make_user("short-handle@example.com")
        resp = await client.patch(
            f"{API_V1_PREFIX}/users/me",
            json={"handle": "ab"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 422

    async def test_duplicate_handle_returns_409(self, client, settings):
        owner = await _make_user("owner@example.com")
        other = await _make_user("other@example.com")
        first = await client.patch(
            f"{API_V1_PREFIX}/users/me",
            json={"handle": "the-one"},
            headers=_auth_headers(owner, settings),
        )
        assert first.status_code == 200
        clash = await client.patch(
            f"{API_V1_PREFIX}/users/me",
            json={"handle": "the-one"},
            headers=_auth_headers(other, settings),
        )
        assert clash.status_code == 409

    async def test_empty_body_returns_current_profile(self, client, settings):
        user = await _make_user("noop@example.com", name="NoOp")
        resp = await client.patch(f"{API_V1_PREFIX}/users/me", json={}, headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        assert resp.json()["display_name"] == "NoOp"

    async def test_handle_can_be_cleared(self, client, settings):
        user = await _make_user("clear@example.com")
        await client.patch(
            f"{API_V1_PREFIX}/users/me",
            json={"handle": "to-clear"},
            headers=_auth_headers(user, settings),
        )
        resp = await client.patch(
            f"{API_V1_PREFIX}/users/me",
            json={"handle": None},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 200
        assert resp.json()["handle"] is None

    async def test_unknown_field_rejected(self, client, settings):
        user = await _make_user("strict@example.com")
        resp = await client.patch(
            f"{API_V1_PREFIX}/users/me",
            json={"subscription_tier": "pro"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 422

    async def test_requires_authentication(self, client, settings):
        resp = await client.patch(f"{API_V1_PREFIX}/users/me", json={"bio": "x"})
        assert resp.status_code == 401


class TestMissingUser:
    """Token valid, but the referenced user no longer exists (e.g. deleted)."""

    def _orphan_headers(self, settings: ApiSettings) -> dict[str, str]:
        from bson import ObjectId

        token = create_access_token(
            user_id=str(ObjectId()),
            email="ghost@example.com",
            subscription_tier="free",
            settings=settings,
        )
        return {"Authorization": f"Bearer {token}"}

    async def test_get_returns_404(self, client, settings):
        resp = await client.get(f"{API_V1_PREFIX}/users/me", headers=self._orphan_headers(settings))
        assert resp.status_code == 404

    async def test_patch_returns_404(self, client, settings):
        resp = await client.patch(
            f"{API_V1_PREFIX}/users/me",
            json={"bio": "x"},
            headers=self._orphan_headers(settings),
        )
        assert resp.status_code == 404
