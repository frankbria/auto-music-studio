"""FastAPI auth dependencies (US-8.3, Step 6).

``get_current_user`` resolves the ``Authorization: Bearer <jwt>`` header into a
:class:`CurrentUser` built from the access token's claims, or raises 401. The
settings (and thus the signing secret) are read from ``request.app.state.settings``
so the dependency works against any app built by ``create_app``.

Future protected routers attach this via ``dependencies=[Depends(get_current_user)]``
(or take ``CurrentUser`` as a parameter when they need the identity).
"""

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from ..services import users as user_service
from ..settings import ApiSettings
from .tokens import TokenExpiredError, TokenInvalidError, decode_access_token

# auto_error=False so we can craft our own 401 (with the WWW-Authenticate
# challenge) and distinguish "no credentials" from "bad credentials".
_bearer = HTTPBearer(auto_error=False)


class CurrentUser(BaseModel):
    """The authenticated principal, derived from an access-token's claims."""

    user_id: str
    email: str
    subscription_tier: str


def get_settings(request: Request) -> ApiSettings:
    """FastAPI dependency exposing the app's :class:`ApiSettings`.

    Public so any router can depend on settings without reaching into a private
    symbol (``Depends(get_settings)``).
    """
    return request.app.state.settings


# Backwards-compatible private alias for this module's internal call sites.
_settings = get_settings


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _user_from_token(token: str, settings: ApiSettings) -> CurrentUser:
    """Decode ``token`` to a :class:`CurrentUser`, or raise 401.

    Expired and otherwise-invalid tokens get distinct detail messages.
    """
    try:
        claims = decode_access_token(token, settings)
    except TokenExpiredError as exc:
        raise _unauthorized("Access token has expired.") from exc
    except TokenInvalidError as exc:
        raise _unauthorized("Invalid access token.") from exc
    return CurrentUser(
        user_id=claims["sub"],
        email=claims.get("email", ""),
        subscription_tier=claims.get("tier", "free"),
    )


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> CurrentUser:
    """Require a valid Bearer access token; return the :class:`CurrentUser`.

    Raises 401 with a ``WWW-Authenticate: Bearer`` challenge when the header is
    missing, and 401 (distinct details) when the token is expired or invalid.
    """
    if credentials is None:
        raise _unauthorized("Not authenticated.")
    return _user_from_token(credentials.credentials, _settings(request))


async def require_existing_user(current: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Like :func:`get_current_user`, but also require the account to still exist.

    An access token outlives account deletion by up to its TTL; endpoints that
    create or manage user-owned records resolve the user first so a stale token
    gets a clean 404 instead of touching orphaned data (mirrors ``POST /generate``).
    """
    user = await user_service.get_user_by_id(current.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return current


def get_current_user_optional(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> CurrentUser | None:
    """Return the :class:`CurrentUser` if authenticated, else ``None``.

    Anonymous access (no header) yields ``None``. An *explicitly supplied* but
    invalid/expired token is still a 401 — it signals a broken client, not an
    intentional anonymous request. This includes a malformed or wrong-scheme
    ``Authorization`` header, which ``HTTPBearer(auto_error=False)`` reports as
    ``None`` credentials: we distinguish it from "no header" and reject it.
    """
    if credentials is None:
        if request.headers.get("Authorization"):
            raise _unauthorized("Invalid access token.")
        return None
    return _user_from_token(credentials.credentials, _settings(request))
