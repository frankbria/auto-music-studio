"""US-26.3: mapping a Stripe subscription onto the user's tier.

The whole story hangs on one question — *given what Stripe says the subscription is,
what tier should this musician have right now?* — and the two most valuable acceptance
criteria are both edge cases of it:

- AC2, cancelling keeps Pro until the period ends
- AC3, a failed payment gets a grace period rather than an instant downgrade

Both are decided by the status mapping, so it is a pure function tested without a
database, a webhook, or a Stripe account.
"""

import pytest

from acemusic.api.services import billing, tiers


def _subscription(status: str, **overrides) -> dict:
    """A Stripe subscription object, trimmed to the fields the mapping reads."""
    return {
        "id": "sub_123",
        "status": status,
        "cancel_at_period_end": False,
        "current_period_end": 1_800_000_000,
        **overrides,
    }


class TestTierForStatus:
    """Which statuses are worth paying for."""

    @pytest.mark.parametrize("status", ["active", "trialing"])
    def test_a_paid_subscription_is_pro(self, status: str) -> None:
        assert billing.tier_for_status(status) == tiers.PRO

    def test_past_due_keeps_pro(self) -> None:
        # AC3. A failed charge starts Stripe's retry schedule; the musician keeps what
        # they paid for while it runs. Downgrading on the first failure would punish a
        # expired card the same as a refusal to pay.
        assert billing.tier_for_status("past_due") == tiers.PRO

    @pytest.mark.parametrize("status", ["canceled", "unpaid", "incomplete", "incomplete_expired"])
    def test_everything_else_is_free(self, status: str) -> None:
        # "unpaid" is Stripe's terminal state *after* retries are exhausted — that is
        # the downgrade AC3 asks for, and it is a different status from "past_due".
        assert billing.tier_for_status(status) == tiers.FREE

    def test_an_unknown_status_fails_closed(self) -> None:
        # Same rule as tiers.normalise: a status we do not recognise must not hand out
        # Pro. A new Stripe status should cost us a support ticket, not free revenue.
        assert billing.tier_for_status("some_future_status") == tiers.FREE
        assert billing.tier_for_status(None) == tiers.FREE


class TestSubscriptionFields:
    """The read-model written onto the user document."""

    def test_an_active_subscription_grants_pro(self) -> None:
        fields = billing.subscription_fields(_subscription("active"))
        assert fields["subscription_tier"] == tiers.PRO
        assert fields["subscription_status"] == "active"
        assert fields["stripe_subscription_id"] == "sub_123"
        assert fields["subscription_cancel_at_period_end"] is False

    def test_a_pending_cancellation_keeps_pro_and_records_the_end_date(self) -> None:
        # AC2. Stripe leaves the status "active" until the period actually ends, so the
        # tier must not move — but the date has to be recorded, or the UI cannot tell
        # the musician when access stops.
        fields = billing.subscription_fields(_subscription("active", cancel_at_period_end=True))
        assert fields["subscription_tier"] == tiers.PRO
        assert fields["subscription_cancel_at_period_end"] is True
        assert fields["subscription_current_period_end"] is not None

    def test_the_period_end_is_a_real_datetime(self) -> None:
        fields = billing.subscription_fields(_subscription("active"))
        end = fields["subscription_current_period_end"]
        assert end.year == 2027 and end.tzinfo is not None

    def test_a_missing_period_end_is_tolerated(self) -> None:
        # Not every subscription payload carries one (an incomplete checkout, say).
        # A KeyError here would 500 the webhook and make Stripe redeliver forever.
        fields = billing.subscription_fields(_subscription("incomplete", current_period_end=None))
        assert fields["subscription_current_period_end"] is None

    def test_a_deleted_subscription_downgrades(self) -> None:
        fields = billing.subscription_fields(_subscription("canceled"))
        assert fields["subscription_tier"] == tiers.FREE
