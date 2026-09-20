"""OAuth2 login + JWT token router (US-8.3, Step 7).

Endpoints (mounted under ``/api/v1/auth``):

* ``POST /login/{provider}``    → ``{"authorization_url": ...}`` (302-style redirect URL)
* ``POST /callback/{provider}`` → exchange code, upsert the user, mint tokens
* ``POST /refresh``             → rotate the refresh token, mint a new access token
* ``POST /logout``              → revoke a refresh token (idempotent, 204)
* ``POST /plugin-token``        → mint a separate token pair for the VST3 plugin (#445)
* ``GET /plugin-tokens``        → list the caller's live plugin tokens, metadata only (#515)
* ``DELETE /plugin-tokens/{id}`` → revoke one plugin token (#515)

State (CSRF) validation is stateless via the signed ``state`` JWT minted in
:mod:`acemusic.api.auth.oauth`. ``exchange_code_for_user`` is referenced through
the ``oauth`` module (not imported by name) so route tests can substitute a stub
for the external provider HTTP without touching our own logic.

**Client-binding cookie (issue #110).** ``/login`` sets a per-flow, HttpOnly state
cookie whose nonce ``/callback`` must echo back, which is what stops a replayed
``state`` from completing in another browser (login CSRF / session fixation). This
means the client MUST preserve cookies between ``/login`` and ``/callback``:

* Same-origin frontend + API (recommended; e.g. the SPA served behind the same
  origin as the API via a reverse proxy): the default ``SameSite=Lax`` works.
* Split-origin SPA (frontend and API on different origins): the browser only
  sends the cookie on the cross-site callback when it is ``SameSite=None`` AND
  ``Secure`` (so, over HTTPS) and the fetch is credentialed
  (``credentials: 'include'``; CORS already allows credentials). Set
  ``ACEMUSIC_API_OAUTH_COOKIE_SAMESITE=none`` for that deployment.

Local development: a cross-origin **plain-HTTP** pair (e.g. ``localhost:3000`` →
``localhost:8000``) cannot carry this cookie at all — ``SameSite=None`` needs
``Secure`` and ``Secure`` needs HTTPS. This is a browser constraint, not a
limitation of this code: any login-CSRF defense needs a secret the victim's
browser holds, which over cross-origin HTTP is impossible. Run the SPA as a
same-origin proxy to the API in dev (recommended) or serve both over HTTPS.

HTTP status choices (documented for callers):
* unknown provider → ``400`` (client asked for something we don't support)
* unconfigured provider credentials → ``503`` (server misconfiguration, retryable
  once an operator sets the env vars)
* bad/expired/tampered ``state`` → ``400`` (treated as a malformed CSRF request)
* invalid/revoked/expired refresh token → ``401``
* provider rejects the code / userinfo fails → ``502`` (upstream dependency failed;
  the detail is generic so no provider secrets leak)
* logout → ``204`` always (idempotent; revoking an unknown token is a no-op)
* revoking a plugin token that is not the caller's own plugin token → ``404``
  (an unknown id, another account's token, and the caller's own *web session*
  are deliberately indistinguishable: this endpoint exists to manage DAW
  credentials, and must not become a way to probe for or sign out anything else)
"""

from datetime import datetime, timedelta, timezone

from beanie import PydanticObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

from ..auth import oauth, services
from ..auth.dependencies import CurrentUser, get_current_user
from ..auth.oauth import (
    STATE_EXPIRE_MINUTES,
    OAuthError,
    UnknownProviderError,
    build_authorization_request,
)
from ..auth.tokens import create_access_token, create_refresh_token
from ..exceptions import EmailAlreadyRegisteredError
from ..models import User
from ..services import users as user_service, workspaces as workspace_service
from ..settings import ApiSettings

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginResponse(BaseModel):
    authorization_url: str


