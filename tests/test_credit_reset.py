"""US-26.2 AC5: credits reset to the tier allocation on the monthly anniversary.

Applied lazily, on read, rather than by a scheduler — a cron that misses a window leaves
someone short until the next one, and there is no window to miss if the answer is computed
from the dates every time it is asked for.

The date arithmetic is the risky part (month lengths, anniversaries on the 31st), so it is
a pure function tested without a database.
"""

from datetime import datetime, timedelta, timezone

import pytest
from beanie import PydanticObjectId

from acemusic.api.models import User
from acemusic.api.services import credits as credits_service, users as user_service


def _at(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


class TestNextResetDue:
    """When the allocation is next owed, given the anniversary and the last reset."""

    def test_one_month_after_the_last_reset(self) -> None:
        assert credits_service.next_reset_due(_at(2026, 3, 10)) == _at(2026, 4, 10)

    def test_a_month_shorter_than_the_anniversary_day_clamps_to_its_end(self) -> None:
        # Signing up on the 31st must not skip February, and must not roll into March.
        assert credits_service.next_reset_due(_at(2026, 1, 31)) == _at(2026, 2, 28)

    def test_a_leap_february_takes_the_29th(self) -> None:
        assert credits_service.next_reset_due(_at(2028, 1, 31)) == _at(2028, 2, 29)

    def test_december_rolls_the_year(self) -> None:
        assert credits_service.next_reset_due(_at(2026, 12, 15)) == _at(2027, 1, 15)

    def test_the_clamp_does_not_stick(self) -> None:
        # A January-31 signup clamped to Feb 28 must go back to the 31st in March, not
        # spend the rest of its life on the 28th. This is why the anniversary is passed
        # separately from the last reset.
        assert credits_service.next_reset_due(_at(2026, 2, 28), anniversary_day=31) == _at(2026, 3, 31)


@pytest.mark.integration
class TestApplyMonthlyReset:
    async def _user(self, label: str, *, tier: str, balance: float, created: datetime, last_reset=None) -> User:
        email = f"{label}-{PydanticObjectId()}@example.com"
        user = await user_service.get_or_create_user(
            email=email, provider="google", oauth_id=email, name="T"
        )
        user.subscription_tier = tier
        user.credits_balance = balance
        user.created_at = created
        user.credits_reset_at = last_reset
        await user.save()
        return user

    async def test_a_due_free_account_is_topped_up_to_its_allocation(self, mongo_db) -> None:
        long_ago = datetime.now(timezone.utc) - timedelta(days=40)
        user = await self._user("due-free", tier="free", balance=3.0, created=long_ago, last_reset=long_ago)

        refreshed = await credits_service.apply_monthly_reset(user)

        assert refreshed.credits_balance == 50.0

    async def test_a_due_pro_account_gets_the_pro_allocation(self, mongo_db) -> None:
        long_ago = datetime.now(timezone.utc) - timedelta(days=40)
        user = await self._user("due-pro", tier="pro", balance=3.0, created=long_ago, last_reset=long_ago)

        refreshed = await credits_service.apply_monthly_reset(user)

        assert refreshed.credits_balance == 500.0

    async def test_an_account_not_yet_due_is_left_alone(self, mongo_db) -> None:
        recent = datetime.now(timezone.utc) - timedelta(days=3)
        user = await self._user("not-due", tier="free", balance=7.0, created=recent, last_reset=recent)

        refreshed = await credits_service.apply_monthly_reset(user)

        assert refreshed.credits_balance == 7.0

    async def test_the_reset_is_recorded_so_it_does_not_repeat(self, mongo_db) -> None:
        long_ago = datetime.now(timezone.utc) - timedelta(days=40)
        user = await self._user("once", tier="free", balance=3.0, created=long_ago, last_reset=long_ago)

        await credits_service.apply_monthly_reset(user)
        after_first = (await User.get(user.id)).credits_balance

        # Spend, then ask again in the same period: the top-up must not come back.
        await credits_service.deduct_credits(user.id, 10.0)
        again = await credits_service.apply_monthly_reset(await User.get(user.id))

        assert after_first == 50.0
        assert again.credits_balance == 40.0, "the allocation was granted twice in one period"

    async def test_a_reset_is_visible_in_the_history(self, mongo_db) -> None:
        # A balance that jumps with no row to explain it is the same complaint the
        # refund ledger fixed.
        from acemusic.api.models import CreditTransaction

        long_ago = datetime.now(timezone.utc) - timedelta(days=40)
        user = await self._user("ledgered", tier="free", balance=3.0, created=long_ago, last_reset=long_ago)

        await credits_service.apply_monthly_reset(user)

        rows = await CreditTransaction.find(CreditTransaction.user_id == user.id).to_list()
        assert [r.action_type for r in rows] == ["monthly_reset"]
        assert rows[0].amount == 47.0, "the row should record the movement, not the new total"
        assert rows[0].balance_after == 50.0

    async def test_an_account_that_has_never_reset_is_backfilled_not_paid(self, mongo_db) -> None:
        # Accounts predating the field have credits_reset_at=None. Treating that as
        # "infinitely overdue" would hand every one of them a windfall on next read.
        user = await self._user(
            "backfill", tier="free", balance=12.0, created=datetime.now(timezone.utc) - timedelta(days=3)
        )

        refreshed = await credits_service.apply_monthly_reset(user)

        assert refreshed.credits_balance == 12.0
        assert refreshed.credits_reset_at is not None, "the anchor was not backfilled"

    async def test_a_balance_above_the_allocation_is_not_clawed_back(self, mongo_db) -> None:
        # A top-up purchase (US-26.4) can leave someone above their monthly figure;
        # "reset to allocation" must not mean "confiscate what they bought".
        long_ago = datetime.now(timezone.utc) - timedelta(days=40)
        user = await self._user("rich", tier="free", balance=120.0, created=long_ago, last_reset=long_ago)

        refreshed = await credits_service.apply_monthly_reset(user)

        assert refreshed.credits_balance == 120.0

    async def test_several_missed_periods_grant_one_allocation_not_many(self, mongo_db) -> None:
        # Someone away for six months comes back to their monthly allowance, not six.
        ages_ago = datetime.now(timezone.utc) - timedelta(days=190)
        user = await self._user("lapsed", tier="free", balance=1.0, created=ages_ago, last_reset=ages_ago)

        refreshed = await credits_service.apply_monthly_reset(user)

        assert refreshed.credits_balance == 50.0
