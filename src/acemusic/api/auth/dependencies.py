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

from ..services import credits as credits_service, tiers, users as user_service
from ..services.tiers import Capability
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


async def require_tier_capability(user_id: str, capability: Capability) -> None:
    """Raise 403 unless ``user_id``'s tier may use ``capability`` (US-26.2).

    Reads the tier from the **database**, not the token claims: an access token outlives
    a plan change by up to its TTL, so claims would let a downgraded account keep Pro and
    make someone who just paid wait for Pro to start working.

    The 403 body mirrors the 402's shape — what is locked, what it would do, where to go —
    so a client presents "you cannot do this yet" the same way whether the obstacle is
    money or plan.
    """
    user = await user_service.get_user_by_id(user_id)

    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    if tiers.allows(user.subscription_tier, capability):
        return

    name, benefit = tiers.describe(capability)
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "error": "upgrade_required",
            "capability": capability.value,
            "feature": name,
            "tier": tiers.normalise(user.subscription_tier),
            "required_tier": tiers.PRO,
            "message": f"{name} is a Pro feature — upgrade to {benefit}.",
            "upgrade_url": credits_service.UPGRADE_URL,
        },
    )


def require_capability(capability: Capability):
    """Router dependency form of :func:`require_tier_capability`.

    Use this when the whole endpoint is Pro-only. When the gate depends on a request
    *argument* instead — a video resolution, an export format, whether a generation named
    a custom voice — call ``require_tier_capability`` directly; a dependency cannot see
    those. Both raise the same 403, because they are the same check.
    """

    async def _dependency(current: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        await require_tier_capability(current.user_id, capability)
        return current

    return _dependency


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