class CallbackRequest(BaseModel):
    code: str
    state: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class PluginTokenSummary(BaseModel):
    """One live plugin token, as Settings lists it (#515).

    Metadata only — the credential itself is unrecoverable by design (only its
    SHA-256 hash is stored), and ``id`` is all a revoke needs.
    """

    id: str
    created_at: datetime
    expires_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds until the access token expires


def _settings(request: Request) -> ApiSettings:
    return request.app.state.settings


def _state_cookie_path(request: Request) -> str:
    """Scope the state cookie to the auth prefix (e.g. ``/api/v1/auth``).

    Derived from the request path so the router stays agnostic of the mount
    prefix; ``/login`` and ``/callback`` resolve to the same path, so the cookie
    set at login is sent to (and can be cleared by) the callback.
    """
    path = request.url.path
    for marker in ("/login/", "/callback/"):
        if marker in path:
            return path.rsplit(marker, 1)[0] or "/"
    return "/"


def _mint_token_pair(user: User, settings: ApiSettings) -> tuple[str, str]:
    """Mint a fresh ``(access_token, refresh_token)`` pair for ``user``."""
    access = create_access_token(
        user_id=str(user.id),
        email=user.email,
        subscription_tier=user.subscription_tier,
        settings=settings,
    )
    refresh = create_refresh_token()
    return access, refresh


@router.post("/login/{provider}", response_model=LoginResponse)
def login(provider: str, request: Request, response: Response) -> LoginResponse:
    """Return the provider's authorization URL for the client to redirect to.

    Also sets the client-binding state cookie (issue #110): its raw nonce is
    returned to the same client and re-checked at the callback, so a ``state``
    minted here cannot be replayed in another client's callback.
    """
    settings = _settings(request)
    try:
        auth_request = build_authorization_request(provider, settings)
    except UnknownProviderError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except OAuthError as exc:
        # Credentials not configured — server-side misconfiguration.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"OAuth provider {provider!r} is not configured.",
        ) from exc
    response.set_cookie(
        key=auth_request.cookie_name,
        value=auth_request.state_nonce,
        max_age=STATE_EXPIRE_MINUTES * 60,
        httponly=True,
        secure=settings.oauth_cookie_secure,
        samesite=settings.oauth_cookie_samesite,
        path=_state_cookie_path(request),
    )
    return LoginResponse(authorization_url=auth_request.url)


