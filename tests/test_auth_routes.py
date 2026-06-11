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
from acemusic.api.auth.oauth import (
    STATE_COOKIE_PREFIX,
    OAuthError,
    OAuthUserInfo,
    build_authorization_request,
)
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
            # The test client speaks plain HTTP, so a Secure cookie would never be
            # sent back; disable Secure here (production default stays True).
            "oauth_cookie_secure": False,
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


def _bind_state(client: httpx.AsyncClient, provider: str, settings: ApiSettings) -> str:
    """Mint a client-bound state and place its nonce in the client's cookie jar.

    Mirrors what ``POST /login/{provider}`` does (issue #110): the callback only
    succeeds when the request carries the cookie nonce matching the state. The
    real login-sets-the-cookie path is covered separately by
    ``TestLogin::test_login_sets_state_cookie`` and ``TestCallback::
    test_end_to_end_login_then_callback``.
    """
    req = build_authorization_request(provider, settings)
    client.cookies.set(req.cookie_name, req.state_nonce)
    return parse_qs(urlparse(req.url).query)["state"][0]


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

    async def test_login_sets_client_binding_state_cookie(self, client):
        """Login must set the HttpOnly+SameSite state cookie that binds the flow
        to this client (issue #110)."""
        resp = await client.post(f"{API_V1_PREFIX}/auth/login/google")
        assert resp.status_code == 200
        set_cookie = resp.headers.get("set-cookie")
        assert set_cookie is not None
        assert STATE_COOKIE_PREFIX in set_cookie
        assert "httponly" in set_cookie.lower()
        assert "samesite=lax" in set_cookie.lower()
        # Secure is disabled only because the test client speaks HTTP; the
        # production default (oauth_cookie_secure=True) would add it.
        assert "secure" not in set_cookie.lower()
        assert any(name.startswith(STATE_COOKIE_PREFIX) for name in client.cookies.keys())

    async def test_login_cookie_honors_samesite_none_for_split_origin(self, settings):
        """A split-origin deployment can emit SameSite=None; Secure so the cookie
        is sent on the cross-site callback (issue #110 contract)."""
        split = settings.model_copy(update={"oauth_cookie_samesite": "none", "oauth_cookie_secure": True})
        async with _async_client(create_app(split)) as ac:
            resp = await ac.post(f"{API_V1_PREFIX}/auth/login/google")
        assert resp.status_code == 200
        set_cookie = (resp.headers.get("set-cookie") or "").lower()
        assert "samesite=none" in set_cookie
        assert "secure" in set_cookie


