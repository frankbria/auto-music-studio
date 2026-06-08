"""OAuth2 provider clients for Google and Discord (US-8.3, Step 5).

The platform API is stateless — there is no session middleware — so CSRF
protection cannot rely on a server-side session. The ``state`` parameter is a
short-lived signed JWT (``type="oauth_state"``) bound to the provider; the
callback verifies it with :func:`validate_state`.

A signed ``state`` is tamper-evident but, on its own, **not bound to the client
that started the flow** — anyone can mint one and replay it in a victim's
callback (login CSRF / session fixation, issue #110). To close that, the state is
bound to a per-client *nonce* using a stateless double-submit pattern:
:func:`build_authorization_request` mints a high-entropy ``state_nonce``, commits
only its SHA-256 into the signed state (the ``cnf`` claim), and returns the raw
nonce so the route can set it in an HttpOnly+SameSite cookie. At the callback,
:func:`validate_state` requires that cookie nonce to hash to the committed value.
An attacker can neither forge the signed state nor read/set the victim's HttpOnly
cookie, so a replayed state no longer validates.

The authorization URL is built directly (deterministic, easy to assert) while the
code-for-token exchange and the userinfo fetch use Authlib's
:class:`~authlib.integrations.httpx_client.AsyncOAuth2Client`, which is an
``httpx.AsyncClient`` under the hood and therefore mockable with ``respx``.

Provider differences (Google OIDC vs. Discord) are normalized to a single
:class:`OAuthUserInfo` so callers never branch on the provider.
"""

import hashlib
import hmac
import secrets
from collections.abc import Mapping
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
#: Prefix for the per-flow cookie carrying the raw client-bound nonce. Each login
#: gets its own ``<prefix><flow_id>`` cookie so concurrent flows (multi-tab,
#: double-click) don't clobber each other's nonce — the ``state`` names its cookie
#: via the ``sid`` claim.
STATE_COOKIE_PREFIX = "oauth_state_"
#: Bytes of entropy for the state nonce (``secrets.token_urlsafe`` argument).
STATE_NONCE_BYTES = 32
#: Bytes of entropy for the per-flow id that namespaces the state cookie.
STATE_FLOW_ID_BYTES = 8

SUPPORTED_PROVIDERS = ("google", "discord")


def state_cookie_name(flow_id: str) -> str:
    """Cookie name carrying the nonce for the login flow identified by ``flow_id``."""
    return f"{STATE_COOKIE_PREFIX}{flow_id}"


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
    email_verified: bool


@dataclass
class AuthorizationRequest:
    """An authorization URL plus the raw nonce that binds its ``state`` to a client.

    ``url`` is the provider authorization URL (the client redirects to it).
    ``state_nonce`` is the high-entropy secret the caller must set in the
    ``cookie_name`` cookie (HttpOnly+SameSite); only its SHA-256 is committed
    inside the signed ``state``, so the URL never carries the nonce itself.
    ``cookie_name`` is per-flow so concurrent logins don't overwrite each other.
    """

    url: str
    state_nonce: str
    cookie_name: str


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


def _hash_nonce(nonce: str) -> str:
    """SHA-256 of the client-bound nonce, committed into the signed ``state``."""
    return hashlib.sha256(nonce.encode("utf-8")).hexdigest()


