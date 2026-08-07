"""Subscription billing via Stripe (US-26.3).

**Stripe is the system of record; the user document is a read-model of it.** Every
tier check in the app reads ``user.subscription_tier``, and that read happens on nearly
every request — the sidebar polls balance and tier on each page. Asking Stripe for the
answer would put a network call in the hottest path in the platform, so instead the
webhook handler writes Stripe's answer onto the user and the reads stay local.

That choice is what makes two of the acceptance criteria fall out rather than needing
machinery:

- **Cancelling keeps Pro until the period ends (AC2).** Stripe leaves the subscription
  ``active`` with ``cancel_at_period_end`` set until the period actually elapses, then
  sends ``customer.subscription.deleted``. Nothing here has to notice an expiry date —
  no scheduler, no nightly sweep.
- **A failed payment gets a grace period (AC3).** ``past_due`` maps to Pro, so the
  musician keeps what they paid for while Stripe's retry schedule runs. Only the
  terminal states downgrade. Re-implementing dunning here would be a second retry clock
  that could disagree with the one actually charging the card.

Like the other service modules this raises plain exceptions, never ``HTTPException``.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

import stripe

from ..models import BillingEvent, User
from ..settings import ApiSettings
from . import tiers

logger = logging.getLogger(__name__)


class BillingNotConfigured(RuntimeError):
    """Stripe credentials are absent, so billing cannot be used."""


class BillingError(RuntimeError):
    """Stripe rejected a request, or returned something unusable."""


class AlreadySubscribed(RuntimeError):
    """This account already has a live subscription, so a second checkout would double-bill."""


#: Statuses the musician has effectively paid for.
#:
#: ``past_due`` is here on purpose and is the whole of AC3: the first charge failed and
#: Stripe is retrying, which is not the same as refusing to pay. ``unpaid`` is Stripe's
#: state *after* the retries are exhausted, and that one downgrades.
PAID_STATUSES = frozenset({"active", "trialing", "past_due"})


def tier_for_status(status: str | None) -> str:
    """The tier a subscription in ``status`` is worth.

    Fails closed, matching :func:`tiers.normalise`: a status this code has never heard
    of yields the free tier. Stripe can add statuses without asking us, and the safe
    reading of an unknown one is "not paid".
    """
    return tiers.PRO if status in PAID_STATUSES else tiers.FREE


def _timestamp(value: Any) -> datetime | None:
    """A Stripe unix timestamp as an aware datetime, or ``None``.

    Tolerant by design. A malformed or missing timestamp must not raise: this runs
    inside the webhook handler, and an exception there is a non-2xx, which makes Stripe
    redeliver the event on a schedule that will not fix bad data.
    """
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        logger.warning("billing: unusable timestamp %r", value)
        return None


def _as_utc(value: datetime | None) -> datetime | None:
    """Make a stored datetime comparable with a fresh one.

    MongoDB hands back naive datetimes, and comparing naive with aware raises. Same
    normalisation ``credits.apply_monthly_reset`` already does for ``created_at``.
    """
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def subscription_fields(subscription: dict[str, Any]) -> dict[str, Any]:
    """Map a Stripe subscription object onto the user fields that mirror it.

    Returned as a plain dict rather than applied in place so the mapping stays pure and
    testable without a database — it is the part that decides who has Pro, so it is the
    part worth testing hardest.
    """
    status = subscription.get("status")
    return {
        "stripe_subscription_id": subscription.get("id"),
        "subscription_status": status,
        "subscription_tier": tier_for_status(status),
        "subscription_current_period_end": _timestamp(subscription.get("current_period_end")),
        "subscription_cancel_at_period_end": bool(subscription.get("cancel_at_period_end")),
    }


def _client(settings: ApiSettings) -> stripe.StripeClient:
    """A configured Stripe client, or a clear refusal.

    The seam every outbound call goes through, so tests can substitute it and a
    Stripe-less deployment gets one obvious error instead of an ``AuthenticationError``
    from deep inside the SDK.
    """
    if not settings.stripe_enabled:
        raise BillingNotConfigured(
            "Stripe is not configured. Set ACEMUSIC_API_STRIPE_SECRET_KEY, "
            "ACEMUSIC_API_STRIPE_WEBHOOK_SECRET and ACEMUSIC_API_STRIPE_PRICE_ID_PRO."
        )
    return stripe.StripeClient(settings.stripe_secret_key)


async def ensure_customer(user: User, settings: ApiSettings) -> str:
    """This user's Stripe customer id, creating one on first use.

    Persisted on the user so a musician never ends up with two customer records — which
    would split their billing history in Stripe's dashboard and make a refund land on
    the wrong one.
    """
    if user.stripe_customer_id:
        return user.stripe_customer_id

    client = _client(settings)
    # ``idempotency_key`` is what actually makes this race-safe. Two concurrent checkout
    # clicks (two tabs, a double-click) both reach here with no customer id; without the
    # key each would create a *different* Stripe customer, and the loser's checkout would
    # complete against an orphaned customer that no webhook could map back to a user — a
    # musician who paid and stayed free. With it, Stripe returns the same customer to
    # both. Raised in review on PR #420.
    #
    # ``to_thread`` because the Stripe SDK is synchronous: called directly it would block
    # the event loop for the whole round-trip, stalling every other request.
    customer = await asyncio.to_thread(
        lambda: client.customers.create(
            params={
                "email": user.email,
                "name": user.display_name or user.name,
                # Lets an operator go from a Stripe dashboard row back to a platform
                # user without a lookup table.
                "metadata": {"user_id": str(user.id)},
            },
            options={"idempotency_key": f"acemusic-customer-{user.id}"},
        )
    )
    user.stripe_customer_id = customer.id
    await user.save()
    return customer.id


async def create_checkout_session(user: User, settings: ApiSettings) -> str:
    """Start a Pro subscription; returns the URL to send the musician to.

    The tier is *not* granted here. It is granted when
    ``checkout.session.completed`` arrives, because a session that is created is not a
    session that is paid — a musician who reaches the Stripe page and closes the tab
    must not come back to Pro.

    Refuses outright if the account already has a live subscription. A subscription-mode
    Checkout session creates a **new** subscription against the customer; it does not
    update the existing one, so a stale tab or a direct POST would leave the musician
    paying twice. Changing an existing plan is the portal's job, and this is the only
    place in the platform that can cause a double charge.
    """
    # Keyed on the **effective tier**, not on ``subscription_status``. Raised in review
    # on PR #420: a late ``invoice.payment_failed`` for a long-dead subscription sets
    # ``past_due``, which is a paid status — so a status-keyed guard would refuse a
    # churned musician checkout forever, waiting on a subscription event they will never
    # generate again. The tier is what they actually have, and it is what may not be
    # paid for twice.
    if user.stripe_subscription_id and tiers.normalise(user.subscription_tier) == tiers.PRO:
        raise AlreadySubscribed(
            "This account already has an active subscription. Use the billing portal to change or cancel it."
        )

    customer_id = await ensure_customer(user, settings)
    client = _client(settings)
    session = await asyncio.to_thread(
        lambda: client.checkout.sessions.create(
            params={
                "mode": "subscription",
                "customer": customer_id,
                "line_items": [{"price": settings.stripe_price_id_pro, "quantity": 1}],
                "success_url": settings.stripe_success_url,
                "cancel_url": settings.stripe_cancel_url,
                # Lets an operator trace a Stripe subscription back to a platform user.
                # Proration on a *plan change* is the portal's job — this path only ever
                # creates a first subscription, per the guard above.
                "subscription_data": {"metadata": {"user_id": str(user.id)}},
            }
        )
    )
    if not session.url:
        raise BillingError("Stripe returned a checkout session with no URL.")
    return session.url


async def create_portal_session(user: User, settings: ApiSettings, return_url: str | None = None) -> str:
    """A Stripe Billing Portal URL: update card, cancel, view invoices.

    Deliberately not rebuilt in our own UI. Card details would drag this platform into
    PCI scope, and cancellation/proration rules are Stripe's to enforce — a hand-rolled
    version of either is a liability, not a feature.
    """
    if not user.stripe_customer_id:
        raise BillingError("This account has no billing profile yet — subscribe first.")

    client = _client(settings)
    session = await asyncio.to_thread(
        lambda: client.billing_portal.sessions.create(
            params={
                "customer": user.stripe_customer_id,
                "return_url": return_url or settings.stripe_success_url,
            }
        )
    )
    if not session.url:
        raise BillingError("Stripe returned a portal session with no URL.")
    return session.url


def verify_webhook(payload: bytes, signature: str | None, settings: ApiSettings) -> dict[str, Any]:
    """Parse and authenticate a webhook delivery.

    Uses the SDK's ``construct_event`` rather than a hand-rolled HMAC: it does a
    constant-time comparison and enforces a timestamp tolerance, which is what stops a
    captured request being replayed later. This endpoint mutates subscription tiers
    while unauthenticated, so it is the one place in the codebase not to be inventive.
    """
    if not settings.stripe_webhook_secret:
        raise BillingNotConfigured("Stripe webhook secret is not configured.")
    if not signature:
        raise BillingError("Missing Stripe-Signature header.")
    try:
        stripe.Webhook.construct_event(payload, signature, settings.stripe_webhook_secret)
    except ValueError as exc:
        raise BillingError("Malformed webhook payload.") from exc
    except stripe.SignatureVerificationError as exc:
        raise BillingError("Webhook signature verification failed.") from exc

    # Re-parse the (now authenticated) bytes into plain dicts rather than handing the
    # SDK's StripeObject around: it is not a plain mapping — ``dict()`` on it raises —
    # and every handler below wants ordinary ``.get()`` semantics. One extra parse of a
    # small body is cheaper than coupling the state machine to the SDK's object model.
    return json.loads(payload)


def _is_stale(user: User, occurred_at: datetime | None) -> bool:
    """Whether this event predates the state already applied for ``user``.

    Stripe does not guarantee ordering, and every handler here applies its state change
    *before* the idempotency row is written (so a crash between the two cannot lose an
    entitlement). That ordering is only safe while each mutation is idempotent **with
    respect to newer state** — which is what this check provides. Used by every handler
    that stamps ``subscription_synced_at``, including the one that grants Pro.
    """
    last_sync = _as_utc(user.subscription_synced_at)
    return bool(occurred_at and last_sync and occurred_at < last_sync)


async def _user_for_customer(customer_id: str | None) -> User | None:
    if not customer_id:
        return None
    return await User.find_one(User.stripe_customer_id == customer_id)


async def _record_event(
    user: User,
    event_id: str,
    event_type: str,
    invoice: dict[str, Any] | None = None,
) -> bool:
    """Append one billing-history row. False if this event was already recorded.

    The unique index on ``stripe_event_id`` is the idempotency guard — Stripe's delivery
    contract is at-least-once, so a duplicate is expected traffic, not an error worth
    logging loudly.

    **Called after the state change, never before.** Recording first would open a window
    where a crash between the insert and ``user.save()`` loses the entitlement change
    permanently: the redelivery would hit the unique index, report "duplicate", and skip
    the mutation that never happened. Applying first is safe because every state change
    here is idempotent — setting the tier to pro twice is setting it once — while this
    insert is the thing that must happen at most once. (A transaction would also work,
    but needs a replica set, which a single-node deployment does not have.)
    """
    invoice = invoice or {}
    try:
        await BillingEvent(
            user_id=user.id,
            stripe_event_id=event_id,
            event_type=event_type,
            # Explicit None check, not ``or``: a fully-discounted invoice has
            # ``amount_paid == 0``, and ``0 or amount_due`` would show the pre-discount
            # figure as though it had been charged. Raised in review on PR #420.
            amount_cents=(
                invoice["amount_paid"] if invoice.get("amount_paid") is not None else invoice.get("amount_due")
            ),
            currency=invoice.get("currency"),
            status=invoice.get("status"),
            description=invoice.get("description") or event_type,
            invoice_url=invoice.get("hosted_invoice_url"),
        ).insert()
    except Exception as exc:  # duplicate key -> already handled
        if "duplicate key" in str(exc).lower() or "E11000" in str(exc):
            logger.info("billing: event %s already recorded, skipping", event_id)
            return False
        raise
    return True


async def handle_event(event: dict[str, Any]) -> str:
    """Apply one verified Stripe event. Returns a short outcome for logging/tests.

    Unknown event types are *ignored*, not rejected: Stripe sends whatever the endpoint
    is subscribed to plus anything added later, and a 4xx on an event we simply do not
    care about would put it into a retry loop forever.
    """
    event_id = event.get("id") or ""
    event_type = event.get("type") or ""
    obj = (event.get("data") or {}).get("object") or {}
    # Stripe stamps every event; used below to reject a stale one that arrives late.
    occurred_at = _timestamp(event.get("created"))

    if event_type == "checkout.session.completed":
        return await _handle_checkout_completed(event_id, event_type, obj, occurred_at)
    if event_type in ("customer.subscription.updated", "customer.subscription.deleted"):
        return await _handle_subscription_change(event_id, event_type, obj, occurred_at)
    if event_type in ("invoice.paid", "invoice.payment_failed"):
        return await _handle_invoice(event_id, event_type, obj)

    logger.info("billing: ignoring unhandled event type %s", event_type)
    return "ignored"


async def _handle_checkout_completed(
    event_id: str,
    event_type: str,
    session: dict[str, Any],
    occurred_at: datetime | None = None,
) -> str:
    """Checkout paid — link the subscription and grant Pro (AC1).

    Stamps the ordering watermark as well. Raised in review on PR #420: without it the
    guard in :func:`_handle_subscription_change` compares the first subscription event
    against ``None`` and lets it through whatever its timestamp says — so an
    ``incomplete`` snapshot generated *before* this checkout could still land after it
    and undo the grant. The window it protects is precisely the one where a musician has
    just paid.
    """
    user = await _user_for_customer(session.get("customer"))
    if user is None:
        logger.warning("billing: checkout for unknown customer %r", session.get("customer"))
        return "unknown_customer"

    # Raised in review on PR #420. This handler stamped the watermark without reading it
    # back, which made it the one place the ordering guard did not protect — and the one
    # place that *grants* Pro. Because the state change deliberately runs before the
    # idempotency row is written, a Stripe redelivery (or an operator clicking "Resend"
    # in the dashboard) of an old checkout event would re-grant Pro to a musician who had
    # since cancelled, then report "duplicate" as though nothing had happened.
    if _is_stale(user, occurred_at):
        logger.info("billing: dropping superseded checkout event for %s", user.id)
        if not await _record_event(user, event_id, event_type):
            return "duplicate"
        return "stale"

    user.stripe_subscription_id = session.get("subscription") or user.stripe_subscription_id
    user.subscription_tier = tiers.PRO
    user.subscription_status = "active"
    user.subscription_cancel_at_period_end = False
    if occurred_at:
        user.subscription_synced_at = occurred_at
    await user.save()

    if not await _record_event(user, event_id, event_type):
        return "duplicate"
    return "subscribed"


async def _handle_subscription_change(
    event_id: str,
    event_type: str,
    subscription: dict[str, Any],
    occurred_at: datetime | None = None,
) -> str:
    """Mirror a subscription's current state, including its end (AC2) and downgrade.

    **Stripe does not guarantee event ordering.** A redelivery or a slow first delivery
    can land an *older* snapshot after a newer one, and since each carries its own event
    id the idempotency guard does not catch it — so a stale ``incomplete`` or
    ``past_due`` snapshot could overwrite a subscription that is now active and
    downgrade a paying musician. The guard below drops anything older than the last
    snapshot applied.

    Raised in review on PR #420, where the concrete case was
    ``customer.subscription.created`` (status ``incomplete`` while a 3DS card is
    confirming) arriving after Pro had already been granted. That event type is no
    longer handled at all — ``checkout.session.completed`` grants access and
    ``updated``/``deleted`` carry every subsequent transition — but the ordering problem
    is general, so it is fixed generally rather than by removing the one messenger.
    """
    user = await _user_for_customer(subscription.get("customer"))
    if user is None:
        logger.warning("billing: subscription event for unknown customer %r", subscription.get("customer"))
        return "unknown_customer"

    if _is_stale(user, occurred_at):
        logger.info(
            "billing: dropping out-of-order %s (%s older than last sync %s)",
            event_type,
            occurred_at,
            user.subscription_synced_at,
        )
        return "stale"

    fields = subscription_fields(subscription)
    if occurred_at:
        fields["subscription_synced_at"] = occurred_at
    if event_type == "customer.subscription.deleted":
        # Deletion is terminal whatever the payload's status says — the subscription is
        # gone, so the entitlement is too.
        fields["subscription_tier"] = tiers.FREE
        fields["subscription_status"] = "canceled"

    for key, value in fields.items():
        setattr(user, key, value)
    await user.save()

    if not await _record_event(user, event_id, event_type):
        return "duplicate"
    return fields["subscription_tier"]


async def _handle_invoice(event_id: str, event_type: str, invoice: dict[str, Any]) -> str:
    """Record a charge (AC4); mark the grace period on failure (AC3).

    A failure does **not** touch the tier. Stripe drives the downgrade through the
    subscription's own lifecycle once its retries are exhausted, and that is the only
    place the entitlement should move.
    """
    user = await _user_for_customer(invoice.get("customer"))
    if user is None:
        logger.warning("billing: invoice for unknown customer %r", invoice.get("customer"))
        return "unknown_customer"

    # Identity check, not just a tier check. Raised in review on PR #420: a customer who
    # cancels and later resubscribes keeps the same Stripe customer but gets a NEW
    # subscription id, so a delayed invoice event for the dead one would otherwise be
    # applied to the live one — a false "we couldn't take your last payment" on a
    # subscription that was never charged, or worse, a late ``invoice.paid`` clearing a
    # *genuine* past_due and telling the musician a real problem is resolved.
    #
    # The ``subscription_synced_at`` watermark closes this for subscription events;
    # invoices carry their own identity, so they get compared rather than timestamped.
    # An invoice with no ``subscription`` is a one-off charge (credit top-ups, US-26.4)
    # and is not about the subscription at all, so it passes through.
    invoice_subscription = invoice.get("subscription")
    if invoice_subscription and user.stripe_subscription_id and invoice_subscription != user.stripe_subscription_id:
        logger.info(
            "billing: invoice for superseded subscription %s (current %s) — recorded, not applied",
            invoice_subscription,
            user.stripe_subscription_id,
        )
        if not await _record_event(user, event_id, event_type, invoice=invoice):
            return "duplicate"
        return "superseded"

    if event_type == "invoice.payment_failed":
        # Only meaningful for someone who currently *has* the entitlement. A late failure
        # for a subscription that already ended must not resurrect a paid-looking status
        # on a free account — that is the state that used to lock them out of
        # resubscribing (see the guard in create_checkout_session).
        if tiers.normalise(user.subscription_tier) != tiers.PRO:
            logger.info("billing: ignoring payment failure for a non-subscriber %s", user.id)
            if not await _record_event(user, event_id, event_type, invoice=invoice):
                return "duplicate"
            return "not_subscribed"

        user.subscription_status = "past_due"
        await user.save()
        if not await _record_event(user, event_id, event_type, invoice=invoice):
            return "duplicate"
        return "past_due"

    # A successful charge clears a grace period that a previous failure set.
    if user.subscription_status == "past_due":
        user.subscription_status = "active"
        await user.save()

    if not await _record_event(user, event_id, event_type, invoice=invoice):
        return "duplicate"
    return "paid"
