"""SoundCloud OAuth 2.1 (PKCE) account-linking and track upload (US-13.2).

This is the distribution-side SoundCloud client. It is deliberately separate from
the *login* OAuth in :mod:`acemusic.api.auth.oauth`: that flow authenticates a
person and creates/looks-up a platform user, whereas this one links an *already
authenticated* user's SoundCloud account so the platform can upload on their
behalf. SoundCloud mandates PKCE (no exceptions), so the code-for-token exchange
carries a ``code_verifier`` rather than going through Authlib's login client.

CSRF for the connect→callback round trip reuses the login flow's stateless
double-submit pattern (a short-lived signed ``state`` JWT committing the SHA-256
of a per-flow nonce that the client echoes back via an HttpOnly cookie), adding a
``uid`` claim so a state minted for one user cannot complete another user's link.
The PKCE ``code_verifier`` rides alongside in its own per-flow HttpOnly cookie.

A single cohesive module (PKCE + state + HTTP + the token-refreshing
``get_valid_connection``) keeps the SoundCloud-specific surface in one place; it
is split only if a second distribution platform ever needs to share pieces.
"""

import asyncio
import base64
import hashlib
import hmac
import ipaddress
import secrets
import socket
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlparse

import httpx
import jwt

from ..settings import ApiSettings

# --- SoundCloud endpoints ---------------------------------------------------
SOUNDCLOUD_AUTHORIZE_URL = "https://secure.soundcloud.com/authorize"
SOUNDCLOUD_TOKEN_URL = "https://secure.soundcloud.com/oauth/token"
SOUNDCLOUD_API_BASE = "https://api.soundcloud.com"
SOUNDCLOUD_ME_URL = f"{SOUNDCLOUD_API_BASE}/me"
SOUNDCLOUD_UPLOAD_URL = f"{SOUNDCLOUD_API_BASE}/tracks"

#: SoundCloud caps uploads far higher (4 GB) but US-13.2 enforces a 500 MB ceiling.
MAX_UPLOAD_BYTES = 500 * 1024 * 1024

#: Marks the CSRF ``state`` JWT so it cannot be confused with an access token.
LINK_STATE_TOKEN_TYPE = "soundcloud_link_state"
LINK_STATE_EXPIRE_MINUTES = 10
#: Per-flow cookies (namespaced by a flow id named in the state's ``sid`` claim)
#: so concurrent link attempts don't clobber each other.
NONCE_COOKIE_PREFIX = "sc_link_nonce_"
VERIFIER_COOKIE_PREFIX = "sc_link_verifier_"
_NONCE_BYTES = 32
_FLOW_ID_BYTES = 8
_VERIFIER_BYTES = 64
#: Refresh slightly before the real expiry so an in-flight call isn't rejected.
_REFRESH_BUFFER_SECONDS = 60
_HTTP_TIMEOUT = 30.0


class SoundCloudError(Exception):
    """A SoundCloud OAuth/API call failed. The message is safe to surface."""


class SoundCloudNotConfiguredError(SoundCloudError):
    """SoundCloud client credentials are not configured."""


class SoundCloudNotConnectedError(SoundCloudError):
    """The user has no linked SoundCloud account."""


class SoundCloudAuthError(SoundCloudError):
    """Re-authorization is required (e.g. the refresh token was revoked)."""


@dataclass
class LinkAuthorizationRequest:
    """The connect step's output: the authorize URL plus the secrets to cookie.

    ``state_nonce`` and ``code_verifier`` must be set in their respective
    HttpOnly cookies (``nonce_cookie_name`` / ``verifier_cookie_name``); only the
    nonce's SHA-256 is committed inside the signed ``state``, and the verifier
    never leaves the client until the token exchange.
    """

    url: str
    state_nonce: str
    code_verifier: str
    nonce_cookie_name: str
    verifier_cookie_name: str


def nonce_cookie_name(flow_id: str) -> str:
    return f"{NONCE_COOKIE_PREFIX}{flow_id}"


def verifier_cookie_name(flow_id: str) -> str:
    return f"{VERIFIER_COOKIE_PREFIX}{flow_id}"