def _create_state(provider: str, nonce: str, flow_id: str, settings: ApiSettings) -> str:
    """Mint a short-lived signed JWT used as the CSRF ``state`` value.

    The ``cnf`` (confirmation) claim binds the state to the client: it holds the
    SHA-256 of ``nonce``, whose raw value the client returns via cookie. The
    ``sid`` claim names that per-flow cookie so the callback reads the right one.
    """
    secret = _require_secret(settings)
    now = datetime.now(timezone.utc)
    payload = {
        "type": STATE_TOKEN_TYPE,
        "provider": provider,
        "cnf": _hash_nonce(nonce),
        "sid": flow_id,
        "iat": now,
        "exp": now + timedelta(minutes=STATE_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, secret, algorithm=settings.jwt_algorithm)


def build_authorization_request(provider: str, settings: ApiSettings) -> AuthorizationRequest:
    """Build the provider authorization URL plus the client-binding state nonce.

    Returns an :class:`AuthorizationRequest`; the caller redirects to ``.url`` and
    must set ``.state_nonce`` in the ``.cookie_name`` HttpOnly+SameSite cookie so
    the callback can prove the same client is completing the flow.

    Raises :class:`UnknownProviderError` for an unknown provider and
    :class:`OAuthError` if the provider's credentials are unconfigured.
    """
    config = _provider_config(provider, settings)
    nonce = secrets.token_urlsafe(STATE_NONCE_BYTES)
    flow_id = secrets.token_urlsafe(STATE_FLOW_ID_BYTES)
    params = {
        "client_id": config["client_id"],
        "redirect_uri": config["redirect_uri"],
        "response_type": "code",
        "scope": config["scope"],
        "state": _create_state(provider, nonce, flow_id, settings),
    }
    return AuthorizationRequest(
        url=f"{config['authorize_url']}?{urlencode(params)}",
        state_nonce=nonce,
        cookie_name=state_cookie_name(flow_id),
    )


def validate_state(state: str, provider: str, settings: ApiSettings, cookies: Mapping[str, str]) -> str:
    """Verify the signed CSRF ``state`` for ``provider`` against the client's cookies.

    The state names its own cookie (``sid`` claim); ``cookies`` is the request's
    cookie jar. The raw nonce in that cookie must hash to the ``cnf`` committed
    when the state was minted — a missing or mismatched nonce means the caller is
    not the client that started the flow.

    Returns the name of the consumed cookie (so the caller can clear it); raises
    :class:`UnknownProviderError` for an unsupported provider, or
    :class:`OAuthError` if the state is expired, tampered, the wrong token type,
    for a different provider, or not bound to this client.
    """
    if provider not in SUPPORTED_PROVIDERS:
        raise UnknownProviderError(f"Unsupported OAuth provider: {provider!r}")
    secret = _require_secret(settings)
    try:
        payload = jwt.decode(state, secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise OAuthError(f"Invalid OAuth state: {exc}") from exc

    if payload.get("type") != STATE_TOKEN_TYPE:
        raise OAuthError("Invalid OAuth state: not a state token.")
    if payload.get("provider") != provider:
        raise OAuthError("OAuth state provider mismatch.")

    committed = payload.get("cnf")
    flow_id = payload.get("sid")
    if not committed or not flow_id:
        raise OAuthError("OAuth state is not bound to a client.")
    cookie_name = state_cookie_name(flow_id)
    nonce = cookies.get(cookie_name)
    if not nonce:
        raise OAuthError("Missing OAuth state cookie.")
    # Constant-time compare so a mismatch can't be probed by timing.
    if not hmac.compare_digest(committed, _hash_nonce(nonce)):
        raise OAuthError("OAuth state does not match the initiating client.")
    return cookie_name


def _coerce_bool(value: object) -> bool:
    """Coerce a provider's verification flag (bool or "true"/"false" string)."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


def _require_field(provider: str, data: dict, key: str) -> object:
    """Return ``data[key]`` or raise :class:`OAuthError` if the provider omitted it.

    Provider userinfo is an upstream surface we don't control (e.g. Discord may
    return an account with no ``email``); a missing required field is an upstream
    failure (→ 502), not a server bug (→ 500).
    """
    value = data.get(key)
    if value is None or value == "":
        raise OAuthError(f"OAuth provider {provider!r} returned no {key!r}.")
    return value


def _normalize_userinfo(provider: str, data: dict) -> OAuthUserInfo:
    """Map a provider's userinfo payload to :class:`OAuthUserInfo`.

    The provider's email-verification signal is preserved (Google's
    ``email_verified``, Discord's ``verified``) so the caller can refuse to
    create or link accounts on an unverified address. A payload missing a
    required identity field raises :class:`OAuthError` rather than ``KeyError``.
    """
    if provider == "google":
        email = _require_field("google", data, "email")
        return OAuthUserInfo(
            provider="google",
            oauth_id=str(_require_field("google", data, "sub")),
            email=str(email),
            name=data.get("name") or str(email),
            email_verified=_coerce_bool(data.get("email_verified")),
        )
    email = _require_field("discord", data, "email")
    name = data.get("global_name") or data.get("username") or str(email)
    return OAuthUserInfo(
        provider="discord",
        oauth_id=str(_require_field("discord", data, "id")),
        email=str(email),
        name=name,
        email_verified=_coerce_bool(data.get("verified")),
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
