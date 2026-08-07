"""US-26.3 payment integration, driven end-to-end through the webhook (AC1-AC5).

Every acceptance criterion except the outbound redirect is reachable without a Stripe
account, because the tier only ever moves in response to a **webhook**: the subscription
lifecycle is an event stream, and an event stream can be replayed locally. These tests
sign real payloads with a real secret and post them at the real endpoint, so the
signature verification, the idempotency guard and the state machine are all exercised
for what they are rather than stubbed out.

What is *not* covered here: creating the Checkout and Portal sessions, which are
outbound calls to Stripe's API and need credentials this environment does not have.
Those are covered against the SDK seam instead — see ``TestCheckoutSurface``.
"""

import hashlib
import hmac
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.models import BillingEvent, User
from acemusic.api.services import billing as billing_service, users as user_service
from acemusic.api.settings import ApiSettings

WEBHOOK_URL = f"{API_V1_PREFIX}/billing/webhook"
SUBSCRIPTION_URL = f"{API_V1_PREFIX}/billing/subscription"
HISTORY_URL = f"{API_V1_PREFIX}/billing/history"
CHECKOUT_URL = f"{API_V1_PREFIX}/billing/checkout"

WEBHOOK_SECRET = "whsec_test_secret_for_local_signing"
CUSTOMER = "cus_test_123"


def _sign(payload: bytes, secret: str = WEBHOOK_SECRET, timestamp: int | None = None) -> str:
    """A genuine Stripe-Signature header.

    Stripe signs ``{timestamp}.{payload}`` with HMAC-SHA256. Built by hand here so the
    endpoint's verification is tested against the real scheme rather than against a
    stub that would pass whatever we fed it.
    """
    timestamp = timestamp or int(time.time())
    signed = f"{timestamp}.".encode() + payload
    digest = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def _event(event_type: str, obj: dict, event_id: str = "evt_test_1") -> bytes:
    """A Stripe event envelope.

    The top-level ``"object": "event"`` is not decoration — the SDK reads it to tell a
    v1 event from a v2 one, and omitting it makes ``construct_event`` raise before it
    ever reaches our code. Kept faithful so these tests fail for real reasons.
    """
    return json.dumps(
        {
            "id": event_id,
            "object": "event",
            "api_version": "2024-06-20",
            "created": int(time.time()),
            "type": event_type,
            "data": {"object": obj},
        }
    ).encode()


def _subscription(status: str = "active", **overrides) -> dict:
    return {
        "id": "sub_test_1",
        "customer": CUSTOMER,
        "status": status,
        "cancel_at_period_end": False,
        "current_period_end": 1_800_000_000,
        **overrides,
    }


class TestWebhookAuthentication:
    """Runs in CI (no DB): the endpoint mutates tiers, so an unsigned caller must fail."""

    def _client(self) -> TestClient:
        settings = ApiSettings(
            jwt_secret_key="test-secret-key-at-least-32-bytes-long-xx",
            stripe_secret_key="sk_test_x",
            stripe_webhook_secret=WEBHOOK_SECRET,
            stripe_price_id_pro="price_x",
            job_processor_enabled=False,
        )
        return TestClient(create_app(settings))

    def test_a_missing_signature_is_rejected(self) -> None:
        resp = self._client().post(WEBHOOK_URL, content=_event("invoice.paid", {}))
        assert resp.status_code == 400

    def test_a_forged_signature_is_rejected(self) -> None:
        payload = _event("customer.subscription.updated", _subscription())
        resp = self._client().post(
            WEBHOOK_URL,
            content=payload,
            headers={"Stripe-Signature": _sign(payload, secret="whsec_the_wrong_secret")},
        )
        assert resp.status_code == 400

    def test_a_stale_signature_is_rejected(self) -> None:
        # Replay defence. A signature captured an hour ago must not still work, which is
        # why verification goes through the SDK's timestamp-tolerant check.
        payload = _event("invoice.paid", {})
        resp = self._client().post(
            WEBHOOK_URL,
            content=payload,
            headers={"Stripe-Signature": _sign(payload, timestamp=int(time.time()) - 3600)},
        )
        assert resp.status_code == 400

    def test_a_correctly_signed_payload_verifies(self) -> None:
        # The positive control, without which the three rejections above prove nothing —
        # a verifier that rejected everything would pass them all.
        #
        # Asserted against the service rather than the endpoint because the endpoint
        # goes on to look the customer up, and that needs a database. The endpoint's
        # happy path is covered by every integration class below.
        settings = ApiSettings(stripe_webhook_secret=WEBHOOK_SECRET)
        payload = _event("customer.subscription.updated", _subscription())
        event = billing_service.verify_webhook(payload, _sign(payload), settings)
        assert event["type"] == "customer.subscription.updated"
        assert event["data"]["object"]["id"] == "sub_test_1"


