"""Fuzz every API route with malformed input: no response may carry a traceback or internal text (#339).

Each route is called, signed in as a free user against a throwaway database, with bad path ids and junk bodies.
Every error must be the shared ``{"detail", "code"}`` shape, and nothing may crash into a 500.
"""

import itertools

import httpx
import pytest

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import create_app
from acemusic.api.services.tiers import ENTERPRISE
from acemusic.api.settings import ApiSettings
from tests.users import make_user

pytestmark = pytest.mark.integration

_PATH_VALUES = ["not-an-id", "6ae85017a7a080810bff79b3", "%00", "' OR 1=1 --"]
_BODIES = [None, {}, {"unexpected": [1, {"nested": None}]}, "not json", ["a", "list"]]
_LEAKS = ("Traceback", 'File "', "Error(", "mongodb://", "/home/", "site-packages")


@pytest.fixture
def settings(mongo_db, mongo_settings) -> ApiSettings:
    return mongo_settings.model_copy(
        update={
            "jwt_secret_key": "test-secret-key-at-least-32-bytes-long-xx",
            "job_processor_enabled": False,
            "soundcloud_poller_enabled": False,
        }
    )


def _routes(app) -> list[tuple[str, str]]:
    """Every (method, path) the API serves, from its OpenAPI schema: included routers aren't flattened onto
    ``app.routes``."""
    return sorted(
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        for method in operations
        if method in {"get", "post", "put", "patch", "delete"}
    )


def _fill(path: str, value: str) -> str:
    out, inside = "", False
    for char in path:
        if char == "{":
            inside, out = True, out + value
        elif char == "}":
            inside = False
        elif not inside:
            out += char
    return out


@pytest.mark.parametrize(
    "identity",
    [{}, {"tier": ENTERPRISE, "is_admin": True}],
    ids=["free-user", "enterprise-admin"],
)
async def test_no_route_crashes_or_leaks_on_malformed_input(settings, identity: dict) -> None:
    """Run as a free user and again as an Enterprise admin, so the paid and admin routes are reached too."""
    app = create_app(settings)
    user = await make_user("fuzz@example.com", **identity)
    token = create_access_token(
        user_id=str(user.id), email=user.email, subscription_tier=user.subscription_tier, settings=settings
    )
    routes = _routes(app)
    assert len(routes) > 100, f"only {len(routes)} routes found: the fuzz would prove nothing"
    crashes: list[str] = []
    leaks: list[str] = []
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver", headers={"Authorization": f"Bearer {token}"}
    ) as client:
        for (method, path), value, body in itertools.product(routes, _PATH_VALUES, _BODIES):
            url = _fill(path, value)
            kwargs = {"content": body} if isinstance(body, str) else {"json": body}
            resp = await client.request(method, url, **({} if body is None else kwargs))
            where = f"{method} {path} [{value!r}, {body!r}] -> {resp.status_code}"
            if resp.status_code >= 500 and resp.status_code not in (502, 503):
                crashes.append(f"{where}: {resp.text[:200]}")
            if any(leak in resp.text for leak in _LEAKS):
                leaks.append(f"{where}: {resp.text[:200]}")
            if resp.status_code >= 400 and resp.headers.get("content-type", "").startswith("application/json"):
                assert "code" in resp.json(), where
    assert not leaks, "\n".join(leaks)
    assert not crashes, "\n".join(crashes[:40])