def _require_credentials(settings: ApiSettings) -> dict[str, str]:
    """Return the SoundCloud client credentials or raise if any are unset."""
    config = {
        "client_id": settings.soundcloud_client_id,
        "client_secret": settings.soundcloud_client_secret,
        "redirect_uri": settings.soundcloud_redirect_uri,
    }
    missing = [k for k, v in config.items() if not v]
    if missing:
        raise SoundCloudNotConfiguredError(f"SoundCloud is not configured (missing: {', '.join(missing)}).")
    return config  # type: ignore[return-value]


def _require_secret(settings: ApiSettings) -> str:
    if not settings.jwt_secret_key:
        raise SoundCloudError("ACEMUSIC_API_JWT_SECRET_KEY is not set; cannot sign the SoundCloud state token.")
    return settings.jwt_secret_key


def _b64url(raw: bytes) -> str:
    """base64url without padding, per RFC 7636."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def generate_pkce_pair() -> tuple[str, str]:
    """Return ``(code_verifier, code_challenge)`` for a PKCE S256 exchange."""
    verifier = _b64url(secrets.token_bytes(_VERIFIER_BYTES))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def _hash_nonce(nonce: str) -> str:
    return hashlib.sha256(nonce.encode("utf-8")).hexdigest()


def _create_link_state(user_id: str, nonce: str, flow_id: str, settings: ApiSettings) -> str:
    """Mint the short-lived signed CSRF ``state`` for an account-link flow."""
    secret = _require_secret(settings)
    now = datetime.now(timezone.utc)
    payload = {
        "type": LINK_STATE_TOKEN_TYPE,
        "uid": user_id,
        "cnf": _hash_nonce(nonce),
        "sid": flow_id,
        "iat": now,
        "exp": now + timedelta(minutes=LINK_STATE_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, secret, algorithm=settings.jwt_algorithm)


def build_connect_request(user_id: str, settings: ApiSettings) -> LinkAuthorizationRequest:
    """Build the SoundCloud authorize URL plus the per-flow client-binding secrets.

    Raises :class:`SoundCloudNotConfiguredError` if credentials are unset.
    """
    config = _require_credentials(settings)
    nonce = secrets.token_urlsafe(_NONCE_BYTES)
    flow_id = secrets.token_urlsafe(_FLOW_ID_BYTES)
    verifier, challenge = generate_pkce_pair()
    params = {
        "client_id": config["client_id"],
        "redirect_uri": config["redirect_uri"],
        "response_type": "code",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": _create_link_state(user_id, nonce, flow_id, settings),
    }
    return LinkAuthorizationRequest(
        url=f"{SOUNDCLOUD_AUTHORIZE_URL}?{urlencode(params)}",
        state_nonce=nonce,
        code_verifier=verifier,
        nonce_cookie_name=nonce_cookie_name(flow_id),
        verifier_cookie_name=verifier_cookie_name(flow_id),
    )


@dataclass
class ValidatedLink:
    """The result of validating a callback's ``state`` against the cookies."""

    code_verifier: str
    nonce_cookie_name: str
    verifier_cookie_name: str