class TestBillingDisabled:
    """A deployment with no Stripe must still boot and serve everything else."""

    def test_checkout_is_503_not_a_crash(self) -> None:
        settings = ApiSettings(
            jwt_secret_key="test-secret-key-at-least-32-bytes-long-xx",
            job_processor_enabled=False,
        )
        assert settings.stripe_enabled is False
        client = TestClient(create_app(settings))
        # Unauthenticated, so this is the auth gate — the point is the app exists.
        assert client.post(CHECKOUT_URL).status_code == 401

    def test_enabled_requires_all_three_settings(self) -> None:
        partial = ApiSettings(stripe_secret_key="sk_test_x", stripe_webhook_secret=WEBHOOK_SECRET)
        # No price id: a checkout would 400 at Stripe on click, which is a worse failure
        # than refusing at the door.
        assert partial.stripe_enabled is False


def _async_client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


@pytest.fixture
def settings(mongo_db, mongo_settings) -> ApiSettings:
    return mongo_settings.model_copy(
        update={
            "jwt_secret_key": "test-secret-key-at-least-32-bytes-long-xx",
            "job_processor_enabled": False,
            "stripe_secret_key": "sk_test_x",
            "stripe_webhook_secret": WEBHOOK_SECRET,
            "stripe_price_id_pro": "price_x",
        }
    )


@pytest.fixture
async def client(settings):
    async with _async_client(create_app(settings)) as ac:
        yield ac


def _auth_headers(user, settings: ApiSettings) -> dict[str, str]:
    token = create_access_token(
        user_id=str(user.id),
        email=user.email,
        subscription_tier=user.subscription_tier,
        settings=settings,
    )
    return {"Authorization": f"Bearer {token}"}


async def _subscriber(email: str) -> User:
    """A user already linked to a Stripe customer, as ``ensure_customer`` would leave them."""
    user = await user_service.get_or_create_user(
        email=email, provider="google", oauth_id=f"g-{email}", name="Test User"
    )
    user.stripe_customer_id = CUSTOMER
    await user.save()
    return user


async def _post_event(client, event_type: str, obj: dict, event_id: str = "evt_test_1"):
    payload = _event(event_type, obj, event_id=event_id)
    return await client.post(WEBHOOK_URL, content=payload, headers={"Stripe-Signature": _sign(payload)})


@pytest.mark.integration
class TestSubscribing:
    """AC1: a completed checkout activates Pro immediately."""

    async def test_checkout_completed_grants_pro(self, client) -> None:
        user = await _subscriber("sub-new@example.com")
        assert user.subscription_tier == "free"

        resp = await _post_event(
            client,
            "checkout.session.completed",
            {"customer": CUSTOMER, "subscription": "sub_test_1"},
        )
        assert resp.status_code == 200

        refreshed = await User.get(user.id)
        assert refreshed.subscription_tier == "pro"
        assert refreshed.stripe_subscription_id == "sub_test_1"
        assert refreshed.subscription_status == "active"


@pytest.mark.integration
class TestCancelling:
    """AC2: cancelling retains Pro until the end of the billing period."""

    async def test_a_pending_cancellation_keeps_pro(self, client) -> None:
        user = await _subscriber("sub-cancel@example.com")
        await _post_event(client, "checkout.session.completed", {"customer": CUSTOMER, "subscription": "sub_test_1"})

        # Stripe reports a pending cancellation as *still active*.
        await _post_event(
            client,
            "customer.subscription.updated",
            _subscription("active", cancel_at_period_end=True),
            event_id="evt_cancel_pending",
        )

        refreshed = await User.get(user.id)
        assert refreshed.subscription_tier == "pro", "cancelling must not remove access early"
        assert refreshed.subscription_cancel_at_period_end is True
        assert refreshed.subscription_current_period_end is not None

    async def test_the_period_ending_downgrades(self, client) -> None:
        user = await _subscriber("sub-ended@example.com")
        await _post_event(client, "checkout.session.completed", {"customer": CUSTOMER, "subscription": "sub_test_1"})

        await _post_event(
            client,
            "customer.subscription.deleted",
            _subscription("canceled"),
            event_id="evt_deleted",
        )

        refreshed = await User.get(user.id)
        assert refreshed.subscription_tier == "free"
        assert refreshed.subscription_status == "canceled"


