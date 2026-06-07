"""Integration tests for the auth router (US-8.3, Step 7).

Run against a real local MongoDB via the ``mongo_db`` fixture (which binds the
Beanie models for the process). The app is built with ``create_app`` and driven
with an ``httpx.AsyncClient`` over an ``ASGITransport`` so requests execute on
the *same* asyncio event loop the ``mongo_db`` fixture initialized the Mongo
client on (Starlette's ``TestClient`` runs handlers on its own worker loop, which
pymongo's async client refuses to share). The app's lifespan is not run, so the
router reuses the already-initialized test database rather than re-connecting.

The ONLY thing mocked is the external OAuth provider HTTP performed inside
``acemusic.api.auth.oauth.exchange_code_for_user`` — never our own services.
"""

from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from fastapi import APIRouter, Depends

from acemusic.api.auth import oauth as oauth_module
from acemusic.api.auth.dependencies import CurrentUser, get_current_user
from acemusic.api.auth.oauth import OAuthError, OAuthUserInfo, get_authorization_url
from acemusic.api.auth.tokens import create_access_token, decode_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.models import User
from acemusic.api.settings import ApiSettings

pytestmark = pytest.mark.integration


def _auth_settings(mongo_settings: ApiSettings) -> ApiSettings:
    """Clone the isolated-DB settings, adding JWT + provider credentials."""
    return mongo_settings.model_copy(
        update={
            "jwt_secret_key": "test-secret-key-at-least-32-bytes-long-xx",
            "google_client_id": "google-id",
            "google_client_secret": "google-secret",
            "google_redirect_uri": "https://app.example.com/api/v1/auth/callback/google",
            "discord_client_id": "discord-id",
            "discord_client_secret": "discord-secret",
            "discord_redirect_uri": "https://app.example.com/api/v1/auth/callback/discord",
        }
    )


@pytest.fixture
def settings(mongo_db, mongo_settings) -> ApiSettings:
    # mongo_db initializes Beanie against the isolated DB on this test's loop.
    return _auth_settings(mongo_settings)


def _async_client(app) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


@pytest.fixture
async def client(settings):
    async with _async_client(create_app(settings)) as ac:
        yield ac


def _valid_state(provider: str, settings: ApiSettings) -> str:
    url = get_authorization_url(provider, settings)
    return parse_qs(urlparse(url).query)["state"][0]


def _fake_exchange(monkeypatch, info: OAuthUserInfo) -> None:
    async def _stub(provider, code, settings):
        return info

    monkeypatch.setattr(oauth_module, "exchange_code_for_user", _stub)


class TestLogin:
    async def test_login_google_returns_authorization_url(self, client):
        resp = await client.post(f"{API_V1_PREFIX}/auth/login/google")
        assert resp.status_code == 200
        url = resp.json()["authorization_url"]
        assert url.startswith(oauth_module.GOOGLE_AUTHORIZE_URL)
        assert "state=" in url

    async def test_login_discord_returns_authorization_url(self, client):
        resp = await client.post(f"{API_V1_PREFIX}/auth/login/discord")
        assert resp.status_code == 200
        assert resp.json()["authorization_url"].startswith(oauth_module.DISCORD_AUTHORIZE_URL)

    async def test_login_unknown_provider_400(self, client):
        resp = await client.post(f"{API_V1_PREFIX}/auth/login/github")
        assert resp.status_code == 400


