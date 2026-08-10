"""US-26.5: the usage summary behind the dashboard.

The ledger is a flat list of signed movements with a free-text ``action_type``; the
dashboard needs it shaped three ways at once (a daily series, a per-category total, a
readable history). These tests pin the shaping rules — especially the two that are easy
to get subtly wrong: refunds must cancel the charge they reverse, and days with no
activity must still appear in the series or the chart lies about its own x-axis.
"""

from datetime import datetime, timedelta, timezone

import pytest

from acemusic.api.models import Clip, CreditTransaction, Job, User
from acemusic.api.services import credits as credits_service, usage, users as user_service


@pytest.fixture(autouse=True)
def _db(mongo_db):
    """Service-layer tests with no HTTP client still need Beanie initialised."""
    return mongo_db


async def _user(email: str, *, monthly: float = 0.0, purchased: float = 0.0) -> User:
    user = await user_service.get_or_create_user(
        email=email, provider="google", oauth_id=f"g-{email}", name="Test User"
    )
    user.credits_balance = monthly
    user.purchased_credits = purchased
    # Anniversary and last reset on the same date, so "one month from the last reset" is
    # a fixed offset regardless of which day of the month the suite happens to run on.
    anchor = datetime.now(timezone.utc) - timedelta(days=5)
    user.created_at = anchor
    user.credits_reset_at = anchor
    await user.save()
    return user


async def _txn(user: User, *, amount: float, action_type: str, days_ago: float = 0, job_id: str = "") -> None:
    await CreditTransaction(
        user_id=user.id,
        amount=amount,
        action_type=action_type,
        job_id=job_id,
        balance_after=0.0,
        created_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
    ).insert()


class TestCategoryFor:
    """No DB: the action_type -> category mapping is pure."""

    @pytest.mark.parametrize(
        "action_type,category",
        [
            ("song", "generation"),
            ("sound", "generation"),
            ("full_song", "generation"),
            ("remix", "editing"),
            ("remaster", "editing"),
            ("mastering", "mastering"),
            ("video", "video"),
            ("stems", "extraction"),
            ("midi", "extraction"),
            ("voice_training", "voice"),
            ("monthly_reset", "grant"),
            ("something_new", "other"),
        ],
    )
    def test_known_actions_map_to_their_category(self, action_type: str, category: str) -> None:
        assert usage.category_for(action_type) == category

    def test_a_refund_lands_in_the_category_it_reverses(self) -> None:
        # The blanket failure path writes f"{job.job_type}_refund", and generation jobs
        # have job_type "generate" while their charge is "song"/"sound" — so the suffix
        # has to be stripped *and* "generate" has to map alongside them, or a refunded
        # song shows up as an "other" credit that never cancels its charge.
        assert usage.category_for("mastering_refund") == "mastering"
        assert usage.category_for("generate_refund") == "generation"
        assert usage.category_for("video_refund") == "video"


