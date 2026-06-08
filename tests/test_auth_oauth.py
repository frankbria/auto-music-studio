"""Unit tests for the OAuth2 provider clients (US-8.3, Step 5).

The authorization-URL and signed-``state`` logic are pure (no I/O). The
code-exchange path talks to a provider over HTTP; that HTTP is faked with
``respx`` so the happy paths and provider errors are exercised without leaving
the machine. We never mock our own code — only the external provider endpoints.
"""

from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
import respx
from freezegun import freeze_time

from acemusic.api.auth.oauth import (
    DISCORD_AUTHORIZE_URL,
    DISCORD_TOKEN_URL,
    DISCORD_USERINFO_URL,
    GOOGLE_AUTHORIZE_URL,
    GOOGLE_TOKEN_URL,
    GOOGLE_USERINFO_URL,
    AuthorizationRequest,
    OAuthError,
    OAuthUserInfo,
    UnknownProviderError,
    build_authorization_request,
    exchange_code_for_user,
    validate_state,
)
from acemusic.api.settings import ApiSettings


def _settings(**overrides) -> ApiSettings:
    base = {
        "_env_file": None,
        "jwt_secret_key": "test-secret-key-at-least-32-bytes-long-xx",
        "google_client_id": "google-id",
        "google_client_secret": "google-secret",
        "google_redirect_uri": "https://app.example.com/api/v1/auth/callback/google",
        "discord_client_id": "discord-id",
        "discord_client_secret": "discord-secret",
        "discord_redirect_uri": "https://app.example.com/api/v1/auth/callback/discord",
    }
    base.update(overrides)
    return ApiSettings(**base)


def _request(provider: str, settings: ApiSettings) -> AuthorizationRequest:
    """Build the authorization request and return the (url, state_nonce) bundle."""
    return build_authorization_request(provider, settings)


def _state_of(req: AuthorizationRequest) -> str:
    return parse_qs(urlparse(req.url).query)["state"][0]


class TestAuthorizationUrl:
    def test_google_url_has_expected_params(self):
        settings = _settings()
        req = _request("google", settings)
        assert isinstance(req, AuthorizationRequest)
        parsed = urlparse(req.url)
        assert req.url.startswith(GOOGLE_AUTHORIZE_URL)
        qs = parse_qs(parsed.query)
        assert qs["client_id"] == ["google-id"]
        assert qs["redirect_uri"] == [settings.google_redirect_uri]
        assert qs["response_type"] == ["code"]
        assert qs["scope"] == ["openid email profile"]
        assert "state" in qs
        # The raw client-bound nonce is returned separately for the cookie; it
        # is never placed in the URL/state (only its hash is committed there).
        assert req.state_nonce
        assert req.state_nonce not in req.url

    def test_discord_url_has_expected_params(self):
        settings = _settings()
        req = _request("discord", settings)
        parsed = urlparse(req.url)
        assert req.url.startswith(DISCORD_AUTHORIZE_URL)
        qs = parse_qs(parsed.query)
        assert qs["client_id"] == ["discord-id"]
        assert qs["redirect_uri"] == [settings.discord_redirect_uri]
        assert qs["response_type"] == ["code"]
        assert qs["scope"] == ["identify email"]
        assert "state" in qs
        assert req.state_nonce

    def test_each_request_has_a_unique_nonce(self):
        settings = _settings()
        first = _request("google", settings)
        second = _request("google", settings)
        assert first.state_nonce != second.state_nonce

    def test_unknown_provider_raises(self):
        with pytest.raises(UnknownProviderError):
            build_authorization_request("github", _settings())

    def test_missing_credentials_raises(self):
        settings = _settings(google_client_id=None)
        with pytest.raises(OAuthError):
            build_authorization_request("google", settings)


class TestStateRoundTrip:
    def test_state_validates_with_matching_nonce(self):
        settings = _settings()
        req = _request("google", settings)
        assert validate_state(_state_of(req), "google", settings, req.state_nonce) is True

    def test_missing_nonce_rejected(self):
        """A state replayed without the client's cookie nonce must fail (login CSRF)."""
        settings = _settings()
        req = _request("google", settings)
        with pytest.raises(OAuthError):
            validate_state(_state_of(req), "google", settings, None)

    def test_wrong_nonce_rejected(self):
        """A state bound to one client cannot be completed with a different nonce."""
        settings = _settings()
        req = _request("google", settings)
        with pytest.raises(OAuthError):
            validate_state(_state_of(req), "google", settings, "some-other-clients-nonce")

    def test_tampered_state_rejected(self):
        settings = _settings()
        req = _request("google", settings)
        with pytest.raises(OAuthError):
            validate_state(_state_of(req) + "tampered", "google", settings, req.state_nonce)

    def test_wrong_provider_rejected(self):
        settings = _settings()
        req = _request("google", settings)
        with pytest.raises(OAuthError):
            validate_state(_state_of(req), "discord", settings, req.state_nonce)

    def test_expired_state_rejected(self):
        settings = _settings()
        with freeze_time("2026-01-01 12:00:00"):
            req = _request("google", settings)
        with freeze_time("2026-01-01 12:30:00"):
            with pytest.raises(OAuthError):
                validate_state(_state_of(req), "google", settings, req.state_nonce)

    def test_non_oauth_state_jwt_rejected(self):
        """A validly-signed JWT that is not an oauth_state token must be rejected."""
        settings = _settings()
        forged = jwt.encode(
            {"type": "access", "provider": "google"},
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )
        with pytest.raises(OAuthError):
            validate_state(forged, "google", settings, "nonce")


