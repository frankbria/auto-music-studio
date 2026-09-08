"""US-26.5: ``GET /api/v1/credits/usage``, the dashboard's single read.

The shaping rules live in ``tests/test_usage_service.py``; these tests cover the wire
contract — the auth gate, the payload shape, the ``days`` window parameter, and the one
behaviour the endpoint adds over the service: applying the monthly reset first, so the
dashboard and the sidebar cannot show different balances.
"""

from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.models import CreditTransaction
from acemusic.api.services import users as user_service
from acemusic.api.settings import ApiSettings

USAGE_URL = f"{API_V1_PREFIX}/credits/usage"


class TestAuthGate:
    """Runs in CI (no DB): usage is personal data, so anonymous reads are rejected."""

    def test_missing_auth_header_returns_401(self) -> None:
        resp = TestClient(create_app()).get(USAGE_URL)
        assert resp.status_code == 401


@pytest.fixture
def settings(mongo_db, mongo_settings) -> ApiSettings:
    return mongo_settings.model_copy(
        update={"jwt_secret_key": "test-secret-key-at-least-32-bytes-long-xx", "job_processor_enabled": False}
    )


@pytest.fixture
async def client(settings):
    transport = httpx.ASGITransport(app=create_app(settings))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


def _auth_headers(user, settings: ApiSettings) -> dict[str, str]:
    token = create_access_token(
        user_id=str(user.id), email=user.email, subscription_tier=user.subscription_tier, settings=settings
    )
    return {"Authorization": f"Bearer {token}"}


async def _make_user(email: str, *, monthly: float = 0.0, purchased: float = 0.0):
    user = await user_service.get_or_create_user(
        email=email, provider="google", oauth_id=f"g-{email}", name="Test User"
    )
    user.credits_balance = monthly
    user.purchased_credits = purchased
    user.credits_reset_at = datetime.now(timezone.utc)
    await user.save()
    return user


@pytest.mark.integration
class TestUsageEndpoint:
    async def test_it_returns_the_whole_dashboard_payload(self, client, settings) -> None:
        user = await _make_user("usage-api@example.com", monthly=20.0, purchased=5.0)
        await CreditTransaction(
            user_id=user.id, amount=-2.0, action_type="song", job_id="", balance_after=23.0
        ).insert()

        resp = await client.get(USAGE_URL, headers=_auth_headers(user, settings))

        assert resp.status_code == 200
        body = resp.json()
        assert body["tier"] == "free"
        assert body["monthly_credits"] == 20.0
        assert body["purchased_credits"] == 5.0
        assert body["total_credits"] == 25.0
        assert body["window_days"] == 30
        assert len(body["daily"]) == 30
        assert body["categories"] == [{"category": "generation", "credits": 2.0}]
        assert body["days_until_reset"] >= 0
        assert body["history"][0]["action_type"] == "song"
        assert body["history"][0]["category"] == "generation"
        assert body["history"][0]["clip_title"] is None

    async def test_the_window_is_configurable(self, client, settings) -> None:
        user = await _make_user("usage-api-window@example.com")
        await CreditTransaction(
            user_id=user.id,
            amount=-1.0,
            action_type="video",
            job_id="",
            balance_after=0.0,
            created_at=datetime.now(timezone.utc) - timedelta(days=5),
        ).insert()

        resp = await client.get(USAGE_URL, params={"days": 3}, headers=_auth_headers(user, settings))

        body = resp.json()
        assert body["window_days"] == 3
        assert len(body["daily"]) == 3
        assert body["history"] == []

    @pytest.mark.parametrize("days", [0, 400])
    async def test_an_out_of_range_window_is_rejected(self, client, settings, days: int) -> None:
        user = await _make_user("usage-api-badwindow@example.com")

        resp = await client.get(USAGE_URL, params={"days": days}, headers=_auth_headers(user, settings))

        assert resp.status_code == 422

    async def test_an_overdue_monthly_reset_is_applied_before_reporting(self, client, settings) -> None:
        # Same lazy top-up the sidebar's balance read performs. Without it the dashboard
        # would show a stale balance for exactly the people who came to check it.
        user = await _make_user("usage-api-reset@example.com", monthly=0.0)
        # Anniversary and last reset on the same date: the next reset is then due one
        # calendar month after the anchor (at most 31 days), so 45 days back is overdue on
        # every day of the year. With created_at 60 days back and credits_reset_at 45 days
        # back, the due date fell on created_at's day-of-month and landed in the future
        # whenever the suite ran on roughly the 15th-29th, which failed CI half of each month.
        anchor = datetime.now(timezone.utc) - timedelta(days=45)
        user.created_at = anchor
        user.credits_reset_at = anchor
        await user.save()

        resp = await client.get(USAGE_URL, headers=_auth_headers(user, settings))

        body = resp.json()
        assert body["monthly_credits"] == 50.0
        assert body["total_credits"] == 50.0
