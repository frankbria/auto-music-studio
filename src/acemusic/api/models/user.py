"""User document model (US-8.2)."""

from datetime import datetime
from typing import Any

from beanie import Document
from pydantic import BaseModel, EmailStr, Field, model_validator
from pymongo import ASCENDING, IndexModel

from .common import utcnow

# Starting balance for new accounts (US-9.6). No product spec exists yet — the
# purchase/subscription flow is Layer 4 (Stage 26) — so this is a provisional
# free allowance: enough for 10 songs or 20 sounds.
DEFAULT_CREDITS_BALANCE = 10.0


class OAuthIdentity(BaseModel):
    """One provider account that signs into a :class:`User` (#111)."""

    provider: str
    oauth_id: str
    #: When this identity was attached. ``None`` for the identity an account was created
    #: with, and for the ones materialised from the legacy fields — in neither case is
    #: there a linking event to date, and inventing one would misreport provenance for
    #: exactly the records where it matters.
    linked_at: datetime | None = None


class User(Document):
    """A platform user. ``email`` is validated and uniquely indexed.

    ``name`` is the raw display name reported by the OAuth provider; ``display_name``
    is the user-editable profile name (defaulted from ``name`` on first login).
    ``handle`` is the unique, user-chosen public identifier (US-8.4).
    """

    email: EmailStr
    name: str
    #: Every OAuth identity that signs into this account (#111). Someone with the same
    #: address on Google and Discord used to be able to use only whichever they signed up
    #: with; a second provider reporting a verified, already-registered email now links
    #: here instead of being refused.
    identities: list[OAuthIdentity] = Field(default_factory=list)
    #: The *primary* identity, denormalised from ``identities[0]``.
    #:
    #: Kept rather than replaced, for two reasons. The partial-unique index below is built
    #: on these fields, and Beanie creates indexes at startup but never rebuilds one whose
    #: spec changed — so on any long-lived database a redefined index would silently keep
    #: its old definition. And documents written before ``identities`` existed have only
    #: these, which is what makes the migration a validator rather than a batch job.
    oauth_provider: str | None = None
    oauth_id: str | None = None
    subscription_tier: str = "free"
    # US-9.6: deducted atomically at job-queue time (see services/credits.py).
    # Documents predating the field load with the default starting balance.
    credits_balance: float = DEFAULT_CREDITS_BALANCE
    # US-26.4: credits bought as a top-up pack. A SECOND bucket rather than a bigger
    # number, because the monthly reset tops `credits_balance` *up to* the tier
    # allocation rather than adding to it — so with one field, buying 100 and spending 60
    # means the next monthly 50 never arrives (the balance is still above 50). Purchased
    # credits are never reset and are spent only after the monthly bucket is empty.
    purchased_credits: float = 0.0
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

    @model_validator(mode="before")
    @classmethod
    def _materialise_identities_from_legacy_fields(cls, data: Any) -> Any:
        """Give documents written before #111 an ``identities`` list on load.

        Same idiom as ``Clip.visibility``'s backfill from ``is_public``: the new shape is
        derived on read so no batch migration is needed, and the service persists it on
        the way past. Without this, every account that existed before this change would
        have an empty list and its owner would be locked out.
        """
        if not isinstance(data, dict) or data.get("identities"):
            return data

        provider, oauth_id = data.get("oauth_provider"), data.get("oauth_id")
        if not (isinstance(provider, str) and isinstance(oauth_id, str)):
            return data

        data = dict(data)
        data["identities"] = [{"provider": provider, "oauth_id": oauth_id}]
        return data

    @model_validator(mode="after")
    def _sync_primary_identity(self) -> "User":
        """Keep ``oauth_provider``/``oauth_id`` pointed at the first identity.

        They are the denormalisation the partial-unique index is built on, so they must
        never drift. Only the *primary* identity is mirrored — a linked second provider
        deliberately does not repoint them, or linking would move an account out from
        under the index entry that already guards it.
        """
        if self.identities:
            primary = self.identities[0]
            self.oauth_provider = primary.provider
            self.oauth_id = primary.oauth_id
        return self

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
            # #111: the same guarantee for *linked* identities, over the array. Legal
            # because only one of the two fields is an array path — MongoDB forbids a
            # compound index spanning two arrays, not one array of subdocuments.
            #
            # Additive on purpose: the index above still guards primary identities and
            # keeps its meaning, so no existing index has to be dropped or rebuilt. Beanie
            # never rebuilds an index whose spec changed, which makes redefining one on a
            # long-lived database a silent no-op.
            IndexModel(
                [("identities.provider", ASCENDING), ("identities.oauth_id", ASCENDING)],
                unique=True,
                partialFilterExpression={"identities.provider": {"$type": "string"}},
                name="identities_provider_oauth_id_unique",
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