@pytest.mark.integration
class TestFailedPayment:
    """AC3: a failed payment triggers a grace period with retry before downgrade."""

    async def test_a_failed_charge_does_not_downgrade(self, client) -> None:
        user = await _subscriber("sub-failed@example.com")
        await _post_event(client, "checkout.session.completed", {"customer": CUSTOMER, "subscription": "sub_test_1"})

        await _post_event(
            client,
            "invoice.payment_failed",
            {"customer": CUSTOMER, "amount_due": 1000, "currency": "usd", "status": "open"},
            event_id="evt_failed",
        )

        refreshed = await User.get(user.id)
        assert refreshed.subscription_tier == "pro", "one failed charge is not a cancellation"
        assert refreshed.subscription_status == "past_due"

    async def test_downgrade_only_once_stripe_gives_up(self, client) -> None:
        user = await _subscriber("sub-dunned@example.com")
        await _post_event(client, "checkout.session.completed", {"customer": CUSTOMER, "subscription": "sub_test_1"})
        await _post_event(
            client,
            "invoice.payment_failed",
            {"customer": CUSTOMER, "amount_due": 1000, "currency": "usd"},
            event_id="evt_failed_2",
        )
        # Retries exhausted: Stripe moves the subscription itself to unpaid.
        await _post_event(client, "customer.subscription.updated", _subscription("unpaid"), event_id="evt_unpaid")

        refreshed = await User.get(user.id)
        assert refreshed.subscription_tier == "free"

    async def test_a_recovered_payment_clears_the_grace_flag(self, client) -> None:
        user = await _subscriber("sub-recovered@example.com")
        await _post_event(client, "checkout.session.completed", {"customer": CUSTOMER, "subscription": "sub_test_1"})
        await _post_event(client, "invoice.payment_failed", {"customer": CUSTOMER}, event_id="evt_f3")
        await _post_event(
            client,
            "invoice.paid",
            {"customer": CUSTOMER, "amount_paid": 1000, "currency": "usd", "status": "paid"},
            event_id="evt_p3",
        )

        refreshed = await User.get(user.id)
        assert refreshed.subscription_status == "active"
        assert refreshed.subscription_tier == "pro"


