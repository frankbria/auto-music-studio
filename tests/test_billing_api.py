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


def _event(event_type: str, obj: dict, event_id: str = "evt_test_1", created: int | None = None) -> bytes:
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
            "created": created if created is not None else int(time.time()),
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


async def _post_event_at(client, event_type: str, obj: dict, event_id: str, created: int):
    """Post an event stamped at a specific time, to drive the out-of-order guard.

    The *signature* timestamp stays current — only the event's own ``created`` moves,
    which is exactly what Stripe does when it redelivers something generated an hour ago.
    """
    payload = _event(event_type, obj, event_id=event_id, created=created)
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
            {
                "customer": CUSTOMER,
                "subscription": "sub_test_1",
                "amount_due": 1000,
                "currency": "usd",
                "status": "open",
            },
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
            {"customer": CUSTOMER, "subscription": "sub_test_1", "amount_due": 1000, "currency": "usd"},
            event_id="evt_failed_2",
        )
        # Retries exhausted: Stripe moves the subscription itself to unpaid.
        await _post_event(client, "customer.subscription.updated", _subscription("unpaid"), event_id="evt_unpaid")

        refreshed = await User.get(user.id)
        assert refreshed.subscription_tier == "free"

    async def test_a_recovered_payment_clears_the_grace_flag(self, client) -> None:
        user = await _subscriber("sub-recovered@example.com")
        await _post_event(client, "checkout.session.completed", {"customer": CUSTOMER, "subscription": "sub_test_1"})
        await _post_event(
            client,
            "invoice.payment_failed",
            {"customer": CUSTOMER, "subscription": "sub_test_1"},
            event_id="evt_f3",
        )
        await _post_event(
            client,
            "invoice.paid",
            {
                "customer": CUSTOMER,
                "subscription": "sub_test_1",
                "amount_paid": 1000,
                "currency": "usd",
                "status": "paid",
            },
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
        await _post_event(client, "customer.subscription.updated", _subscription(), event_id="evt_noise_2")
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

    async def test_an_existing_subscriber_cannot_start_a_second_one(self, client, settings) -> None:
        # Raised in review on PR #420. A subscription-mode Checkout session creates a
        # NEW subscription against the customer — it does not update the existing one —
        # so a stale tab or a direct POST would leave the musician paying twice. This is
        # the only endpoint in the platform whose failure mode is charging someone money.
        user = await _subscriber("sub-double@example.com")
        await _post_event(
            client,
            "checkout.session.completed",
            {"customer": CUSTOMER, "subscription": "sub_test_1"},
            event_id="evt_double_1",
        )

        resp = await client.post(CHECKOUT_URL, headers=_auth_headers(user, settings))
        assert resp.status_code == 409
        assert "billing portal" in resp.json()["detail"]

    async def test_a_lapsed_subscriber_may_subscribe_again(self, client, settings, monkeypatch) -> None:
        # The guard must not strand someone whose subscription actually ended.
        user = await _subscriber("sub-lapsed@example.com")
        await _post_event(
            client,
            "customer.subscription.deleted",
            _subscription("canceled"),
            event_id="evt_lapsed",
        )

        async def _fake_session(user_arg, settings_arg):
            return "https://checkout.stripe.com/c/pay/again"

        monkeypatch.setattr(billing_service, "create_checkout_session", _fake_session)
        resp = await client.post(CHECKOUT_URL, headers=_auth_headers(user, settings))
        assert resp.status_code == 200


@pytest.mark.integration
class TestOutOfOrderDelivery:
    """Raised in review on PR #420. Stripe does not guarantee event ordering.

    Each delivery carries its own event id, so the idempotency guard cannot catch a
    late *older* snapshot — and an older snapshot overwriting a newer one downgrades a
    musician who is paying.
    """

    async def test_a_stale_snapshot_cannot_downgrade_a_paying_subscriber(self, client) -> None:
        user = await _subscriber("sub-ooo@example.com")
        await _post_event(
            client,
            "checkout.session.completed",
            {"customer": CUSTOMER, "subscription": "sub_test_1"},
            event_id="evt_ooo_checkout",
        )
        # A current snapshot lands and sets the sync watermark.
        now = int(time.time())
        await _post_event_at(client, "customer.subscription.updated", _subscription("active"), "evt_ooo_now", now)
        assert (await User.get(user.id)).subscription_tier == "pro"

        # An hour-old "incomplete" snapshot arrives late — the concrete case in review
        # was subscription.created while a 3DS card was still confirming.
        await _post_event_at(
            client,
            "customer.subscription.updated",
            _subscription("incomplete"),
            "evt_ooo_stale",
            now - 3600,
        )

        refreshed = await User.get(user.id)
        assert refreshed.subscription_tier == "pro", "a stale snapshot must not downgrade"
        assert refreshed.subscription_status == "active"

    async def test_a_newer_snapshot_still_applies(self, client) -> None:
        # The guard must not freeze the read-model — a genuine later downgrade still lands.
        user = await _subscriber("sub-ooo2@example.com")
        now = int(time.time())
        await _post_event_at(client, "customer.subscription.updated", _subscription("active"), "evt_ooo2_a", now - 60)
        await _post_event_at(client, "customer.subscription.updated", _subscription("unpaid"), "evt_ooo2_b", now)
        assert (await User.get(user.id)).subscription_tier == "free"

    async def test_subscription_created_is_not_handled(self, client) -> None:
        # checkout.session.completed grants access and updated/deleted carry every later
        # transition, so `created` is noise that only ever arrives with a status too
        # early to be meaningful.
        user = await _subscriber("sub-created@example.com")
        resp = await _post_event(
            client, "customer.subscription.created", _subscription("incomplete"), event_id="evt_created"
        )
        assert resp.json()["status"] == "ignored"
        assert (await User.get(user.id)).subscription_tier == "free"


@pytest.mark.integration
class TestChurnedSubscribers:
    """Raised in review on PR #420: a lapsed musician was permanently locked out.

    ``invoice.payment_failed`` used to set ``past_due`` unconditionally. That is a *paid*
    status, so a late failure for a long-dead subscription made the checkout guard refuse
    a free-tier account forever, waiting on a subscription event it would never generate
    again. Two changes: the guard keys on the entitlement rather than the mirrored
    status, and a failure for a non-subscriber no longer writes one.
    """

    async def test_a_late_failure_does_not_lock_out_a_lapsed_account(self, client, settings) -> None:
        user = await _subscriber("sub-churned@example.com")
        await _post_event(
            client,
            "checkout.session.completed",
            {"customer": CUSTOMER, "subscription": "sub_test_1"},
            event_id="evt_churn_1",
        )
        await _post_event(client, "customer.subscription.deleted", _subscription("canceled"), event_id="evt_churn_2")
        assert (await User.get(user.id)).subscription_tier == "free"

        # Stripe finally gives up on the last invoice, long after the subscription ended.
        await _post_event(
            client,
            "invoice.payment_failed",
            {"customer": CUSTOMER, "amount_due": 1200, "currency": "usd"},
            event_id="evt_churn_3",
        )

        refreshed = await User.get(user.id)
        assert refreshed.subscription_tier == "free"
        assert refreshed.subscription_status != "past_due", "a dead subscription must not look paid"

    async def test_a_lapsed_account_can_check_out_again(self, client, settings, monkeypatch) -> None:
        user = await _subscriber("sub-return@example.com")
        await _post_event(
            client,
            "checkout.session.completed",
            {"customer": CUSTOMER, "subscription": "sub_test_1"},
            event_id="evt_ret_1",
        )
        await _post_event(client, "customer.subscription.deleted", _subscription("canceled"), event_id="evt_ret_2")
        await _post_event(client, "invoice.payment_failed", {"customer": CUSTOMER}, event_id="evt_ret_3")

        async def _fake_session(user_arg, settings_arg):
            return "https://checkout.stripe.com/c/pay/welcome_back"

        monkeypatch.setattr(billing_service, "create_checkout_session", _fake_session)
        resp = await client.post(CHECKOUT_URL, headers=_auth_headers(user, settings))
        assert resp.status_code == 200, "a churned musician must be able to come back"


@pytest.mark.integration
class TestSupersededSubscriptionInvoices:
    """Raised in review on PR #420: invoice events were not correlated to a subscription.

    A musician who cancels and resubscribes keeps the same Stripe customer but gets a new
    subscription id. A delayed invoice event for the dead subscription was being applied
    to the live one — the sequence the earlier churn tests never reached, because they
    stopped at the resubscribe rather than continuing past it.
    """

    async def _resubscribed(self, client, email: str) -> User:
        user = await _subscriber(email)
        await _post_event(
            client,
            "checkout.session.completed",
            {"customer": CUSTOMER, "subscription": "sub_old"},
            event_id=f"{email}-1",
        )
        await _post_event(
            client,
            "customer.subscription.deleted",
            _subscription("canceled", id="sub_old"),
            event_id=f"{email}-2",
        )
        await _post_event(
            client,
            "checkout.session.completed",
            {"customer": CUSTOMER, "subscription": "sub_new"},
            event_id=f"{email}-3",
        )
        refreshed = await User.get(user.id)
        assert refreshed.stripe_subscription_id == "sub_new"
        return refreshed

    async def test_a_stale_failure_does_not_warn_about_a_healthy_subscription(self, client) -> None:
        user = await self._resubscribed(client, "sub-super-fail@example.com")

        await _post_event(
            client,
            "invoice.payment_failed",
            {"customer": CUSTOMER, "subscription": "sub_old", "amount_due": 1200, "currency": "usd"},
            event_id="evt_super_fail",
        )

        refreshed = await User.get(user.id)
        assert refreshed.subscription_status == "active", "the new subscription was never charged"
        assert refreshed.subscription_tier == "pro"

    async def test_a_stale_payment_does_not_clear_a_real_problem(self, client) -> None:
        # The mirror case, and the more dangerous one: telling a musician a genuine
        # payment failure is resolved when it is not.
        user = await self._resubscribed(client, "sub-super-paid@example.com")
        await _post_event(
            client,
            "invoice.payment_failed",
            {"customer": CUSTOMER, "subscription": "sub_new", "amount_due": 1200},
            event_id="evt_super_real_fail",
        )
        assert (await User.get(user.id)).subscription_status == "past_due"

        await _post_event(
            client,
            "invoice.paid",
            {"customer": CUSTOMER, "subscription": "sub_old", "amount_paid": 1200, "currency": "usd"},
            event_id="evt_super_stale_paid",
        )

        refreshed = await User.get(user.id)
        assert refreshed.subscription_status == "past_due", "a stale payment must not clear a real failure"

    async def test_a_paid_one_off_does_not_clear_a_real_payment_problem(self, client) -> None:
        # Raised in review on PR #420, before US-26.4 could walk into it. A credit top-up
        # is a one-off invoice with no `subscription`, so it fell past the identity check
        # into the status logic — and a successful top-up would clear a genuine past_due,
        # telling a musician their failing card is fine.
        user = await _subscriber("sub-topup-clears@example.com")
        await _post_event(
            client,
            "checkout.session.completed",
            {"customer": CUSTOMER, "subscription": "sub_test_1"},
            event_id="evt_topup_sub",
        )
        await _post_event(
            client,
            "invoice.payment_failed",
            {"customer": CUSTOMER, "subscription": "sub_test_1", "amount_due": 1200},
            event_id="evt_topup_fail",
        )
        assert (await User.get(user.id)).subscription_status == "past_due"

        # The musician buys a credit pack — unrelated to the subscription.
        await _post_event(
            client,
            "invoice.paid",
            {"customer": CUSTOMER, "amount_paid": 500, "currency": "usd", "status": "paid"},
            event_id="evt_topup_paid",
        )

        refreshed = await User.get(user.id)
        assert refreshed.subscription_status == "past_due", "a top-up says nothing about the card on file"

    async def test_a_failed_one_off_does_not_flag_a_healthy_subscription(self, client) -> None:
        user = await _subscriber("sub-topup-fails@example.com")
        await _post_event(
            client,
            "checkout.session.completed",
            {"customer": CUSTOMER, "subscription": "sub_test_1"},
            event_id="evt_topup2_sub",
        )

        await _post_event(
            client,
            "invoice.payment_failed",
            {"customer": CUSTOMER, "amount_due": 500, "currency": "usd"},
            event_id="evt_topup2_fail",
        )

        refreshed = await User.get(user.id)
        assert refreshed.subscription_status == "active", "a declined credit pack is not a subscription problem"
        assert refreshed.subscription_tier == "pro"

    async def test_a_one_off_charge_still_applies(self, client, settings) -> None:
        # An invoice with no `subscription` is a one-off (credit top-ups, US-26.4). It is
        # not about the subscription, so the correlation check must not swallow it.
        user = await _subscriber("sub-oneoff@example.com")
        await _post_event(
            client,
            "invoice.paid",
            {"customer": CUSTOMER, "amount_paid": 500, "currency": "usd", "status": "paid"},
            event_id="evt_oneoff",
        )

        entries = (await client.get(HISTORY_URL, headers=_auth_headers(user, settings))).json()["entries"]
        assert len(entries) == 1 and entries[0]["amount"] == 5.0


@pytest.mark.integration
class TestOrderingWatermarkArmedAtCheckout:
    """Raised in review on PR #420: the ordering guard was a no-op for the first event.

    ``_handle_checkout_completed`` granted Pro without stamping ``subscription_synced_at``,
    so the first subscription event was compared against ``None`` and let through whatever
    its timestamp said — leaving unguarded exactly the window in which someone has just paid.
    """

    async def test_a_replayed_checkout_cannot_resurrect_a_cancelled_subscription(self, client) -> None:
        # Raised in review on PR #420, and a regression from this PR's own crash-safety
        # reorder: the checkout handler stamped the watermark without reading it back,
        # so it was the one place the ordering guard did not protect — and the one place
        # that grants Pro. A redelivery (or an operator clicking "Resend" in the Stripe
        # dashboard) of an old checkout event re-granted Pro to a musician who had since
        # cancelled, then reported "duplicate" as though nothing had happened.
        user = await _subscriber("sub-replay@example.com")
        now = int(time.time())
        await _post_event_at(
            client,
            "checkout.session.completed",
            {"customer": CUSTOMER, "subscription": "sub_test_1"},
            "evt_replay_checkout",
            now - 600,
        )
        await _post_event_at(
            client,
            "customer.subscription.deleted",
            _subscription("canceled"),
            "evt_replay_deleted",
            now,
        )
        assert (await User.get(user.id)).subscription_tier == "free"

        # Stripe resends the original checkout event.
        resp = await _post_event_at(
            client,
            "checkout.session.completed",
            {"customer": CUSTOMER, "subscription": "sub_test_1"},
            "evt_replay_checkout",
            now - 600,
        )

        assert resp.status_code == 200
        assert (
            await User.get(user.id)
        ).subscription_tier == "free", "a cancelled musician must not come back on Pro for free"

    async def test_a_snapshot_older_than_the_checkout_cannot_undo_it(self, client) -> None:
        user = await _subscriber("sub-watermark@example.com")
        now = int(time.time())
        await _post_event_at(
            client,
            "checkout.session.completed",
            {"customer": CUSTOMER, "subscription": "sub_test_1"},
            "evt_wm_checkout",
            now,
        )
        assert (await User.get(user.id)).subscription_tier == "pro"

        # An "incomplete" snapshot generated before the checkout completed, arriving after.
        await _post_event_at(
            client,
            "customer.subscription.updated",
            _subscription("incomplete"),
            "evt_wm_stale",
            now - 120,
        )

        assert (await User.get(user.id)).subscription_tier == "pro"


@pytest.mark.integration
class TestInvoiceOrdering:
    """Raised in review on PR #420 and tracked across commits until closed here.

    The correlation check catches an invoice for a *different* subscription; this catches
    reordering **within** the current one. The tier is unaffected either way — only
    subscription events move the entitlement — so this is a misleading banner rather than
    a money bug, but a banner telling someone to fix a card that is fine is still wrong.
    """

    async def _pro(self, client, email: str, at: int | None = None) -> User:
        """A subscribed user. ``at`` stamps the *subscription* watermark, which callers
        below need to control — a checkout stamped "now" would legitimately make any
        later-posted-but-earlier subscription event stale, for reasons unrelated to the
        invoice watermark under test."""
        user = await _subscriber(email)
        payload = {"customer": CUSTOMER, "subscription": "sub_test_1"}
        if at is None:
            await _post_event(client, "checkout.session.completed", payload, event_id=f"{email}-sub")
        else:
            await _post_event_at(client, "checkout.session.completed", payload, f"{email}-sub", at)
        return await User.get(user.id)

    async def test_a_late_failure_does_not_reopen_a_settled_grace_period(self, client) -> None:
        user = await self._pro(client, "sub-invord@example.com")
        now = int(time.time())

        await _post_event_at(
            client,
            "invoice.paid",
            {"customer": CUSTOMER, "subscription": "sub_test_1", "amount_paid": 1200, "currency": "usd"},
            "evt_invord_paid",
            now,
        )
        # The failed attempt that preceded that payment, arriving late.
        await _post_event_at(
            client,
            "invoice.payment_failed",
            {"customer": CUSTOMER, "subscription": "sub_test_1", "amount_due": 1200},
            "evt_invord_failed",
            now - 300,
        )

        refreshed = await User.get(user.id)
        assert refreshed.subscription_status == "active", "the card was charged; do not ask them to fix it"

    async def test_a_genuinely_newer_failure_still_applies(self, client) -> None:
        # The guard must not deafen us to a real problem.
        user = await self._pro(client, "sub-invord2@example.com")
        now = int(time.time())
        await _post_event_at(
            client,
            "invoice.paid",
            {"customer": CUSTOMER, "subscription": "sub_test_1", "amount_paid": 1200},
            "evt_invord2_paid",
            now - 300,
        )
        await _post_event_at(
            client,
            "invoice.payment_failed",
            {"customer": CUSTOMER, "subscription": "sub_test_1", "amount_due": 1200},
            "evt_invord2_failed",
            now,
        )
        assert (await User.get(user.id)).subscription_status == "past_due"

    async def test_the_invoice_watermark_does_not_block_subscription_events(self, client) -> None:
        # The reason the two watermarks are separate. A shared one would let this invoice
        # advance it and then drop the subscription event stamped a moment earlier —
        # trading a cosmetic bug for an entitlement one.
        now = int(time.time())
        user = await self._pro(client, "sub-invord3@example.com", at=now - 600)
        await _post_event_at(
            client,
            "invoice.paid",
            {"customer": CUSTOMER, "subscription": "sub_test_1", "amount_paid": 1200},
            "evt_invord3_paid",
            now,
        )
        await _post_event_at(
            client,
            "customer.subscription.deleted",
            _subscription("canceled"),
            "evt_invord3_deleted",
            now - 10,
        )
        assert (await User.get(user.id)).subscription_tier == "free", "the cancellation must still land"


@pytest.mark.integration
class TestInvoiceAmounts:
    async def test_a_fully_discounted_invoice_shows_zero_not_the_list_price(self, client, settings) -> None:
        # Raised in review on PR #420: `amount_paid or amount_due` evaluates 0 as falsy,
        # so a 100%-coupon invoice displayed the pre-discount figure as though it had
        # been charged.
        user = await _subscriber("sub-free-month@example.com")
        await _post_event(
            client,
            "invoice.paid",
            {
                "customer": CUSTOMER,
                "amount_paid": 0,
                "amount_due": 1200,
                "currency": "usd",
                "status": "paid",
                "description": "Pro monthly (100% coupon)",
            },
            event_id="evt_zero",
        )

        entries = (await client.get(HISTORY_URL, headers=_auth_headers(user, settings))).json()["entries"]
        assert len(entries) == 1
        assert entries[0]["amount"] == 0.0, "a free month must not read as a $12 charge"

    async def test_payment_succeeded_does_not_double_record_a_paid_invoice(self, client, settings) -> None:
        # Raised in review on PR #420: Stripe fires both invoice.paid and
        # invoice.payment_succeeded for the same successful invoice, with different
        # event ids — so idempotency on the event id alone would not dedupe them, and
        # the musician would see the same charge twice.
        user = await _subscriber("sub-twoevents@example.com")
        body = {"customer": CUSTOMER, "amount_paid": 1200, "currency": "usd", "status": "paid"}
        await _post_event(client, "invoice.paid", body, event_id="evt_dbl_paid")
        await _post_event(client, "invoice.payment_succeeded", body, event_id="evt_dbl_succeeded")

        entries = (await client.get(HISTORY_URL, headers=_auth_headers(user, settings))).json()["entries"]
        assert len(entries) == 1, "one charge, one row"


@pytest.mark.integration
class TestWebhookCrashSafety:
    """Raised in review on PR #420: recording the event before applying it loses updates.

    If the idempotency row were written first and the process died before the user was
    saved, Stripe's redelivery would hit the unique index, report "duplicate", and skip
    an entitlement change that never happened — a musician who paid and stayed free.

    The state change now goes first. That is safe because every one of them is
    idempotent, while the ledger insert is the thing that must happen at most once.
    """

    async def test_a_redelivery_repairs_a_half_applied_event(self, client) -> None:
        user = await _subscriber("sub-crash@example.com")

        # Simulate the crash window directly: the event is on record, but the user was
        # never updated — exactly the state the old ordering could leave behind.
        await BillingEvent(
            user_id=user.id,
            stripe_event_id="evt_crash",
            event_type="checkout.session.completed",
        ).insert()
        assert (await User.get(user.id)).subscription_tier == "free"

        await _post_event(
            client,
            "checkout.session.completed",
            {"customer": CUSTOMER, "subscription": "sub_test_1"},
            event_id="evt_crash",
        )

        # The redelivery applies the change before it discovers the duplicate, so the
        # musician ends up with what they paid for instead of silently staying free.
        assert (await User.get(user.id)).subscription_tier == "pro"
        assert await BillingEvent.find(BillingEvent.user_id == user.id).count() == 1


@pytest.mark.integration
class TestCreditTopUp:
    """US-26.4 AC1: buying a pack credits the account, exactly once.

    A grant is *not* naturally idempotent the way a tier flip is — crediting twice is a
    real gift — so these lean hard on the redelivery cases.
    """

    async def test_a_paid_pack_grants_its_credits(self, client) -> None:
        user = await _subscriber("topup-grant@example.com")
        before = (await User.get(user.id)).purchased_credits

        resp = await _post_event(
            client,
            "checkout.session.completed",
            {
                "customer": CUSTOMER,
                "metadata": {billing_service.PACK_METADATA_KEY: "100", "user_id": str(user.id)},
            },
            event_id="evt_topup_100",
        )

        assert resp.json()["status"] == "topped_up"
        assert (await User.get(user.id)).purchased_credits == before + 100.0

    async def test_a_top_up_does_not_grant_pro(self, client) -> None:
        # The most expensive possible way to misread a webhook: a credit pack rides the
        # same event type as a subscription checkout, and only the metadata tells them
        # apart. Falling through would hand out Pro for the price of 50 credits.
        user = await _subscriber("topup-nopro@example.com")

        await _post_event(
            client,
            "checkout.session.completed",
            {"customer": CUSTOMER, "metadata": {billing_service.PACK_METADATA_KEY: "50"}},
            event_id="evt_topup_nopro",
        )

        refreshed = await User.get(user.id)
        assert refreshed.subscription_tier == "free"
        assert refreshed.purchased_credits == 50.0

    async def test_a_redelivered_top_up_credits_once(self, client) -> None:
        user = await _subscriber("topup-dupe@example.com")
        body = {"customer": CUSTOMER, "metadata": {billing_service.PACK_METADATA_KEY: "50"}}

        await _post_event(client, "checkout.session.completed", body, event_id="evt_topup_same")
        second = await _post_event(client, "checkout.session.completed", body, event_id="evt_topup_same")

        assert second.json()["status"] == "duplicate"
        assert (await User.get(user.id)).purchased_credits == 50.0, "a redelivery is not a second sale"

    async def test_a_redelivery_completes_a_grant_that_never_landed(self, client) -> None:
        # Raised in review on PR #422. Recording before granting is what stops a
        # redelivery double-crediting — but on its own it means a crash between the two
        # leaves the musician charged with no credits, permanently, because the next
        # delivery sees the row and reports "duplicate". The row now carries a settled
        # marker so a redelivery can tell "done" from "started and abandoned".
        user = await _subscriber("topup-repair@example.com")
        await BillingEvent(
            user_id=user.id,
            stripe_event_id="evt_topup_crash",
            event_type="checkout.session.completed",
        ).insert()
        assert (await User.get(user.id)).purchased_credits == 0.0

        resp = await _post_event(
            client,
            "checkout.session.completed",
            {"customer": CUSTOMER, "metadata": {billing_service.PACK_METADATA_KEY: "250"}},
            event_id="evt_topup_crash",
        )

        assert resp.json()["status"] == "repaired"
        assert (await User.get(user.id)).purchased_credits == 250.0

    async def test_a_settled_grant_is_not_repeated_by_the_repair_path(self, client) -> None:
        # The repair must not become a second way to double-credit.
        user = await _subscriber("topup-settled@example.com")
        body = {"customer": CUSTOMER, "metadata": {billing_service.PACK_METADATA_KEY: "50"}}
        await _post_event(client, "checkout.session.completed", body, event_id="evt_settled")
        await _post_event(client, "checkout.session.completed", body, event_id="evt_settled")
        await _post_event(client, "checkout.session.completed", body, event_id="evt_settled")

        assert (await User.get(user.id)).purchased_credits == 50.0

    async def test_an_unknown_pack_grants_nothing(self, client) -> None:
        # A pack id that no longer exists (renamed, retired) must not guess an amount.
        user = await _subscriber("topup-unknown@example.com")

        resp = await _post_event(
            client,
            "checkout.session.completed",
            {"customer": CUSTOMER, "metadata": {billing_service.PACK_METADATA_KEY: "9999"}},
            event_id="evt_topup_unknown",
        )

        assert resp.json()["status"] == "unknown_pack"
        assert (await User.get(user.id)).purchased_credits == 0.0

    async def test_a_subscription_checkout_still_grants_pro(self, client) -> None:
        # The negative control for the metadata branch: no pack means the old path.
        user = await _subscriber("topup-control@example.com")
        await _post_event(
            client,
            "checkout.session.completed",
            {"customer": CUSTOMER, "subscription": "sub_test_1"},
            event_id="evt_topup_control",
        )
        refreshed = await User.get(user.id)
        assert refreshed.subscription_tier == "pro"
        assert refreshed.purchased_credits == 0.0


@pytest.mark.integration
class TestPacksEndpoint:
    async def test_it_lists_the_packs_with_prices(self, client, settings) -> None:
        user = await _subscriber("topup-packs@example.com")
        resp = await client.get(f"{API_V1_PREFIX}/billing/packs", headers=_auth_headers(user, settings))

        packs = {p["id"]: p for p in resp.json()["packs"]}
        assert packs["50"]["credits"] == 50.0 and packs["50"]["price"] == 5.00
        assert packs["100"]["price"] == 9.00
        assert packs["250"]["price"] == 20.00

    async def test_an_unknown_pack_is_a_400(self, client, settings) -> None:
        user = await _subscriber("topup-badpack@example.com")
        resp = await client.post(
            f"{API_V1_PREFIX}/billing/topup",
            json={"pack_id": "not-a-pack"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 400

    async def test_topup_requires_authentication(self, client) -> None:
        assert (await client.post(f"{API_V1_PREFIX}/billing/topup", json={"pack_id": "50"})).status_code == 401
