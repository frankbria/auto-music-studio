"""JWT access tokens and opaque refresh tokens (US-8.3).

Access tokens are short-lived signed JWTs (PyJWT) carrying the user's identity
and subscription tier. Refresh tokens are opaque high-entropy strings; only their
SHA-256 hash is stored server-side (see :mod:`acemusic.api.auth.services`).

These are pure functions with no I/O so they can be unit-tested without a DB.
"""

import secrets
from datetime import datetime, timedelta, timezone

import jwt

from ..settings import ApiSettings

#: Marks an access token so it cannot be confused with a token minted for another
#: purpose (e.g. a CSRF ``state`` JWT). ``decode_access_token`` rejects mismatches.
ACCESS_TOKEN_TYPE = "access"


class ConfigurationError(RuntimeError):
    """Raised when auth is used but ``jwt_secret_key`` is not configured."""


class TokenError(Exception):
    """Base class for access-token validation failures."""


class TokenExpiredError(TokenError):
    """The token's ``exp`` claim is in the past."""


class TokenInvalidError(TokenError):
    """The token's signature, structure, or claims are invalid."""


def _require_secret(settings: ApiSettings) -> str:
    if not settings.jwt_secret_key:
        raise ConfigurationError(
            "ACEMUSIC_API_JWT_SECRET_KEY is not set; cannot sign or verify JWTs. "
            "Set a strong random secret before using authentication."
        )
    return settings.jwt_secret_key


def create_access_token(
    user_id: str,
    email: str,
    subscription_tier: str,
    settings: ApiSettings,
) -> str:
    """Mint a signed access-token JWT for the given user.

    Raises :class:`ConfigurationError` if no signing secret is configured.
    """
    secret = _require_secret(settings)
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "email": email,
        "tier": subscription_tier,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
        "type": ACCESS_TOKEN_TYPE,
    }
    return jwt.encode(payload, secret, algorithm=settings.jwt_algorithm)


def create_refresh_token() -> str:
    """Return a new opaque, URL-safe refresh token (high entropy)."""
    return secrets.token_urlsafe(48)


def decode_access_token(token: str, settings: ApiSettings) -> dict:
    """Verify signature + expiry and return the token's claims.

    Raises :class:`TokenExpiredError` if expired, :class:`TokenInvalidError` for
    any other validation failure (bad signature, malformed, or non-access type),
    and :class:`ConfigurationError` if no signing secret is configured.
    """
    secret = _require_secret(settings)
    try:
        payload = jwt.decode(token, secret, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError("Access token has expired.") from exc
    except jwt.PyJWTError as exc:
        raise TokenInvalidError(f"Invalid access token: {exc}") from exc

    if payload.get("type") != ACCESS_TOKEN_TYPE:
        raise TokenInvalidError("Token is not an access token.")
    return payload