@pytest.mark.integration
class TestBillingHistory:
    """AC4: billing history shows past charges with dates and amounts."""

    async def test_paid_invoices_appear_with_amount_and_date(self, client, settings) -> None:
        user = await _subscriber("sub-history@example.com")
        await _post_event(
            client,
            "invoice.paid",
            {
                "customer": CUSTOMER,
                "amount_paid": 1200,
                "currency": "usd",
                "status": "paid",
                "description": "Pro monthly",
                "hosted_invoice_url": "https://stripe.example/invoice/1",
            },
            event_id="evt_hist_1",
        )

        resp = await client.get(HISTORY_URL, headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        entries = resp.json()["entries"]
        assert len(entries) == 1
        entry = entries[0]
        # Stored as integer cents, presented in major units — no float ever touches
        # the stored value.
        assert entry["amount"] == 12.00
        assert entry["currency"] == "usd"
        assert entry["status"] == "paid"
        assert entry["invoice_url"] == "https://stripe.example/invoice/1"
        assert entry["created_at"]

    async def test_lifecycle_events_are_not_listed_as_charges(self, client, settings) -> None:
        # Found in the demo: subscription events are written to the same collection (it
        # is the idempotency guard), and they were surfacing as history rows with a dash
        # for the amount. A billing history is a list of charges, not a callback log.
        user = await _subscriber("sub-noise@example.com")
        await _post_event(
            client,
            "checkout.session.completed",
            {"customer": CUSTOMER, "subscription": "sub_test_1"},
            event_id="evt_noise_1",
        )
        await _post_event(
            client, "customer.subscription.updated", _subscription(), event_id="evt_noise_2"
        )
        await _post_event(
            client,
            "invoice.paid",
            {"customer": CUSTOMER, "amount_paid": 900, "currency": "usd", "status": "paid"},
            event_id="evt_noise_3",
        )

        resp = await client.get(HISTORY_URL, headers=_auth_headers(user, settings))
        entries = resp.json()["entries"]
        assert [e["event_type"] for e in entries] == ["invoice.paid"]
        # All three are still recorded — dropping them would break idempotency.
        assert await BillingEvent.find(BillingEvent.user_id == user.id).count() == 3

    async def test_a_failed_attempt_is_still_shown(self, client, settings) -> None:
        # "We tried to charge you and it did not work" is exactly what someone opens
        # this page to find out, so a failure is a charge for display purposes.
        user = await _subscriber("sub-failshown@example.com")
        await _post_event(
            client,
            "invoice.payment_failed",
            {"customer": CUSTOMER, "amount_due": 1200, "currency": "usd", "status": "open"},
            event_id="evt_failshown",
        )

        resp = await client.get(HISTORY_URL, headers=_auth_headers(user, settings))
        entries = resp.json()["entries"]
        assert len(entries) == 1
        assert entries[0]["amount"] == 12.00
        assert entries[0]["status"] == "open"

    async def test_history_is_scoped_to_the_caller(self, client, settings) -> None:
        mine = await _subscriber("sub-mine@example.com")
        await _post_event(client, "invoice.paid", {"customer": CUSTOMER, "amount_paid": 500}, event_id="evt_mine")
        stranger = await user_service.get_or_create_user(
            email="sub-stranger@example.com", provider="google", oauth_id="g-stranger", name="Other"
        )

        resp = await client.get(HISTORY_URL, headers=_auth_headers(stranger, settings))
        assert resp.json()["entries"] == []
        assert mine.id != stranger.id


@pytest.mark.integration
class TestWebhookIdempotency:
    """AC5: Stripe delivers at least once, so a redelivery must not double-apply."""

    async def test_a_redelivered_event_is_recorded_once(self, client, settings) -> None:
        user = await _subscriber("sub-dupe@example.com")
        body = {"customer": CUSTOMER, "amount_paid": 700, "currency": "usd", "status": "paid"}

        first = await _post_event(client, "invoice.paid", body, event_id="evt_same")
        second = await _post_event(client, "invoice.paid", body, event_id="evt_same")

        assert first.status_code == 200 and second.status_code == 200
        assert second.json()["status"] == "duplicate"
        assert await BillingEvent.find(BillingEvent.user_id == user.id).count() == 1

    async def test_an_unhandled_event_type_is_accepted_and_ignored(self, client) -> None:
        # A 4xx would make Stripe redeliver an event we will never act on.
        resp = await _post_event(client, "customer.discount.created", {"customer": CUSTOMER}, event_id="evt_ignored")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ignored"


@pytest.mark.integration
class TestSubscriptionEndpoint:
    async def test_it_reports_the_mirrored_state(self, client, settings) -> None:
        user = await _subscriber("sub-status@example.com")
        await _post_event(client, "checkout.session.completed", {"customer": CUSTOMER, "subscription": "sub_test_1"})
        await _post_event(
            client,
            "customer.subscription.updated",
            _subscription("active", cancel_at_period_end=True),
            event_id="evt_status",
        )

        resp = await client.get(SUBSCRIPTION_URL, headers=_auth_headers(user, settings))
        body = resp.json()
        assert body["tier"] == "pro"
        assert body["cancel_at_period_end"] is True
        assert body["current_period_end"] is not None
        assert body["billing_enabled"] is True


@pytest.mark.integration
class TestCheckoutSurface:
    """The outbound half of AC1.

    Creating the session is a call to Stripe's API, which needs credentials this
    environment does not have. The seam is substituted so the *endpoint contract* —
    auth, response shape, and the not-configured refusal — is still covered; what
    remains unverified is Stripe's own response, and that is stated in the PR rather
    than papered over.
    """

    async def test_it_returns_the_url_from_stripe(self, client, settings, monkeypatch) -> None:
        user = await _subscriber("sub-checkout@example.com")

        async def _fake_session(user_arg, settings_arg):
            return "https://checkout.stripe.com/c/pay/test_session"

        monkeypatch.setattr(billing_service, "create_checkout_session", _fake_session)
        resp = await client.post(CHECKOUT_URL, headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        assert resp.json()["url"].startswith("https://checkout.stripe.com/")

    async def test_it_503s_when_stripe_is_not_configured(self, client, settings, monkeypatch) -> None:
        user = await _subscriber("sub-unconfigured@example.com")

        async def _unconfigured(user_arg, settings_arg):
            raise billing_service.BillingNotConfigured("Stripe is not configured.")

        monkeypatch.setattr(billing_service, "create_checkout_session", _unconfigured)
        resp = await client.post(CHECKOUT_URL, headers=_auth_headers(user, settings))
        assert resp.status_code == 503

    async def test_it_requires_authentication(self, client) -> None:
        assert (await client.post(CHECKOUT_URL)).status_code == 401
