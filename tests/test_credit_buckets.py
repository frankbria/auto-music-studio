"""US-26.4: monthly credits are spent before purchased ones (AC2, AC3).

The split exists because :func:`apply_monthly_reset` grants
``max(0, allocation - credits_balance)`` — it tops *up to* the allocation rather than
adding. With a single number, buying 100 credits and spending 60 means the next monthly
50 never arrives, because the balance is still above 50. AC2 and AC3 cannot both hold in
one field.

The deduction has to span two buckets and stay a **single** atomic operation, or two
concurrent generations can each pass a two-read check and overdraw a balance that only
covers one. That is what most of this file is about.
"""

import asyncio

import pytest

from acemusic.api.models import User
from acemusic.api.services import credits as credits_service, tiers, users as user_service


@pytest.fixture(autouse=True)
def _db(mongo_db):
    """Initialise Beanie against the isolated test database for every case here.

    These are service-layer tests with no HTTP client, so nothing else pulls the
    ``mongo_db`` fixture in — without this, every case fails on an uninitialised model
    rather than on anything it is asserting.
    """
    return mongo_db


async def _user(email: str, *, monthly: float = 0.0, purchased: float = 0.0) -> User:
    user = await user_service.get_or_create_user(
        email=email, provider="google", oauth_id=f"g-{email}", name="Test User"
    )
    user.credits_balance = monthly
    user.purchased_credits = purchased
    await user.save()
    return user


@pytest.mark.integration
class TestSpendOrder:
    """AC2: the monthly allocation is consumed first."""

    async def test_a_deduction_within_the_monthly_bucket_leaves_purchases_alone(self) -> None:
        user = await _user("buckets-monthly@example.com", monthly=50.0, purchased=100.0)

        remaining = await credits_service.deduct_credits(user.id, 20.0)

        refreshed = await User.get(user.id)
        assert refreshed.credits_balance == 30.0
        assert refreshed.purchased_credits == 100.0
        # The caller sees one number — a musician does not care which bucket paid.
        assert remaining == 130.0

    async def test_a_deduction_spanning_both_drains_monthly_first(self) -> None:
        user = await _user("buckets-spanning@example.com", monthly=10.0, purchased=100.0)

        remaining = await credits_service.deduct_credits(user.id, 30.0)

        refreshed = await User.get(user.id)
        assert refreshed.credits_balance == 0.0
        assert refreshed.purchased_credits == 80.0
        assert remaining == 80.0

    async def test_a_deduction_exactly_equal_to_the_monthly_balance(self) -> None:
        # The boundary the `$min` sits on: no purchased credit may be touched.
        user = await _user("buckets-exact@example.com", monthly=25.0, purchased=100.0)

        await credits_service.deduct_credits(user.id, 25.0)

        refreshed = await User.get(user.id)
        assert refreshed.credits_balance == 0.0
        assert refreshed.purchased_credits == 100.0

    async def test_purchased_credits_alone_can_pay(self) -> None:
        user = await _user("buckets-onlybought@example.com", monthly=0.0, purchased=5.0)

        assert await credits_service.deduct_credits(user.id, 3.0) == 2.0
        assert (await User.get(user.id)).purchased_credits == 2.0

    async def test_an_unaffordable_deduction_changes_nothing(self) -> None:
        user = await _user("buckets-broke@example.com", monthly=1.0, purchased=1.0)

        assert await credits_service.deduct_credits(user.id, 5.0) is None

        refreshed = await User.get(user.id)
        assert refreshed.credits_balance == 1.0
        assert refreshed.purchased_credits == 1.0


@pytest.mark.integration
class TestAtomicity:
    async def test_concurrent_deductions_cannot_overdraw_across_buckets(self) -> None:
        # The reason this is one pipeline update rather than read-then-write. Ten
        # requests, a combined balance that covers five: exactly five may succeed.
        user = await _user("buckets-race@example.com", monthly=3.0, purchased=2.0)

        results = await asyncio.gather(*(credits_service.deduct_credits(user.id, 1.0) for _ in range(10)))

        assert sum(1 for r in results if r is not None) == 5
        refreshed = await User.get(user.id)
        assert refreshed.credits_balance == 0.0
        assert refreshed.purchased_credits == 0.0

    async def test_a_legacy_document_without_either_field_still_works(self) -> None:
        # Documents predating US-9.6 have no credits_balance; those predating US-26.4
        # have no purchased_credits. A $expr over a missing field must not silently
        # reject them — the existing backfill path has to keep working.
        user = await _user("buckets-legacy@example.com", monthly=10.0)
        await User.get_pymongo_collection().update_one(
            {"_id": user.id}, {"$unset": {"credits_balance": "", "purchased_credits": ""}}
        )

        remaining = await credits_service.deduct_credits(user.id, 1.0)

        assert remaining is not None, "a legacy account must not be refused"

    async def test_a_document_with_no_purchased_field_deducts_from_monthly(self) -> None:
        user = await _user("buckets-nopurchased@example.com", monthly=10.0)
        await User.get_pymongo_collection().update_one({"_id": user.id}, {"$unset": {"purchased_credits": ""}})

        assert await credits_service.deduct_credits(user.id, 4.0) == 6.0


