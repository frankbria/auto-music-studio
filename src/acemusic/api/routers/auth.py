"""OAuth2 login + JWT token router (US-8.3, Step 7).

Endpoints (mounted under ``/api/v1/auth``):

* ``POST /login/{provider}``    → ``{"authorization_url": ...}`` (302-style redirect URL)
* ``POST /callback/{provider}`` → exchange code, upsert the user, mint tokens
* ``POST /refresh``             → rotate the refresh token, mint a new access token
* ``POST /logout``              → revoke a refresh token (idempotent, 204)

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

HTTP status choices (documented for callers):
* unknown provider → ``400`` (client asked for something we don't support)
* unconfigured provider credentials → ``503`` (server misconfiguration, retryable
  once an operator sets the env vars)
* bad/expired/tampered ``state`` → ``400`` (treated as a malformed CSRF request)
* invalid/revoked/expired refresh token → ``401``
* provider rejects the code / userinfo fails → ``502`` (upstream dependency failed;
  the detail is generic so no provider secrets leak)
* logout → ``204`` always (idempotent; revoking an unknown token is a no-op)
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel

from ..auth import oauth, services
from ..auth.oauth import (
    STATE_EXPIRE_MINUTES,
    OAuthError,
    UnknownProviderError,
    build_authorization_request,
)
from ..auth.tokens import create_access_token, create_refresh_token
from ..models import User
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

    user = await User.find_one(User.oauth_provider == info.provider, User.oauth_id == info.oauth_id)
    if user is None:
        # No account for this provider identity. The User model holds a single
        # OAuth identity and email is unique-indexed, so if the verified address
        # is already registered under another provider we cannot link a second
        # identity yet: reject deterministically (409) rather than 500 on the
        # index or silently create a duplicate. Multi-identity linking is tracked
        # as future work (see PR "Known limitations").
        if await User.find_one(User.email == info.email) is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This email is already registered with a different sign-in provider.",
            )
        user = User(
            email=info.email,
            name=info.name,
            oauth_provider=info.provider,
            oauth_id=info.oauth_id,
        )
        await user.insert()
    else:
        # Known identity. The provider may report a changed email; only apply it
        # when the address is free (or already ours), otherwise keep our current
        # email so the user still logs into their own account without violating
        # the unique index.
        email_owner = await User.find_one(User.email == info.email)
        if email_owner is None or email_owner.id == user.id:
            user.email = info.email
            user.name = info.name
            user.updated_at = datetime.now(timezone.utc)
            await user.save()

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

    # Atomic consume (validate + revoke in one op) so a duplicated/concurrent
    # refresh can't mint two token pairs from the same single-use token.
    user_id = await services.consume_refresh_token(body.refresh_token)
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

    access, new_refresh = _mint_token_pair(user, settings)
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
    await services.store_refresh_token(user.id, new_refresh, expires_at)

    return TokenResponse(
        access_token=access,
        refresh_token=new_refresh,
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(body: LogoutRequest) -> Response:
    """Revoke a refresh token. Idempotent: unknown/already-revoked tokens still 204."""
    await services.revoke_refresh_token(body.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
