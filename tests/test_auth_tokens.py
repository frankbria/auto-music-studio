"""Unit tests for JWT access tokens and opaque refresh tokens (US-8.3).

Pure functions — no database, no integration marker. ``freezegun`` drives the
clock so expiry is deterministic.
"""

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from freezegun import freeze_time

from acemusic.api.auth.tokens import (
    ConfigurationError,
    TokenError,
    TokenExpiredError,
    TokenInvalidError,
    create_access_token,
    create_refresh_token,
    decode_access_token,
)
from acemusic.api.settings import ApiSettings


def _settings(**overrides) -> ApiSettings:
    base = {"_env_file": None, "jwt_secret_key": "test-secret-key-at-least-32-bytes-long-xx"}
    base.update(overrides)
    return ApiSettings(**base)


class TestCreateAccessToken:
    def test_claims_are_correct(self):
        settings = _settings()
        token = create_access_token(
            user_id="507f1f77bcf86cd799439011",
            email="user@example.com",
            subscription_tier="pro",
            settings=settings,
        )
        payload = decode_access_token(token, settings)
        assert payload["sub"] == "507f1f77bcf86cd799439011"
        assert payload["email"] == "user@example.com"
        assert payload["tier"] == "pro"
        assert payload["type"] == "access"
        assert "exp" in payload and "iat" in payload

    def test_missing_secret_raises_configuration_error(self):
        settings = _settings(jwt_secret_key=None)
        with pytest.raises(ConfigurationError):
            create_access_token(user_id="u", email="e@x.com", subscription_tier="free", settings=settings)

    def test_expiry_honors_setting(self):
        settings = _settings(access_token_expire_minutes=15)
        with freeze_time("2026-01-01 12:00:00"):
            token = create_access_token(user_id="u", email="e@x.com", subscription_tier="free", settings=settings)
            # still valid before expiry
            assert decode_access_token(token, settings)["sub"] == "u"
        # jump 16 minutes -> expired
        with freeze_time("2026-01-01 12:16:00"):
            with pytest.raises(TokenExpiredError):
                decode_access_token(token, settings)


class TestDecodeAccessToken:
    def test_invalid_signature_rejected(self):
        token = create_access_token(user_id="u", email="e@x.com", subscription_tier="free", settings=_settings())
        other = _settings(jwt_secret_key="a-different-secret")
        with pytest.raises(TokenInvalidError):
            decode_access_token(token, other)

    def test_garbage_token_rejected(self):
        with pytest.raises(TokenInvalidError):
            decode_access_token("not.a.jwt", _settings())

    def test_wrong_type_rejected(self):
        settings = _settings()
        # Hand-mint a well-formed token whose type is not "access" (e.g. a
        # refresh-style token); it carries all required claims so it reaches and
        # fails the type check specifically.
        forged = jwt.encode(
            {"sub": "u", "type": "refresh", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )
        with pytest.raises(TokenInvalidError):
            decode_access_token(forged, settings)

    def test_missing_required_claim_rejected(self):
        """A signed token missing a required claim (``sub``) is rejected as invalid,
        not allowed through to raise a downstream KeyError/500."""
        settings = _settings()
        forged = jwt.encode(
            {"type": "access", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )
        with pytest.raises(TokenInvalidError):
            decode_access_token(forged, settings)

    def test_token_errors_share_base_class(self):
        assert issubclass(TokenExpiredError, TokenError)
        assert issubclass(TokenInvalidError, TokenError)

    def test_decode_missing_secret_raises_configuration_error(self):
        token = create_access_token(user_id="u", email="e@x.com", subscription_tier="free", settings=_settings())
        with pytest.raises(ConfigurationError):
            decode_access_token(token, _settings(jwt_secret_key=None))


class TestCreateRefreshToken:
    def test_is_long_and_unique(self):
        tokens = {create_refresh_token() for _ in range(100)}
        assert len(tokens) == 100  # no collisions
        assert all(len(t) >= 43 for t in tokens)  # token_urlsafe(48) ~ 64 chars
