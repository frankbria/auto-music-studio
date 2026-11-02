"""Per-user, per-kind request limits, tiered by plan (US-28.4, #341).

Every authenticated request counts against its user's ``read`` (GET/HEAD) or ``write`` (anything else) limit, and
every billed job against ``generation``. Free gets the configured base, Pro three times it, Enterprise ten times. Over
the limit is a 429 with ``Retry-After``.

The middleware reads the user and plan from the access token, so a limit costs no database read; an invalid token
passes through to the route, which answers 401. Generation is counted where the job is charged
(``credits.charge_and_create``), which reaches this request's limits through a context variable.

The plan is the one in the access token, so a plan change applies when the token is next refreshed (minutes). Like
the other limiters this is per process (see :mod:`.rate_limit`).
"""

import logging
import time
from collections import deque
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Literal

from fastapi import HTTPException, status
from starlette.types import ASGIApp, Receive, Scope, Send

from ..auth.tokens import decode_access_token
from ..errors import error_response
from ..services import tiers
from ..settings import ApiSettings
from .rate_limit import FixedWindowRateLimiter

logger = logging.getLogger(__name__)

LimitKind = Literal["read", "write", "generation"]

#: How many times the base limit each plan gets.
TIER_FACTORS: dict[str, int] = {tiers.FREE: 1, tiers.PRO: 3, tiers.ENTERPRISE: 10}

_DETAILS: dict[LimitKind, str] = {
    "read": "You're making requests too quickly. Wait a moment and try again.",
    "write": "You're making changes too quickly. Wait a moment and try again.",
    "generation": "You're starting creations too quickly. Wait a moment and try again.",
}


@dataclass(frozen=True)
class Rejection:
    at: float
    user_id: str
    tier: str
    kind: LimitKind


class UserRateLimits:
    """One fixed-window limiter per (kind, plan), and a short record of who was turned away."""

    def __init__(self, settings: ApiSettings, recent: int = 200) -> None:
        bases: dict[LimitKind, int] = {
            "read": settings.rate_limit_reads_per_minute,
            "write": settings.rate_limit_writes_per_minute,
            "generation": settings.rate_limit_generations_per_minute,
        }
        self.limits = {
            kind: {tier: base * factor for tier, factor in TIER_FACTORS.items()} for kind, base in bases.items()
        }
        self._limiters = {
            (kind, tier): FixedWindowRateLimiter(limit, 60, _DETAILS[kind])
            for kind, by_tier in self.limits.items()
            for tier, limit in by_tier.items()
        }
        self.rejections: deque[Rejection] = deque(maxlen=recent)

    def check(self, kind: LimitKind, user_id: str, tier: str) -> None:
        """Count one request; raise 429 with ``Retry-After`` once the user is over their plan's limit."""
        plan = tiers.normalise(tier)
        try:
            self._limiters[(kind, plan)].check(user_id)
        except HTTPException:
            self.rejections.append(Rejection(time.time(), user_id, plan, kind))
            raise


_current: ContextVar[tuple[UserRateLimits, str, str] | None] = ContextVar("user_rate_limits", default=None)


def check_generation(jobs: int = 1) -> None:
    """Count ``jobs`` billed jobs against the requesting user's generation limit; nothing outside a signed-in request.

    A path that queues billed jobs without ``credits.charge_and_create`` must call this itself before charging.
    """
    current = _current.get()
    if current is not None:
        limits, user_id, tier = current
        for _ in range(jobs):
            limits.check("generation", user_id, tier)


class UserRateLimitMiddleware:
    """Pure ASGI, so the context variable it sets is the one the route runs in."""

    def __init__(self, app: ASGIApp, limits: UserRateLimits, settings: ApiSettings) -> None:
        self.app = app
        self.limits = limits
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        identity = self._identity(scope) if scope["type"] == "http" else None
        if identity is None:
            await self.app(scope, receive, send)
            return
        user_id, tier = identity
        kind: LimitKind = "read" if scope["method"] in ("GET", "HEAD") else "write"
        try:
            self.limits.check(kind, user_id, tier)
        except HTTPException as exc:
            response = error_response(status.HTTP_429_TOO_MANY_REQUESTS, exc.detail, "rate_limited", exc.headers)
            await response(scope, receive, send)
            return
        token = _current.set((self.limits, user_id, tier))
        try:
            await self.app(scope, receive, send)
        finally:
            _current.reset(token)

    def _identity(self, scope: Scope) -> tuple[str, str] | None:
        for name, value in scope["headers"]:
            if name == b"authorization":
                scheme, _, token = value.decode("latin-1").partition(" ")
                if scheme.lower() != "bearer" or not token:
                    return None
                try:
                    claims = decode_access_token(token, self.settings)
                except Exception:  # any token the route would refuse is the route's to refuse, with its own 401
                    logger.debug("Rate limits skipped a request whose token didn't decode", exc_info=True)
                    return None
                return str(claims["sub"]), str(claims.get("tier") or tiers.FREE)
        return None