def validate_link_state(state: str, user_id: str, settings: ApiSettings, cookies: Mapping[str, str]) -> ValidatedLink:
    """Verify the link ``state`` for ``user_id`` and return the PKCE verifier.

    Confirms the state is a non-expired, untampered link-state JWT bound to this
    user, whose committed nonce hash matches the client's cookie, and returns the
    ``code_verifier`` from the per-flow cookie plus the consumed cookie names so
    the caller can clear them. Raises :class:`SoundCloudError` otherwise.
    """
    secret = _require_secret(settings)
    try:
        payload = jwt.decode(state, secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise SoundCloudError(f"Invalid SoundCloud state: {exc}") from exc

    if payload.get("type") != LINK_STATE_TOKEN_TYPE:
        raise SoundCloudError("Invalid SoundCloud state: not a link-state token.")
    if payload.get("uid") != user_id:
        raise SoundCloudError("SoundCloud state does not belong to this user.")

    committed = payload.get("cnf")
    flow_id = payload.get("sid")
    if not committed or not flow_id:
        raise SoundCloudError("SoundCloud state is not bound to a client.")

    nonce = cookies.get(nonce_cookie_name(flow_id))
    if not nonce:
        raise SoundCloudError("Missing SoundCloud state cookie.")
    if not hmac.compare_digest(committed, _hash_nonce(nonce)):
        raise SoundCloudError("SoundCloud state does not match the initiating client.")

    verifier = cookies.get(verifier_cookie_name(flow_id))
    if not verifier:
        raise SoundCloudError("Missing SoundCloud PKCE cookie.")

    return ValidatedLink(
        code_verifier=verifier,
        nonce_cookie_name=nonce_cookie_name(flow_id),
        verifier_cookie_name=verifier_cookie_name(flow_id),
    )


async def _post_token(data: dict[str, str], settings: ApiSettings) -> dict:
    """POST to SoundCloud's token endpoint and return the parsed token response.

    A 400/401 is a rejected grant (invalid/expired/revoked) and surfaces as a
    :class:`SoundCloudAuthError` — the caller must re-authorize, not retry. Every
    other failure (network error, 429, 5xx) is transient and surfaces as a plain
    :class:`SoundCloudError` so callers can keep the connection and retry later.
    """
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.post(SOUNDCLOUD_TOKEN_URL, data=data)
    except httpx.HTTPError as exc:
        raise SoundCloudError("SoundCloud token request failed.") from exc

    if resp.status_code in (400, 401):
        raise SoundCloudAuthError("SoundCloud rejected the authorization grant.")
    try:
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise SoundCloudError("SoundCloud token request failed.") from exc
    return resp.json()


async def exchange_code(code: str, code_verifier: str, settings: ApiSettings) -> dict:
    """Exchange an authorization ``code`` (+ PKCE verifier) for a token response."""
    config = _require_credentials(settings)
    return await _post_token(
        {
            "grant_type": "authorization_code",
            "client_id": config["client_id"],
            "client_secret": config["client_secret"],
            "redirect_uri": config["redirect_uri"],
            "code_verifier": code_verifier,
            "code": code,
        },
        settings,
    )


async def refresh_access_token(refresh_token: str, settings: ApiSettings) -> dict:
    """Exchange a ``refresh_token`` for a fresh token response."""
    config = _require_credentials(settings)
    return await _post_token(
        {
            "grant_type": "refresh_token",
            "client_id": config["client_id"],
            "client_secret": config["client_secret"],
            "refresh_token": refresh_token,
        },
        settings,
    )


async def get_soundcloud_user(access_token: str) -> dict:
    """Fetch the linked SoundCloud account's profile (``GET /me``)."""
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.get(SOUNDCLOUD_ME_URL, headers={"Authorization": f"OAuth {access_token}"})
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError as exc:
        raise SoundCloudError("Fetching the SoundCloud profile failed.") from exc


def token_expiry(expires_in: object) -> datetime:
    """Translate SoundCloud's ``expires_in`` seconds into an absolute UTC instant.

    Defaults to one hour (SoundCloud's documented access-token lifetime) when the
    field is missing or unparseable, so a usable connection is never persisted
    with an expiry in the past.
    """
    try:
        seconds = int(expires_in)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        seconds = 3600
    return datetime.now(timezone.utc) + timedelta(seconds=seconds)


async def get_valid_connection(user_id: str, settings: ApiSettings):
    """Return the user's connection with a guaranteed-fresh access token.

    Refreshes (and persists) the token when it is within
    :data:`_REFRESH_BUFFER_SECONDS` of expiry. Only a *rejected* refresh (the
    refresh token was revoked/expired → :class:`SoundCloudAuthError`) deletes the
    connection; a transient failure (network/5xx → :class:`SoundCloudError`) is
    re-raised with the connection intact so a later call can retry.

    Imports the model locally to avoid a circular import at module load
    (router → service → model → …).
    """
    from beanie import PydanticObjectId

    from ..models import SoundCloudConnection

    connection = await SoundCloudConnection.find_one(SoundCloudConnection.user_id == PydanticObjectId(user_id))
    if connection is None:
        raise SoundCloudNotConnectedError("No SoundCloud account is linked.")

    if not _is_expired(connection.token_expires_at):
        return connection

    try:
        tokens = await refresh_access_token(connection.refresh_token, settings)
    except SoundCloudAuthError as exc:
        # Confirmed dead grant — the link is unusable; drop it so the user re-links.
        await connection.delete()
        raise SoundCloudAuthError("SoundCloud re-authorization is required.") from exc

    connection.access_token = tokens.get("access_token") or connection.access_token
    # SoundCloud rotates the refresh token on each use; keep the old one if absent.
    connection.refresh_token = tokens.get("refresh_token") or connection.refresh_token
    connection.token_expires_at = token_expiry(tokens.get("expires_in"))
    connection.updated_at = datetime.now(timezone.utc)
    await connection.save()
    return connection


def _is_expired(expires_at: datetime) -> bool:
    """True if ``expires_at`` is within the refresh buffer of now (UTC-aware)."""
    return _as_utc(expires_at) <= datetime.now(timezone.utc) + timedelta(seconds=_REFRESH_BUFFER_SECONDS)


def token_valid(expires_at: datetime) -> bool:
    """True if ``expires_at`` is still in the future.

    Tolerates the naive UTC datetimes MongoDB returns (Beanie drops tzinfo), so
    callers can compare a freshly-built or a round-tripped expiry uniformly.
    """
    return _as_utc(expires_at) > datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    """Treat a tz-naive datetime as UTC (MongoDB stores/returns naive UTC)."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


#: SoundCloud track[...] form fields we forward, in a stable order.
_TRACK_FIELDS = ("title", "genre", "description", "bpm", "key_signature", "isrc", "sharing")


async def upload_track(
    access_token: str,
    audio: bytes,
    filename: str,
    metadata: Mapping[str, object],
    artwork: bytes | None = None,
) -> dict:
    """Upload ``audio`` as a SoundCloud track and return the created track JSON.

    ``metadata`` keys in :data:`_TRACK_FIELDS` become ``track[<field>]`` form
    parts (omitting None/empty); ``artwork`` (when given) is sent as
    ``track[artwork_data]``. Returns the SoundCloud response (includes ``id`` and
    ``permalink_url``).
    """
    data = {f"track[{field}]": str(metadata[field]) for field in _TRACK_FIELDS if metadata.get(field) not in (None, "")}
    files: dict[str, tuple] = {"track[asset_data]": (filename, audio, "application/octet-stream")}
    if artwork is not None:
        files["track[artwork_data]"] = ("artwork", artwork, "application/octet-stream")
    try:
        async with httpx.AsyncClient(timeout=None) as client:
            resp = await client.post(
                SOUNDCLOUD_UPLOAD_URL,
                headers={"Authorization": f"OAuth {access_token}"},
                data=data,
                files=files,
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError as exc:
        raise SoundCloudError("SoundCloud track upload failed.") from exc


async def _assert_public_url(url: str) -> None:
    """Reject non-http(s) URLs or hosts resolving to a private/internal address.

    Guards the user-supplied ``artwork_url`` against SSRF (cloud metadata,
    internal services). ponytail: this validates the *resolved* host then lets
    httpx connect, so there's a small TOCTOU window and DNS-rebind gap; pin the
    connection to the checked IP if this ever fronts untrusted high-value infra.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SoundCloudError("Artwork URL must use http or https.")
    host = parsed.hostname
    if not host:
        raise SoundCloudError("Artwork URL has no host.")
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, host, parsed.port or 443, 0, socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise SoundCloudError("Artwork URL host could not be resolved.") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise SoundCloudError("Artwork URL resolves to a non-public address.")


async def fetch_artwork(url: str) -> bytes:
    """Download cover-art bytes from a public ``url`` for an upload.

    Redirects are *not* followed: a public URL that 30x-redirects to an internal
    address would bypass the pre-flight host check, so a redirect is treated as a
    failed fetch rather than chased.
    """
    await _assert_public_url(url)
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=False) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.content
    except httpx.HTTPError as exc:
        raise SoundCloudError("Fetching the artwork failed.") from exc