@pytest.mark.integration
class TestBuildUsageSummary:
    async def test_it_reports_both_buckets_the_tier_and_the_reset_date(self) -> None:
        user = await _user("usage-balance@example.com", monthly=30.0, purchased=12.0)

        summary = await usage.build_usage_summary(user)

        assert summary.monthly_credits == 30.0
        assert summary.purchased_credits == 12.0
        assert summary.total_credits == 42.0
        assert summary.tier == "free"
        assert summary.reset_at is not None
        # A month after the anchor _user set 5 days back — 23 days off in February,
        # 26 in a 31-day month.
        assert 22 <= summary.days_until_reset <= 27

    async def test_the_daily_series_covers_every_day_in_the_window(self) -> None:
        user = await _user("usage-series@example.com")
        await _txn(user, amount=-2.0, action_type="song", days_ago=0)
        await _txn(user, amount=-1.0, action_type="song", days_ago=3)

        summary = await usage.build_usage_summary(user, days=7)

        assert len(summary.daily) == 7
        assert [point.date for point in summary.daily] == sorted(point.date for point in summary.daily)
        by_date = {point.date: point.credits for point in summary.daily}
        today = datetime.now(timezone.utc).date()
        assert by_date[today] == 2.0
        assert by_date[today - timedelta(days=3)] == 1.0
        # The four quiet days are present and zero, not missing.
        assert sum(1 for value in by_date.values() if value == 0.0) == 5

    async def test_a_refund_cancels_the_charge_it_reverses(self) -> None:
        user = await _user("usage-refund@example.com")
        await _txn(user, amount=-4.0, action_type="mastering", days_ago=1)
        await _txn(user, amount=4.0, action_type="mastering_refund", days_ago=1)
        await _txn(user, amount=-3.0, action_type="video", days_ago=1)

        summary = await usage.build_usage_summary(user, days=7)

        totals = {row.category: row.credits for row in summary.categories}
        assert "mastering" not in totals  # netted to zero, so not worth a slice
        assert totals == {"video": 3.0}

    async def test_grants_are_history_but_not_consumption(self) -> None:
        user = await _user("usage-grant@example.com")
        await _txn(user, amount=50.0, action_type="monthly_reset", days_ago=2)
        await _txn(user, amount=-5.0, action_type="song", days_ago=2)

        summary = await usage.build_usage_summary(user, days=7)

        assert [row.category for row in summary.categories] == ["generation"]
        by_date = {point.date: point.credits for point in summary.daily}
        assert by_date[datetime.now(timezone.utc).date() - timedelta(days=2)] == 5.0
        # It still belongs in the history — the balance jumped, and the table has to say why.
        assert "monthly_reset" in [row.action_type for row in summary.history]

    async def test_it_ignores_rows_outside_the_window_and_other_users(self) -> None:
        user = await _user("usage-window@example.com")
        other = await _user("usage-other@example.com")
        await _txn(user, amount=-1.0, action_type="song", days_ago=2)
        await _txn(user, amount=-9.0, action_type="song", days_ago=40)
        await _txn(other, amount=-7.0, action_type="song", days_ago=1)

        summary = await usage.build_usage_summary(user, days=30)

        assert [row.amount for row in summary.history] == [-1.0]
        assert summary.categories == [usage.CategoryTotal(category="generation", credits=1.0)]

    async def test_the_totals_cover_the_window_even_when_the_table_is_truncated(self, monkeypatch) -> None:
        # The table is capped so the response stays a sane size; the charts above it are
        # not, or a heavy month would silently under-report its own oldest days.
        monkeypatch.setattr(usage, "MAX_HISTORY_ROWS", 2)
        user = await _user("usage-cap@example.com")
        for _ in range(5):
            await _txn(user, amount=-1.0, action_type="song", days_ago=1)

        summary = await usage.build_usage_summary(user, days=7)

        assert len(summary.history) == 2
        assert summary.categories == [usage.CategoryTotal(category="generation", credits=5.0)]

    async def test_history_is_newest_first_and_carries_the_clip_title(self) -> None:
        user = await _user("usage-titles@example.com")
        clip = await Clip(
            workspace_id=user.id, user_id=user.id, file_path="/tmp/a.wav", title="Midnight Drive"
        ).insert()
        job = await Job(
            user_id=user.id,
            workspace_id=user.id,
            job_type="mastering",
            input_params={"clip_id": str(clip.id)},
        ).insert()
        await _txn(user, amount=-4.0, action_type="mastering", days_ago=1, job_id=str(job.id))
        await _txn(user, amount=-2.0, action_type="song", days_ago=0)

        summary = await usage.build_usage_summary(user, days=7)

        assert [row.action_type for row in summary.history] == ["song", "mastering"]
        assert summary.history[1].clip_title == "Midnight Drive"
        # A job-less row is not an error, it simply has no clip to name.
        assert summary.history[0].clip_title is None

    async def test_a_generation_job_is_titled_from_the_clip_it_produced(self) -> None:
        user = await _user("usage-genclip@example.com")
        clip = await Clip(workspace_id=user.id, user_id=user.id, file_path="/tmp/b.wav", title="Sunburst").insert()
        job = await Job(
            user_id=user.id,
            workspace_id=user.id,
            job_type="generate",
            result={"clip_ids": [str(clip.id)]},
        ).insert()
        await _txn(user, amount=-1.0, action_type="song", days_ago=0, job_id=str(job.id))

        summary = await usage.build_usage_summary(user, days=7)

        assert summary.history[0].clip_title == "Sunburst"

    async def test_a_dangling_job_id_does_not_break_the_summary(self) -> None:
        user = await _user("usage-dangling@example.com")
        await _txn(user, amount=-1.0, action_type="song", days_ago=0, job_id="not-an-object-id")
        await _txn(user, amount=-1.0, action_type="video", days_ago=0, job_id="507f1f77bcf86cd799439011")

        summary = await usage.build_usage_summary(user, days=7)

        assert [row.clip_title for row in summary.history] == [None, None]

    async def test_it_reads_the_reset_date_the_credits_service_would(self) -> None:
        user = await _user("usage-reset@example.com")
        user.credits_reset_at = datetime.now(timezone.utc) - timedelta(days=29)
        await user.save()

        summary = await usage.build_usage_summary(user)

        # Mongo hands datetimes back naive; the summary normalises them to UTC so the
        # frontend does not have to guess a timezone.
        anchor = user.credits_reset_at.replace(tzinfo=timezone.utc)
        expected = credits_service.next_reset_due(anchor, anniversary_day=user.created_at.day)
        assert summary.reset_at == expected
        assert summary.reset_at.tzinfo is not None