class TestCallback:
    async def test_end_to_end_login_then_callback(self, client, settings, monkeypatch):
        """The cookie set by the real /login flows to /callback and validates."""
        _fake_exchange(
            monkeypatch,
            OAuthUserInfo(provider="google", oauth_id="e2e-1", email="e2e@example.com", name="E", email_verified=True),
        )
        login = await client.post(f"{API_V1_PREFIX}/auth/login/google")
        assert login.status_code == 200
        state = parse_qs(urlparse(login.json()["authorization_url"]).query)["state"][0]
        # The state cookie is now in the client jar from login; reuse the client.
        resp = await client.post(
            f"{API_V1_PREFIX}/auth/callback/google",
            json={"code": "auth-code", "state": state},
        )
        assert resp.status_code == 200

    async def test_callback_without_state_cookie_returns_400(self, client, settings, monkeypatch):
        """A state replayed without the initiating client's cookie is rejected
        (login CSRF / session fixation, issue #110)."""
        _fake_exchange(
            monkeypatch,
            OAuthUserInfo(provider="google", oauth_id="csrf-1", email="v@example.com", name="V", email_verified=True),
        )
        # Mint a perfectly valid, signed state but DON'T set the matching cookie.
        req = build_authorization_request("google", settings)
        state = parse_qs(urlparse(req.url).query)["state"][0]
        resp = await client.post(
            f"{API_V1_PREFIX}/auth/callback/google",
            json={"code": "auth-code", "state": state},
        )
        assert resp.status_code == 400
        # The victim's account is never created from a replayed state.
        assert await User.find_one(User.email == "v@example.com") is None

    async def test_callback_with_mismatched_state_cookie_returns_400(self, client, settings, monkeypatch):
        """A state bound to one client cannot be completed with a different nonce."""
        _fake_exchange(
            monkeypatch,
            OAuthUserInfo(provider="google", oauth_id="csrf-2", email="w@example.com", name="W", email_verified=True),
        )
        req = build_authorization_request("google", settings)
        state = parse_qs(urlparse(req.url).query)["state"][0]
        # Attacker-controlled cookie (right name, wrong value) that does not match
        # the state's commitment.
        client.cookies.set(req.cookie_name, "some-other-clients-nonce")
        resp = await client.post(
            f"{API_V1_PREFIX}/auth/callback/google",
            json={"code": "auth-code", "state": state},
        )
        assert resp.status_code == 400

    async def test_callback_clears_state_cookie_on_success(self, client, settings, monkeypatch):
        """The single-use state cookie is cleared once the callback consumes it."""
        _fake_exchange(
            monkeypatch,
            OAuthUserInfo(provider="google", oauth_id="clr-1", email="clr@example.com", name="C", email_verified=True),
        )
        state = _bind_state(client, "google", settings)
        resp = await client.post(
            f"{API_V1_PREFIX}/auth/callback/google",
            json={"code": "auth-code", "state": state},
        )
        assert resp.status_code == 200
        set_cookie = (resp.headers.get("set-cookie") or "").lower()
        assert STATE_COOKIE_PREFIX in set_cookie
        assert "max-age=0" in set_cookie or "expires=" in set_cookie

    async def test_concurrent_logins_do_not_clobber_each_other(self, client, settings, monkeypatch):
        """Two login flows in one browser stay independent (per-flow cookies).

        Regression guard: a single shared cookie would let the second /login
        overwrite the first flow's nonce, breaking the first callback.
        """
        _fake_exchange(
            monkeypatch,
            OAuthUserInfo(provider="google", oauth_id="cc-1", email="cc@example.com", name="CC", email_verified=True),
        )
        first = await client.post(f"{API_V1_PREFIX}/auth/login/google")
        first_state = parse_qs(urlparse(first.json()["authorization_url"]).query)["state"][0]
        # A second login (e.g. another tab / double-click) before the first completes.
        second = await client.post(f"{API_V1_PREFIX}/auth/login/google")
        assert second.status_code == 200
        # The first flow still completes — its per-flow cookie was not overwritten.
        resp = await client.post(
            f"{API_V1_PREFIX}/auth/callback/google",
            json={"code": "auth-code", "state": first_state},
        )
        assert resp.status_code == 200

    async def test_google_callback_creates_user_and_returns_jwt(self, client, settings, monkeypatch):
        _fake_exchange(
            monkeypatch,
            OAuthUserInfo(
                provider="google", oauth_id="g-1", email="alice@example.com", name="Alice", email_verified=True
            ),
        )
        state = _bind_state(client, "google", settings)
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

    async def test_callback_creates_default_workspace_for_new_user(self, client, settings, monkeypatch):
        """Registration bootstraps a default workspace (US-9.4)."""
        from acemusic.api.models import Workspace
        from acemusic.api.services.workspaces import DEFAULT_WORKSPACE_NAME

        _fake_exchange(
            monkeypatch,
            OAuthUserInfo(provider="google", oauth_id="g-ws", email="ws@example.com", name="W", email_verified=True),
        )
        resp = await client.post(
            f"{API_V1_PREFIX}/auth/callback/google",
            json={"code": "auth-code", "state": _bind_state(client, "google", settings)},
        )
        assert resp.status_code == 200
        user = await User.find_one(User.oauth_provider == "google", User.oauth_id == "g-ws")
        workspaces = await Workspace.find(Workspace.user_id == user.id).to_list()
        assert len(workspaces) == 1
        assert workspaces[0].is_default is True
        assert workspaces[0].name == DEFAULT_WORKSPACE_NAME

    async def test_repeat_login_does_not_create_second_default_workspace(self, client, settings, monkeypatch):
        from acemusic.api.models import Workspace

        info = OAuthUserInfo(
            provider="google", oauth_id="g-ws2", email="ws2@example.com", name="W", email_verified=True
        )
        for code in ("c1", "c2"):
            _fake_exchange(monkeypatch, info)
            resp = await client.post(
                f"{API_V1_PREFIX}/auth/callback/google",
                json={"code": code, "state": _bind_state(client, "google", settings)},
            )
            assert resp.status_code == 200
        user = await User.find_one(User.oauth_provider == "google", User.oauth_id == "g-ws2")
        workspaces = await Workspace.find(Workspace.user_id == user.id).to_list()
        assert len(workspaces) == 1

    async def test_discord_callback_creates_user_and_returns_jwt(self, client, settings, monkeypatch):
        _fake_exchange(
            monkeypatch,
            OAuthUserInfo(provider="discord", oauth_id="d-1", email="bob@example.com", name="Bob", email_verified=True),
        )
        state = _bind_state(client, "discord", settings)
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
            OAuthUserInfo(provider="google", oauth_id="g-9", email="old@example.com", name="Old", email_verified=True),
        )
        await client.post(
            f"{API_V1_PREFIX}/auth/callback/google",
            json={"code": "c1", "state": _bind_state(client, "google", settings)},
        )
        _fake_exchange(
            monkeypatch,
            OAuthUserInfo(provider="google", oauth_id="g-9", email="new@example.com", name="New", email_verified=True),
        )
        await client.post(
            f"{API_V1_PREFIX}/auth/callback/google",
            json={"code": "c2", "state": _bind_state(client, "google", settings)},
        )
        users = await User.find(User.oauth_provider == "google", User.oauth_id == "g-9").to_list()
        assert len(users) == 1
        assert users[0].email == "new@example.com"
        assert users[0].name == "New"
        assert users[0].updated_at is not None

    async def test_unverified_email_returns_403(self, client, settings, monkeypatch):
        _fake_exchange(
            monkeypatch,
            OAuthUserInfo(
                provider="google", oauth_id="g-u", email="unverified@example.com", name="U", email_verified=False
            ),
        )
        resp = await client.post(
            f"{API_V1_PREFIX}/auth/callback/google",
            json={"code": "auth-code", "state": _bind_state(client, "google", settings)},
        )
        assert resp.status_code == 403
        # No account is created on an unverified address.
        assert await User.find_one(User.email == "unverified@example.com") is None

    async def test_same_email_via_second_provider_rejected_409(self, client, settings, monkeypatch):
        # First login via Google creates the account.
        _fake_exchange(
            monkeypatch,
            OAuthUserInfo(
                provider="google", oauth_id="g-shared", email="shared@example.com", name="Shared", email_verified=True
            ),
        )
        first = await client.post(
            f"{API_V1_PREFIX}/auth/callback/google",
            json={"code": "c1", "state": _bind_state(client, "google", settings)},
        )
        assert first.status_code == 200
        # Same email arrives via a second provider (Discord). The single-identity
        # model can't link it yet, so it is rejected deterministically (409) —
        # not 500'd on the unique index and not silently duplicated.
        _fake_exchange(
            monkeypatch,
            OAuthUserInfo(
                provider="discord", oauth_id="d-shared", email="shared@example.com", name="Shared", email_verified=True
            ),
        )
        second = await client.post(
            f"{API_V1_PREFIX}/auth/callback/discord",
            json={"code": "c2", "state": _bind_state(client, "discord", settings)},
        )
        assert second.status_code == 409
        # No duplicate account was created for the shared email.
        users = await User.find(User.email == "shared@example.com").to_list()
        assert len(users) == 1
        assert users[0].oauth_provider == "google"

    async def test_existing_identity_email_change_to_owned_address_does_not_500(self, client, settings, monkeypatch):
        """If a provider reports an email already owned by another account, the
        known-identity update keeps its current email rather than violating the
        unique index — the user still logs into their own account."""
        # Account A owns alice@example.com (via Google).
        _fake_exchange(
            monkeypatch,
            OAuthUserInfo(
                provider="google", oauth_id="g-A", email="alice@example.com", name="Alice", email_verified=True
            ),
        )
        a = await client.post(
            f"{API_V1_PREFIX}/auth/callback/google",
            json={"code": "cA", "state": _bind_state(client, "google", settings)},
        )
        assert a.status_code == 200

        # Account B exists (via Discord) with a different email.
        _fake_exchange(
            monkeypatch,
            OAuthUserInfo(provider="discord", oauth_id="d-B", email="bob@example.com", name="Bob", email_verified=True),
        )
        b = await client.post(
            f"{API_V1_PREFIX}/auth/callback/discord",
            json={"code": "cB", "state": _bind_state(client, "discord", settings)},
        )
        assert b.status_code == 200
        account_b_id = decode_access_token(b.json()["access_token"], settings)["sub"]

        # B logs in again, but Discord now reports alice@example.com (already A's).
        _fake_exchange(
            monkeypatch,
            OAuthUserInfo(
                provider="discord", oauth_id="d-B", email="alice@example.com", name="Bob", email_verified=True
            ),
        )
        resp = await client.post(
            f"{API_V1_PREFIX}/auth/callback/discord",
            json={"code": "cB2", "state": _bind_state(client, "discord", settings)},
        )
        # No duplicate-key 500; B logs into its own account, email unchanged.
        assert resp.status_code == 200
        assert decode_access_token(resp.json()["access_token"], settings)["sub"] == account_b_id
        b_user = await User.find_one(User.oauth_provider == "discord", User.oauth_id == "d-B")
        assert b_user.email == "bob@example.com"
        # A still uniquely owns alice@example.com.
        assert len(await User.find(User.email == "alice@example.com").to_list()) == 1

    async def test_bad_state_returns_400(self, client, settings, monkeypatch):
        _fake_exchange(
            monkeypatch,
            OAuthUserInfo(provider="google", oauth_id="g-2", email="x@example.com", name="X", email_verified=True),
        )
        resp = await client.post(
            f"{API_V1_PREFIX}/auth/callback/google",
            json={"code": "auth-code", "state": "tampered-state"},
        )
        assert resp.status_code == 400

    async def test_expired_state_returns_400(self, client, settings, monkeypatch):
        _fake_exchange(
            monkeypatch,
            OAuthUserInfo(provider="google", oauth_id="g-3", email="y@example.com", name="Y", email_verified=True),
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
            json={"code": "bad", "state": _bind_state(client, "google", settings)},
        )
        assert resp.status_code == 502


async def _login(client, settings, monkeypatch, *, oauth_id="r-1", email="r@example.com") -> dict:
    _fake_exchange(
        monkeypatch,
        OAuthUserInfo(provider="google", oauth_id=oauth_id, email=email, name="R", email_verified=True),
    )
    resp = await client.post(
        f"{API_V1_PREFIX}/auth/callback/google",
        json={"code": "code", "state": _bind_state(client, "google", settings)},
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