class TestExchangeCodeForUser:
    @respx.mock
    async def test_google_happy_path(self):
        settings = _settings()
        respx.post(GOOGLE_TOKEN_URL).mock(
            return_value=httpx.Response(200, json={"access_token": "ya29.token", "token_type": "Bearer"})
        )
        respx.get(GOOGLE_USERINFO_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "sub": "google-sub-123",
                    "email": "alice@example.com",
                    "name": "Alice",
                    "email_verified": True,
                },
            )
        )
        info = await exchange_code_for_user("google", "auth-code", settings)
        assert isinstance(info, OAuthUserInfo)
        assert info.provider == "google"
        assert info.oauth_id == "google-sub-123"
        assert info.email == "alice@example.com"
        assert info.name == "Alice"
        # email_verified drives the 403 gate, so assert the mapping explicitly.
        assert info.email_verified is True

    @respx.mock
    async def test_discord_happy_path(self):
        settings = _settings()
        respx.post(DISCORD_TOKEN_URL).mock(
            return_value=httpx.Response(200, json={"access_token": "discord.token", "token_type": "Bearer"})
        )
        respx.get(DISCORD_USERINFO_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "discord-id-456",
                    "email": "bob@example.com",
                    "username": "bob",
                    "global_name": "Bob",
                    "verified": True,
                },
            )
        )
        info = await exchange_code_for_user("discord", "auth-code", settings)
        assert info.provider == "discord"
        assert info.oauth_id == "discord-id-456"
        assert info.email == "bob@example.com"
        # global_name preferred when present
        assert info.name == "Bob"
        # Discord's verification flag ("verified") maps to email_verified.
        assert info.email_verified is True

    @respx.mock
    async def test_discord_falls_back_to_username(self):
        settings = _settings()
        respx.post(DISCORD_TOKEN_URL).mock(
            return_value=httpx.Response(200, json={"access_token": "discord.token", "token_type": "Bearer"})
        )
        respx.get(DISCORD_USERINFO_URL).mock(
            return_value=httpx.Response(
                200,
                json={"id": "d-789", "email": "c@example.com", "username": "carol", "global_name": None},
            )
        )
        info = await exchange_code_for_user("discord", "code", settings)
        assert info.name == "carol"

    @respx.mock
    async def test_provider_token_error_raises_oauth_error(self):
        settings = _settings()
        respx.post(GOOGLE_TOKEN_URL).mock(return_value=httpx.Response(400, json={"error": "invalid_grant"}))
        with pytest.raises(OAuthError):
            await exchange_code_for_user("google", "bad-code", settings)

    @respx.mock
    async def test_provider_userinfo_error_raises_oauth_error(self):
        settings = _settings()
        respx.post(GOOGLE_TOKEN_URL).mock(
            return_value=httpx.Response(200, json={"access_token": "tok", "token_type": "Bearer"})
        )
        respx.get(GOOGLE_USERINFO_URL).mock(return_value=httpx.Response(401, json={"error": "unauthorized"}))
        with pytest.raises(OAuthError):
            await exchange_code_for_user("google", "code", settings)

    @respx.mock
    async def test_userinfo_missing_email_raises_oauth_error(self):
        """A provider userinfo payload missing a required field is an upstream
        failure (OAuthError → 502), not an uncaught KeyError → 500."""
        settings = _settings()
        respx.post(DISCORD_TOKEN_URL).mock(
            return_value=httpx.Response(200, json={"access_token": "tok", "token_type": "Bearer"})
        )
        # Discord can return an account with no email.
        respx.get(DISCORD_USERINFO_URL).mock(
            return_value=httpx.Response(200, json={"id": "d-noemail", "username": "noemail"})
        )
        with pytest.raises(OAuthError):
            await exchange_code_for_user("discord", "code", settings)

    async def test_exchange_unknown_provider_raises(self):
        with pytest.raises(UnknownProviderError):
            await exchange_code_for_user("github", "code", _settings())