@router.post("/callback/{provider}", response_model=TokenResponse)
async def callback(provider: str, body: CallbackRequest, request: Request, response: Response) -> TokenResponse:
    """Complete the OAuth flow: validate state, exchange code, upsert user, mint tokens."""
    settings = _settings(request)

    try:
        consumed_cookie = oauth.validate_state(body.state, provider, settings, request.cookies)
    except UnknownProviderError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except OAuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid OAuth state.") from exc

    # Single-use: the state has served its purpose, so clear its per-flow cookie.
    response.delete_cookie(consumed_cookie, path=_state_cookie_path(request))

    try:
        info = await oauth.exchange_code_for_user(provider, body.code, settings)
    except UnknownProviderError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except OAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"OAuth exchange with {provider!r} failed.",
        ) from exc

    if not info.email_verified:
        # An unverified address could belong to anyone; creating or linking an
        # account on it would let an attacker squat or hijack a victim's email.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The OAuth provider has not verified this email address.",
        )

    # Upsert the user for this verified OAuth identity (US-8.4 owns the service;
    # it also seeds the profile display_name from the provider name on creation).
    #
    # #111: an email already registered under another provider is now *linked* onto that
    # account rather than refused, so the same person can sign in with Google or Discord
    # interchangeably. The 409 below survives for the case linking must not cover — a
    # collision the provider has not verified — which this route never reaches, because
    # the check above already turned it into a 403.
    try:
        user = await user_service.get_or_create_user(
            email=info.email,
            provider=info.provider,
            oauth_id=info.oauth_id,
            name=info.name,
            # #111: what permits a second provider to be linked onto an existing account.
            # Passed explicitly rather than assumed from the 403 gate above, so the
            # service never has to infer that its caller checked — and so the gate and the
            # permission move together if either is ever changed.
            email_verified=info.email_verified,
        )
    except EmailAlreadyRegisteredError as exc:
        # Unreachable from here while the 403 gate above stands, and kept deliberately:
        # it is the failure the service guarantees, and a future caller that stops
        # verifying should meet a 409 rather than an accidental account takeover.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This email is already registered with a different sign-in provider.",
        ) from exc

    # Every account gets a default workspace at registration (US-9.4). The call
    # is an idempotent get-or-create, so repeat logins are a cheap lookup and
    # accounts predating this hook are backfilled on their next login.
    await workspace_service.get_or_create_default_workspace(user.id)

    access, refresh = _mint_token_pair(user, settings)
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
    await services.store_refresh_token(user.id, refresh, expires_at)

    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, request: Request) -> TokenResponse:
    """Rotate a refresh token: atomically consume the old, issue a new pair."""
    settings = _settings(request)

    # The replacement is minted first so the swap below is a single atomic op:
    # validate + rotate in one ``find_one_and_update``, so a duplicated or
    # concurrent refresh can't mint two live pairs from one single-use token.
    # If the swap fails nothing was persisted and this pair is simply dropped.
    new_refresh = create_refresh_token()
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
    user_id = await services.rotate_refresh_token(body.refresh_token, new_refresh, expires_at)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = await User.get(user_id)
    if user is None:
        # The token validated but the user is gone — treat as unauthorized.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access = create_access_token(
        user_id=str(user.id),
        email=user.email,
        subscription_tier=user.subscription_tier,
        settings=settings,
    )

    return TokenResponse(
        access_token=access,
        refresh_token=new_refresh,
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.post("/plugin-token", response_model=TokenResponse)
async def plugin_token(request: Request, current: CurrentUser = Depends(get_current_user)) -> TokenResponse:
    """Mint a fresh token pair for the VST3 plugin (#445).

    A new refresh token rather than the web session's: refresh tokens are single-use,
    so a shared one would sign out whichever client rotated second.
    """
    settings = _settings(request)
    user = await user_service.get_user_by_id(current.user_id)
    if user is None:
        # The access token outlived the account; nothing to mint for.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    access, refresh = _mint_token_pair(user, settings)
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
    # Tagged so it can be listed and revoked apart from the browser session (#515).
    await services.store_refresh_token(user.id, refresh, expires_at, kind="plugin")
    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.get("/plugin-tokens", response_model=list[PluginTokenSummary])
async def list_plugin_tokens(current: CurrentUser = Depends(get_current_user)) -> list[PluginTokenSummary]:
    """List the caller's live plugin tokens, newest first (#515).

    Web sessions are not included: this is the DAW-credential list, and the
    browser session reading it is not something to revoke from here.
    """
    tokens = await services.list_plugin_tokens(PydanticObjectId(current.user_id))
    return [
        PluginTokenSummary(id=str(token.id), created_at=token.created_at, expires_at=token.expires_at)
        for token in tokens
    ]


@router.delete("/plugin-tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_plugin_token(token_id: str, current: CurrentUser = Depends(get_current_user)) -> Response:
    """Revoke one of the caller's plugin tokens (#515).

    Idempotent for a token that is the caller's own: revoking it twice still
    succeeds. Everything else — an unknown id, a malformed id, another account's
    token, the caller's own web session — is a flat 404, so the endpoint reveals
    nothing about tokens it will not act on.
    """
    try:
        oid = PydanticObjectId(token_id)
    except (InvalidId, TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plugin token not found.") from None
    if not await services.revoke_plugin_token(PydanticObjectId(current.user_id), oid):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plugin token not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(body: LogoutRequest) -> Response:
    """Revoke a refresh token. Idempotent: unknown/already-revoked tokens still 204."""
    await services.revoke_refresh_token(body.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
