"""User document model (US-8.2)."""

from datetime import datetime

from beanie import Document
from pydantic import EmailStr, Field
from pymongo import ASCENDING, IndexModel

from .common import utcnow

# Starting balance for new accounts (US-9.6). No product spec exists yet — the
# purchase/subscription flow is Layer 4 (Stage 26) — so this is a provisional
# free allowance: enough for 10 songs or 20 sounds.
DEFAULT_CREDITS_BALANCE = 10.0


class User(Document):
    """A platform user. ``email`` is validated and uniquely indexed.

    ``name`` is the raw display name reported by the OAuth provider; ``display_name``
    is the user-editable profile name (defaulted from ``name`` on first login).
    ``handle`` is the unique, user-chosen public identifier (US-8.4).
    """

    email: EmailStr
    name: str
    oauth_provider: str | None = None
    oauth_id: str | None = None
    subscription_tier: str = "free"
    # US-9.6: deducted atomically at job-queue time (see services/credits.py).
    # Documents predating the field load with the default starting balance.
    credits_balance: float = DEFAULT_CREDITS_BALANCE
    # US-26.2: when the monthly allocation was last applied. The reset is anchored to
    # ``created_at`` (the subscription anniversary) rather than the calendar month, so
    # nobody gains or loses a partial period by signing up on the 3rd. Null means it has
    # never run — for accounts predating this field, the first read backfills it rather
    # than handing out a windfall.
    credits_reset_at: datetime | None = None
    # US-26.3: a read-model of the Stripe subscription, written only by the webhook
    # handler. The tier is read on nearly every request (the sidebar polls balance +
    # tier on each page), so asking Stripe for it would put a network call in the
    # hottest path in the app. Stripe stays the system of record; this is the cache
    # its events keep current.
    #
    # ``subscription_tier`` above remains the *effective* tier and is what every
    # capability check reads. Cancelling does not touch it — that is what makes
    # "keep Pro until the period ends" fall out of the event stream instead of
    # needing a scheduler to notice an expiry.
    stripe_customer_id: str | None = None
    stripe_subscription_id: str | None = None
    #: Mirrors Stripe's subscription status: active, past_due, canceled, unpaid,
    #: trialing, incomplete. ``None`` means the user has never subscribed.
    subscription_status: str | None = None
    #: End of the paid-for period. While a cancellation is pending this is the date
    #: Pro access actually stops, so the UI can say so.
    subscription_current_period_end: datetime | None = None
    #: Cancellation requested but not yet effective — Pro until the period end.
    subscription_cancel_at_period_end: bool = False
    #: When the subscription snapshot above was taken, from the Stripe event's own
    #: timestamp. Stripe does not guarantee event ordering, and each delivery carries
    #: its own event id so the idempotency guard cannot catch a late *older* snapshot —
    #: which would otherwise overwrite an active subscription with a stale
    #: ``incomplete``/``past_due`` one and downgrade a paying musician. Events older
    #: than this are dropped.
    subscription_synced_at: datetime | None = None
    #: Same idea for *invoice* events, kept separate on purpose. Sharing one watermark
    #: would let an invoice advance it and then silently drop a legitimate subscription
    #: event stamped a moment earlier — trading a cosmetic bug for an entitlement one.
    invoice_synced_at: datetime | None = None
    # Profile fields (US-8.4). All optional so existing/OAuth-created users remain
    # valid; ``handle`` stays null until the user claims one.
    display_name: str | None = None
    handle: str | None = None
    bio: str | None = None
    style_tags: list[str] = Field(default_factory=list)
    avatar_url: str | None = None
    # US-16.4: the user's preferred default generation model (a key in
    # constants.MODELS), used to seed the creation-page model selector. Null
    # means "no preference"; the UI falls back to its own default.
    default_model: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime | None = None

    class Settings:
        name = "users"
        indexes = [
            IndexModel([("email", ASCENDING)], unique=True),
            # Enforce one account per OAuth identity. The index is *partial* so it
            # only applies when both fields are present — otherwise the many users
            # with null oauth_provider/oauth_id (e.g. created before linking) would
            # all collide on a single (null, null) key under a plain unique index.
            IndexModel(
                [("oauth_provider", ASCENDING), ("oauth_id", ASCENDING)],
                unique=True,
                partialFilterExpression={
                    "oauth_provider": {"$type": "string"},
                    "oauth_id": {"$type": "string"},
                },
            ),
            # Handles are globally unique. Partial (same reasoning as the OAuth
            # index): the many users with a null handle must not collide on a
            # single null key under a plain unique index.
            IndexModel(
                [("handle", ASCENDING)],
                unique=True,
                partialFilterExpression={"handle": {"$type": "string"}},
            ),
        ]
