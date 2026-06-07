"""Unit tests for the FastAPI auth dependency (US-8.3, Step 6).

A tiny throwaway FastAPI app mounts a route guarded by ``get_current_user`` (and
one guarded by ``get_current_user_optional``); ``TestClient`` exercises the
401/200 surface. No database needed — the dependency reads claims from the JWT.
"""

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from acemusic.api.auth.dependencies import (
    CurrentUser,
    get_current_user,
    get_current_user_optional,
)
from acemusic.api.auth.tokens import create_access_token
from acemusic.api.settings import ApiSettings


def _settings(**overrides) -> ApiSettings:
    base = {"_env_file": None, "jwt_secret_key": "test-secret-key-at-least-32-bytes-long-xx"}
    base.update(overrides)
    return ApiSettings(**base)


@pytest.fixture
def settings() -> ApiSettings:
    return _settings()


@pytest.fixture
def client(settings) -> TestClient:
    app = FastAPI()
    app.state.settings = settings

    @app.get("/protected")
    def protected(user: CurrentUser = Depends(get_current_user)) -> dict:
        return {"user_id": user.user_id, "email": user.email, "tier": user.subscription_tier}

    @app.get("/optional")
    def optional(user: CurrentUser | None = Depends(get_current_user_optional)) -> dict:
        if user is None:
            return {"authenticated": False}
        return {"authenticated": True, "user_id": user.user_id}

    return TestClient(app)


def _token(settings, **overrides) -> str:
    kwargs = {
        "user_id": "507f1f77bcf86cd799439011",
        "email": "user@example.com",
        "subscription_tier": "free",
        "settings": settings,
    }
    kwargs.update(overrides)
    return create_access_token(**kwargs)


class TestGetCurrentUser:
    def test_missing_header_returns_401_with_bearer_challenge(self, client):
        resp = client.get("/protected")
        assert resp.status_code == 401
        assert "bearer" in resp.headers.get("www-authenticate", "").lower()

    def test_garbage_token_returns_401(self, client):
        resp = client.get("/protected", headers={"Authorization": "Bearer not.a.jwt"})
        assert resp.status_code == 401

    def test_expired_token_returns_401(self, client, settings):
        # Hand-mint a token already expired so no clock travel is needed.
        now = datetime.now(timezone.utc)
        expired = jwt.encode(
            {
                "sub": "u",
                "email": "e@x.com",
                "tier": "free",
                "type": "access",
                "iat": now - timedelta(hours=2),
                "exp": now - timedelta(hours=1),
            },
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )
        resp = client.get("/protected", headers={"Authorization": f"Bearer {expired}"})
        assert resp.status_code == 401
        assert "expired" in resp.json()["detail"].lower()

    def test_invalid_and_expired_have_distinct_details(self, client, settings):
        garbage = client.get("/protected", headers={"Authorization": "Bearer not.a.jwt"})
        now = datetime.now(timezone.utc)
        expired = jwt.encode(
            {"sub": "u", "type": "access", "exp": now - timedelta(hours=1)},
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )
        expired_resp = client.get("/protected", headers={"Authorization": f"Bearer {expired}"})
        assert garbage.json()["detail"] != expired_resp.json()["detail"]

    def test_valid_token_returns_user(self, client, settings):
        token = _token(settings, subscription_tier="pro")
        resp = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["user_id"] == "507f1f77bcf86cd799439011"
        assert body["email"] == "user@example.com"
        assert body["tier"] == "pro"


class TestGetCurrentUserOptional:
    def test_missing_header_returns_none_path(self, client):
        resp = client.get("/optional")
        assert resp.status_code == 200
        assert resp.json() == {"authenticated": False}

    def test_invalid_token_still_401(self, client):
        """An explicitly-supplied bad token is an error, not anonymous access."""
        resp = client.get("/optional", headers={"Authorization": "Bearer not.a.jwt"})
        assert resp.status_code == 401

    def test_valid_token_authenticates(self, client, settings):
        token = _token(settings)
        resp = client.get("/optional", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["authenticated"] is True
