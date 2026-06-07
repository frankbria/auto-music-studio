"""OAuth2 provider clients for Google and Discord (US-8.3, Step 5).

The platform API is stateless — there is no session middleware — so CSRF
protection cannot rely on a server-side session. Instead the ``state`` parameter
is a short-lived signed JWT (``type="oauth_state"``) bound to the provider; the
callback verifies it with :func:`validate_state`. This gives stateless,
tamper-evident CSRF protection using the same ``jwt_secret_key`` as access tokens.

The authorization URL is built directly (deterministic, easy to assert) while the
code-for-token exchange and the userinfo fetch use Authlib's
:class:`~authlib.integrations.httpx_client.AsyncOAuth2Client`, which is an
``httpx.AsyncClient`` under the hood and therefore mockable with ``respx``.

Provider differences (Google OIDC vs. Discord) are normalized to a single
:class:`OAuthUserInfo` so callers never branch on the provider.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import jwt
from authlib.integrations.httpx_client import AsyncOAuth2Client

from ..settings import ApiSettings

# --- Provider endpoints -----------------------------------------------------
# Google publishes these via OIDC discovery
# (https://accounts.google.com/.well-known/openid-configuration); we pin the
# resolved values to avoid a network round-trip to the discovery document on
# every login. Discord has no discovery document, so its endpoints are explicit.
GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_SCOPE = "openid email profile"

DISCORD_AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
DISCORD_TOKEN_URL = "https://discord.com/api/oauth2/token"
DISCORD_USERINFO_URL = "https://discord.com/api/users/@me"
DISCORD_SCOPE = "identify email"

#: Marks the CSRF ``state`` JWT so it cannot be confused with an access token.
STATE_TOKEN_TYPE = "oauth_state"
#: ``state`` JWTs are short-lived: the round trip to the provider is seconds.
STATE_EXPIRE_MINUTES = 10

SUPPORTED_PROVIDERS = ("google", "discord")


class OAuthError(Exception):
    """An OAuth flow failed (bad credentials config, provider error, bad state)."""


class UnknownProviderError(OAuthError):
    """The requested provider is not one we support."""


@dataclass
class OAuthUserInfo:
    """Provider-agnostic identity extracted from a userinfo response."""

    provider: str
    oauth_id: str
    email: str
    name: str


def _provider_config(provider: str, settings: ApiSettings) -> dict:
    """Return endpoint + credential config for ``provider`` or raise.

    Raises :class:`UnknownProviderError` for an unsupported provider and
    :class:`OAuthError` when the provider's credentials are not configured.
    """
    if provider == "google":
        config = {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": settings.google_redirect_uri,
            "authorize_url": GOOGLE_AUTHORIZE_URL,
            "token_url": GOOGLE_TOKEN_URL,
            "userinfo_url": GOOGLE_USERINFO_URL,
            "scope": GOOGLE_SCOPE,
        }
    elif provider == "discord":
        config = {
            "client_id": settings.discord_client_id,
            "client_secret": settings.discord_client_secret,
            "redirect_uri": settings.discord_redirect_uri,
            "authorize_url": DISCORD_AUTHORIZE_URL,
            "token_url": DISCORD_TOKEN_URL,
            "userinfo_url": DISCORD_USERINFO_URL,
            "scope": DISCORD_SCOPE,
        }
    else:
        raise UnknownProviderError(f"Unsupported OAuth provider: {provider!r}")

    missing = [k for k in ("client_id", "client_secret", "redirect_uri") if not config[k]]
    if missing:
        raise OAuthError(f"OAuth provider {provider!r} is not configured (missing: {', '.join(missing)}).")
    return config


def _require_secret(settings: ApiSettings) -> str:
    if not settings.jwt_secret_key:
        raise OAuthError("ACEMUSIC_API_JWT_SECRET_KEY is not set; cannot sign the OAuth state token.")
    return settings.jwt_secret_key


def _create_state(provider: str, settings: ApiSettings) -> str:
    """Mint a short-lived signed JWT used as the CSRF ``state`` value."""
    secret = _require_secret(settings)
    now = datetime.now(timezone.utc)
    payload = {
        "type": STATE_TOKEN_TYPE,
        "provider": provider,
        "iat": now,
        "exp": now + timedelta(minutes=STATE_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, secret, algorithm=settings.jwt_algorithm)


def get_authorization_url(provider: str, settings: ApiSettings) -> str:
    """Build the provider's authorization URL (with a signed ``state``).

    Raises :class:`UnknownProviderError` for an unknown provider and
    :class:`OAuthError` if the provider's credentials are unconfigured.
    """
    config = _provider_config(provider, settings)
    params = {
        "client_id": config["client_id"],
        "redirect_uri": config["redirect_uri"],
        "response_type": "code",
        "scope": config["scope"],
        "state": _create_state(provider, settings),
    }
    return f"{config['authorize_url']}?{urlencode(params)}"


def validate_state(state: str, provider: str, settings: ApiSettings) -> bool:
    """Verify the signed CSRF ``state`` for ``provider``.

    Returns ``True`` on success; raises :class:`OAuthError` if the state is
    expired, tampered, the wrong token type, or for a different provider.
    """
    secret = _require_secret(settings)
    try:
        payload = jwt.decode(state, secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise OAuthError(f"Invalid OAuth state: {exc}") from exc

    if payload.get("type") != STATE_TOKEN_TYPE:
        raise OAuthError("Invalid OAuth state: not a state token.")
    if payload.get("provider") != provider:
        raise OAuthError("OAuth state provider mismatch.")
    return True


def _normalize_userinfo(provider: str, data: dict) -> OAuthUserInfo:
    """Map a provider's userinfo payload to :class:`OAuthUserInfo`."""
    if provider == "google":
        return OAuthUserInfo(
            provider="google",
            oauth_id=str(data["sub"]),
            email=data["email"],
            name=data.get("name") or data.get("email", ""),
        )
    name = data.get("global_name") or data.get("username") or data.get("email", "")
    return OAuthUserInfo(
        provider="discord",
        oauth_id=str(data["id"]),
        email=data["email"],
        name=name,
    )


async def exchange_code_for_user(provider: str, code: str, settings: ApiSettings) -> OAuthUserInfo:
    """Exchange an authorization ``code`` for the provider's user identity.

    Raises :class:`UnknownProviderError` for an unknown provider and
    :class:`OAuthError` if the provider rejects the code or the userinfo fetch
    fails. The raised message is safe to surface (no secrets).
    """
    config = _provider_config(provider, settings)
    try:
        async with AsyncOAuth2Client(
            client_id=config["client_id"],
            client_secret=config["client_secret"],
            redirect_uri=config["redirect_uri"],
            scope=config["scope"],
        ) as client:
            await client.fetch_token(
                config["token_url"],
                code=code,
                grant_type="authorization_code",
            )
            resp = await client.get(config["userinfo_url"])
            resp.raise_for_status()
            data = resp.json()
    except OAuthError:
        raise
    except Exception as exc:  # authlib OAuthError, httpx errors, etc.
        raise OAuthError(f"OAuth exchange with {provider!r} failed.") from exc

    return _normalize_userinfo(provider, data)