class TestCallback:
    async def test_google_callback_creates_user_and_returns_jwt(self, client, settings, monkeypatch):
        _fake_exchange(
            monkeypatch,
            OAuthUserInfo(provider="google", oauth_id="g-1", email="alice@example.com", name="Alice"),
        )
        state = _valid_state("google", settings)
        resp = await client.post(
            f"{API_V1_PREFIX}/auth/callback/google",
            json={"code": "auth-code", "state": state},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["token_type"] == "bearer"
        assert body["expires_in"] == settings.access_token_expire_minutes * 60
        claims = decode_access_token(body["access_token"], settings)
        assert claims["email"] == "alice@example.com"
        assert claims["tier"] == "free"
        user = await User.find_one(User.oauth_provider == "google", User.oauth_id == "g-1")
        assert user is not None
        assert claims["sub"] == str(user.id)
        assert body["refresh_token"]

    async def test_discord_callback_creates_user_and_returns_jwt(self, client, settings, monkeypatch):
        _fake_exchange(
            monkeypatch,
            OAuthUserInfo(provider="discord", oauth_id="d-1", email="bob@example.com", name="Bob"),
        )
        state = _valid_state("discord", settings)
        resp = await client.post(
            f"{API_V1_PREFIX}/auth/callback/discord",
            json={"code": "auth-code", "state": state},
        )
        assert resp.status_code == 200
        claims = decode_access_token(resp.json()["access_token"], settings)
        assert claims["email"] == "bob@example.com"
        user = await User.find_one(User.oauth_provider == "discord", User.oauth_id == "d-1")
        assert user is not None

    async def test_existing_user_is_updated_not_duplicated(self, client, settings, monkeypatch):
        _fake_exchange(
            monkeypatch,
            OAuthUserInfo(provider="google", oauth_id="g-9", email="old@example.com", name="Old"),
        )
        await client.post(
            f"{API_V1_PREFIX}/auth/callback/google",
            json={"code": "c1", "state": _valid_state("google", settings)},
        )
        _fake_exchange(
            monkeypatch,
            OAuthUserInfo(provider="google", oauth_id="g-9", email="new@example.com", name="New"),
        )
        await client.post(
            f"{API_V1_PREFIX}/auth/callback/google",
            json={"code": "c2", "state": _valid_state("google", settings)},
        )
        users = await User.find(User.oauth_provider == "google", User.oauth_id == "g-9").to_list()
        assert len(users) == 1
        assert users[0].email == "new@example.com"
        assert users[0].name == "New"
        assert users[0].updated_at is not None

    async def test_bad_state_returns_400(self, client, settings, monkeypatch):
        _fake_exchange(
            monkeypatch,
            OAuthUserInfo(provider="google", oauth_id="g-2", email="x@example.com", name="X"),
        )
        resp = await client.post(
            f"{API_V1_PREFIX}/auth/callback/google",
            json={"code": "auth-code", "state": "tampered-state"},
        )
        assert resp.status_code == 400

    async def test_expired_state_returns_400(self, client, settings, monkeypatch):
        _fake_exchange(
            monkeypatch,
            OAuthUserInfo(provider="google", oauth_id="g-3", email="y@example.com", name="Y"),
        )
        now = datetime.now(timezone.utc)
        expired = jwt.encode(
            {
                "type": oauth_module.STATE_TOKEN_TYPE,
                "provider": "google",
                "iat": now - timedelta(hours=1),
                "exp": now - timedelta(minutes=1),
            },
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )
        resp = await client.post(
            f"{API_V1_PREFIX}/auth/callback/google",
            json={"code": "auth-code", "state": expired},
        )
        assert resp.status_code == 400

    async def test_provider_exchange_error_returns_502(self, client, settings, monkeypatch):
        async def _boom(provider, code, settings):
            raise OAuthError("provider rejected the code")

        monkeypatch.setattr(oauth_module, "exchange_code_for_user", _boom)
        resp = await client.post(
            f"{API_V1_PREFIX}/auth/callback/google",
            json={"code": "bad", "state": _valid_state("google", settings)},
        )
        assert resp.status_code == 502


async def _login(client, settings, monkeypatch, *, oauth_id="r-1", email="r@example.com") -> dict:
    _fake_exchange(
        monkeypatch,
        OAuthUserInfo(provider="google", oauth_id=oauth_id, email=email, name="R"),
    )
    resp = await client.post(
        f"{API_V1_PREFIX}/auth/callback/google",
        json={"code": "code", "state": _valid_state("google", settings)},
    )
    assert resp.status_code == 200
    return resp.json()


class TestRefresh:
    async def test_refresh_rotates_and_old_token_revoked(self, client, settings, monkeypatch):
        tokens = await _login(client, settings, monkeypatch)
        old_refresh = tokens["refresh_token"]

        resp = await client.post(f"{API_V1_PREFIX}/auth/refresh", json={"refresh_token": old_refresh})
        assert resp.status_code == 200
        new = resp.json()
        assert new["access_token"]
        assert new["refresh_token"] != old_refresh
        claims = decode_access_token(new["access_token"], settings)
        assert claims["email"] == "r@example.com"
        reuse = await client.post(f"{API_V1_PREFIX}/auth/refresh", json={"refresh_token": old_refresh})
        assert reuse.status_code == 401

    async def test_refresh_invalid_token_401(self, client):
        resp = await client.post(f"{API_V1_PREFIX}/auth/refresh", json={"refresh_token": "never-issued"})
        assert resp.status_code == 401

    async def test_refresh_revoked_token_401(self, client, settings, monkeypatch):
        tokens = await _login(client, settings, monkeypatch)
        from acemusic.api.auth.services import revoke_refresh_token

        await revoke_refresh_token(tokens["refresh_token"])
        resp = await client.post(f"{API_V1_PREFIX}/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        assert resp.status_code == 401


class TestLogout:
    async def test_logout_revokes_and_is_idempotent(self, client, settings, monkeypatch):
        tokens = await _login(client, settings, monkeypatch)
        refresh = tokens["refresh_token"]

        resp = await client.post(f"{API_V1_PREFIX}/auth/logout", json={"refresh_token": refresh})
        assert resp.status_code == 204
        reuse = await client.post(f"{API_V1_PREFIX}/auth/refresh", json={"refresh_token": refresh})
        assert reuse.status_code == 401
        # Idempotent: logging out an unknown/already-revoked token is still 204.
        again = await client.post(f"{API_V1_PREFIX}/auth/logout", json={"refresh_token": refresh})
        assert again.status_code == 204
        unknown = await client.post(f"{API_V1_PREFIX}/auth/logout", json={"refresh_token": "unknown"})
        assert unknown.status_code == 204


class TestRouteProtectionPattern:
    """Proves a router guarded by Depends(get_current_user) enforces auth.

    No workspaces/clips routers exist yet, so we mount a representative protected
    route under the v1 prefix on the real app to demonstrate the pattern.
    """

    @pytest.fixture
    async def protected_client(self, settings):
        app = create_app(settings)
        router = APIRouter(prefix="/secret")

        @router.get("")
        def secret(user: CurrentUser = Depends(get_current_user)) -> dict:
            return {"user_id": user.user_id}

        app.include_router(router, prefix=API_V1_PREFIX)
        async with _async_client(app) as ac:
            yield ac

    async def test_no_token_401(self, protected_client):
        resp = await protected_client.get(f"{API_V1_PREFIX}/secret")
        assert resp.status_code == 401

    async def test_expired_token_401(self, protected_client, settings):
        now = datetime.now(timezone.utc)
        expired = jwt.encode(
            {"sub": "u", "email": "e@x.com", "tier": "free", "type": "access", "exp": now - timedelta(hours=1)},
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )
        resp = await protected_client.get(f"{API_V1_PREFIX}/secret", headers={"Authorization": f"Bearer {expired}"})
        assert resp.status_code == 401

    async def test_valid_token_200(self, protected_client, settings):
        token = create_access_token(
            user_id="507f1f77bcf86cd799439011",
            email="ok@example.com",
            subscription_tier="free",
            settings=settings,
        )
        resp = await protected_client.get(f"{API_V1_PREFIX}/secret", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["user_id"] == "507f1f77bcf86cd799439011"

    async def test_health_stays_unprotected(self, protected_client):
        resp = await protected_client.get(f"{API_V1_PREFIX}/health")
        assert resp.status_code == 200