@pytest.mark.integration
class TestGrant:
    """AC1: buying a pack increases the balance by the correct amount."""

    async def test_a_grant_lands_in_the_purchased_bucket(self) -> None:
        user = await _user("buckets-grant@example.com", monthly=50.0)

        total = await credits_service.grant_purchased_credits(user.id, 100.0)

        refreshed = await User.get(user.id)
        assert refreshed.purchased_credits == 100.0
        assert refreshed.credits_balance == 50.0, "a purchase is not a monthly grant"
        assert total == 150.0

    async def test_grants_accumulate(self) -> None:
        user = await _user("buckets-grant2@example.com")
        await credits_service.grant_purchased_credits(user.id, 50.0)
        await credits_service.grant_purchased_credits(user.id, 100.0)
        assert (await User.get(user.id)).purchased_credits == 150.0

    @pytest.mark.parametrize("amount", [0.0, -50.0])
    async def test_a_non_positive_grant_is_refused(self, amount: float) -> None:
        # Mirrors deduct_credits' guard. A negative "grant" would confiscate credits.
        user = await _user("buckets-badgrant@example.com")
        with pytest.raises(ValueError):
            await credits_service.grant_purchased_credits(user.id, amount)


@pytest.mark.integration
class TestMonthlyResetIgnoresPurchases:
    """AC3: purchased credits persist across monthly resets."""

    async def test_the_reset_does_not_touch_the_purchased_bucket(self) -> None:
        user = await _user("buckets-reset@example.com", monthly=0.0, purchased=100.0)
        user.credits_reset_at = credits_service.next_reset_due(
            user.created_at.replace(tzinfo=None) if user.created_at.tzinfo else user.created_at
        )
        # Force the reset to be due by backdating the anchor a long way.
        await User.get_pymongo_collection().update_one({"_id": user.id}, {"$set": {"credits_reset_at": _long_ago()}})

        refreshed = await credits_service.apply_monthly_reset(await User.get(user.id))

        assert refreshed.purchased_credits == 100.0, "a purchase must survive the reset"

    async def test_the_full_allocation_arrives_despite_a_large_purchase(self) -> None:
        # The bug that forces the whole split: with one balance, `max(0, allocation -
        # balance)` grants nothing while purchased credits sit above the allocation, so
        # the musician silently loses a month.
        user = await _user("buckets-reset2@example.com", monthly=0.0, purchased=500.0)
        await User.get_pymongo_collection().update_one({"_id": user.id}, {"$set": {"credits_reset_at": _long_ago()}})

        refreshed = await credits_service.apply_monthly_reset(await User.get(user.id))

        assert refreshed.credits_balance == tiers.monthly_allocation("free")
        assert refreshed.purchased_credits == 500.0


def _long_ago():
    from datetime import datetime, timezone

    return datetime(2020, 1, 1, tzinfo=timezone.utc)


@pytest.mark.integration
class TestBalanceSurfaces:
    """Every place that says "your balance" must mean both buckets.

    Seven call sites read ``credits_balance`` directly before this story. A criterion
    about a displayed number has as many surfaces as there are readers of it, and
    checking one proves nothing about the rest (cf. tasks/lessons.md, US-26.2 AC2).
    """

    async def test_spendable_sums_both_buckets(self) -> None:
        user = await _user("surfaces-sum@example.com", monthly=30.0, purchased=70.0)
        assert credits_service.spendable(user) == 100.0

    async def test_spendable_tolerates_a_document_without_the_new_field(self) -> None:
        user = await _user("surfaces-legacy@example.com", monthly=30.0)
        object.__setattr__(user, "purchased_credits", None)
        assert credits_service.spendable(user) == 30.0

    async def test_nothing_reports_a_balance_from_the_monthly_bucket_alone(self) -> None:
        # A grep-shaped assertion on purpose: the failure mode is a *new* call site
        # reading credits_balance directly and quietly under-reporting what a musician
        # paid for. This fails when that happens, which a per-endpoint test would not.
        #
        # Covers `services/` as well as `routers/`. Raised in review on PR #421: the
        # original router-only version missed three service-layer sites building
        # InsufficientCreditsError from the raw field — the same bug, one layer down,
        # invisible to a test that only looked at routers.
        import pathlib

        searched = [
            *pathlib.Path("src/acemusic/api/routers").glob("*.py"),
            *pathlib.Path("src/acemusic/api/services").glob("*.py"),
        ]
        offenders = []
        for path in searched:
            for lineno, line in enumerate(path.read_text().splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                # `credits.py` owns the field, so its own reads and writes of the bucket
                # are the implementation rather than a report of a balance.
                if path.name == "credits.py":
                    continue
                if "credits_balance" in stripped and "spendable" not in stripped:
                    offenders.append(f"{path.name}:{lineno}: {stripped}")
        assert not offenders, "report spendable(), not the monthly bucket alone:\n" + "\n".join(offenders)
