"""Billing event document model (US-26.3).

Two jobs in one append-only collection:

1. **Billing history** (AC4) — every charge, with its date, amount and status, served
   from ``GET /billing/history``. Written from Stripe invoice events rather than from
   our own bookkeeping, so what the musician sees matches what their card was actually
   charged.
2. **Webhook idempotency** — ``stripe_event_id`` is uniquely indexed. Stripe redelivers
   events on any non-2xx, and at-least-once delivery is its documented contract, so a
   handler that is not idempotent will eventually double-apply one. The insert is the
   guard: a duplicate raises on the index rather than replaying the effect.

Modelled on :class:`~acemusic.api.models.credit_transaction.CreditTransaction` — the
other append-only ledger here — down to the ``(user_id, created_at)`` history index.
"""

from datetime import datetime

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, DESCENDING, IndexModel

from .common import utcnow


class BillingEvent(Document):
    """One Stripe event that mattered to a user's billing."""

    user_id: PydanticObjectId
    #: Stripe's event id (``evt_...``). Unique — see the idempotency note above.
    stripe_event_id: str
    #: Stripe event type, e.g. ``invoice.paid``.
    event_type: str
    #: Charge amount in the currency's minor unit (cents), exactly as Stripe reports
    #: it. Kept as an int on purpose: money in floats accumulates error, and every
    #: display is a division by 100 at the edge. ``None`` for events that are not a
    #: charge (a plain subscription update).
    amount_cents: int | None = None
    currency: str | None = None
    #: Stripe's own status for the invoice (``paid``, ``open``, ``void``…).
    status: str | None = None
    description: str | None = None
    #: Stripe-hosted invoice PDF/page, so history can link out rather than
    #: re-rendering an invoice we do not own.
    invoice_url: str | None = None
    #: US-26.4: set once the credits for a top-up have actually landed. A grant is not
    #: idempotent the way a tier flip is, so the ledger row has to be written first — but
    #: that alone would lose the credits entirely if the process died between the insert
    #: and the grant, because the redelivery would see the row and report "duplicate".
    #: This flag lets a redelivery tell "already done" from "recorded but never
    #: completed" and finish the job. Null for events that grant nothing.
    credits_granted_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "billing_events"
        indexes = [
            # "this user's billing history, newest first" served from the index.
            IndexModel([("user_id", ASCENDING), ("created_at", DESCENDING)]),
            # The idempotency guard. Unique, not merely indexed.
            IndexModel([("stripe_event_id", ASCENDING)], unique=True),
        ]
