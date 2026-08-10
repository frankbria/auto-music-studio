"""Usage summary for the credits dashboard (US-26.5).

The ledger stores one signed movement per credit event with a free-text ``action_type``.
The dashboard wants three views of the same rows — a daily series, a per-category total,
and a readable history — so this module reads the window **once** and derives all three
in Python. A month of movements for one musician is tens of rows; a ``$group`` pipeline
per view would be three round trips to save nothing.

Two shaping rules carry the meaning:

* **Refunds cancel the charge they reverse.** ``mastering_refund`` nets against
  ``mastering``, so a failed job that was refunded does not linger in the breakdown as
  credit the musician never actually spent.
* **Grants are history, not consumption.** ``monthly_reset`` belongs in the table (the
  balance jumped and the table has to say why) but not in the "what did I spend it on"
  chart.

Not derivable here: which *bucket* paid for a given row. The ledger records only the
combined ``balance_after`` (see #421/#422), so the monthly-vs-purchased split is reported
for the remaining balance only.
"""

import math
from datetime import date, datetime, time, timedelta, timezone

from beanie import PydanticObjectId
from beanie.operators import In
from bson import ObjectId
from bson.errors import InvalidId
from pydantic import BaseModel
from pymongo import DESCENDING

from ..models import Clip, CreditTransaction, Job, User
from . import credits as credits_service

#: Default reporting window, matching the "past 30 days" the dashboard advertises.
DEFAULT_WINDOW_DAYS = 30

#: Hard cap on returned history *rows*. The charts above the table still total the whole
#: window — only the listing is truncated, so a heavy month reports honest numbers with a
#: shortened table rather than an accurate table nobody can download.
MAX_HISTORY_ROWS = 1000

#: ``action_type`` -> category. Anything unlisted falls back to "other" rather than
#: raising: a new action type must not take the dashboard down before its mapping lands.
CATEGORIES: dict[str, str] = {
    "song": "generation",
    "sound": "generation",
    "full_song": "generation",
    # The blanket failure path labels refunds by *job* type, and a generation job's type
    # is "generate" while its charge is "song"/"sound". Mapped alongside them so the
    # refund nets against the charge instead of drifting into "other".
    "generate": "generation",
    "extend": "editing",
    "cover": "editing",
    "remix": "editing",
    "repaint": "editing",
    "sample": "editing",
    "add_vocal": "editing",
    "mashup": "editing",
    "crop": "editing",
    "speed": "editing",
    "remaster": "editing",
    "mastering": "mastering",
    "video": "video",
    "stems": "extraction",
    "midi": "extraction",
    "voice_training": "voice",
    "monthly_reset": "grant",
}

#: The one category that adds credit rather than consuming it, excluded from the charts.
GRANT_CATEGORY = "grant"


class DailyPoint(BaseModel):
    """Net credits consumed on one calendar day (UTC)."""

    date: date
    credits: float


class CategoryTotal(BaseModel):
    """Net credits consumed by one action category over the window."""

    category: str
    credits: float


class UsageRow(BaseModel):
    """One ledger movement, as the history table shows it."""

    created_at: datetime
    action_type: str
    category: str
    amount: float
    balance_after: float
    job_id: str
    #: Best effort. None when the row has no job, the job is gone, or the job never
    #: referenced a clip (generation jobs only name one once they have completed).
    clip_title: str | None = None


class UsageSummary(BaseModel):
    """Everything the dashboard renders, in one response."""

    tier: str
    monthly_credits: float
    purchased_credits: float
    total_credits: float
    reset_at: datetime | None
    days_until_reset: int | None
    window_days: int
    daily: list[DailyPoint]
    categories: list[CategoryTotal]
    history: list[UsageRow]


def category_for(action_type: str) -> str:
    """The action category ``action_type`` belongs to, refunds included.

    A refund is labelled ``<something>_refund``; stripping the suffix puts it in the same
    category as the charge it reverses so the two cancel.
    """
    base = action_type[: -len("_refund")] if action_type.endswith("_refund") else action_type
    return CATEGORIES.get(base, "other")


async def build_usage_summary(user: User, *, days: int = DEFAULT_WINDOW_DAYS) -> UsageSummary:
    """Balance, reset date, and ``days`` worth of usage for ``user``.

    Callers should apply the monthly reset first (as the balance endpoint does), or the
    dashboard will disagree with the sidebar for anyone whose top-up is overdue.
    """
    days = max(1, days)
    now = datetime.now(timezone.utc)
    first_day = now.date() - timedelta(days=days - 1)
    start = datetime.combine(first_day, time.min, tzinfo=timezone.utc)

    # The whole window, uncapped: the charts must total every movement or a heavy month
    # silently under-reports its own oldest days. Only the *history list* is capped
    # (below), which bounds the response without lying about the numbers above it.
    rows = (
        await CreditTransaction.find(
            CreditTransaction.user_id == user.id,
            CreditTransaction.created_at >= start,
        )
        .sort([("created_at", DESCENDING), ("_id", DESCENDING)])
        .to_list()
    )

    daily = {first_day + timedelta(days=offset): 0.0 for offset in range(days)}
    totals: dict[str, float] = {}

    for row in rows:
        category = category_for(row.action_type)
        if category == GRANT_CATEGORY:
            continue
        # Charges are negative in the ledger; the chart reads in credits spent, and a
        # refund's positive amount subtracts from that.
        spent = -row.amount
        moment = row.created_at if row.created_at.tzinfo else row.created_at.replace(tzinfo=timezone.utc)
        day = moment.astimezone(timezone.utc).date()
        if day in daily:
            daily[day] += spent
        totals[category] = totals.get(category, 0.0) + spent

    history = rows[:MAX_HISTORY_ROWS]
    titles = await _clip_titles(user, {row.job_id for row in history if row.job_id})
    reset_at = _next_reset(user)
    monthly, purchased = credits_service.buckets(user)

    return UsageSummary(
        tier=user.subscription_tier,
        monthly_credits=monthly,
        purchased_credits=purchased,
        total_credits=credits_service.spendable(user),
        reset_at=reset_at,
        days_until_reset=None if reset_at is None else max(0, math.ceil((reset_at - now).total_seconds() / 86400)),
        window_days=days,
        daily=[DailyPoint(date=day, credits=round(value, 4)) for day, value in sorted(daily.items())],
        # A category that netted to zero is not a slice worth drawing.
        categories=[
            CategoryTotal(category=name, credits=round(value, 4))
            for name, value in sorted(totals.items(), key=lambda item: -item[1])
            if round(value, 4) != 0.0
        ],
        history=[
            UsageRow(
                created_at=row.created_at,
                action_type=row.action_type,
                category=category_for(row.action_type),
                amount=row.amount,
                balance_after=row.balance_after,
                job_id=row.job_id,
                clip_title=titles.get(row.job_id),
            )
            for row in history
        ],
    )


def _next_reset(user: User) -> datetime | None:
    """When ``user``'s monthly allocation lands next, or None if never yet anchored."""
    anchor = user.credits_reset_at

    if anchor is None:
        return None

    anchor = anchor if anchor.tzinfo else anchor.replace(tzinfo=timezone.utc)
    created = user.created_at if user.created_at.tzinfo else user.created_at.replace(tzinfo=timezone.utc)

    return credits_service.next_reset_due(anchor, anniversary_day=created.day)


async def _clip_titles(user: User, job_ids: set[str]) -> dict[str, str]:
    """Map job id -> the title of the clip it touched, for the rows that have one.

    Two hops (jobs, then clips) rather than a per-row lookup, and both batched. Rows whose
    job predates the clip link — or whose job has been deleted — simply come back absent;
    a missing title is cosmetic and must not fail the dashboard.

    Both hops are scoped to ``user``. The ids come from that user's own ledger, so this is
    belt-and-braces — but it is the difference between a stale or mis-written ``job_id``
    being a blank cell and it naming somebody else's track.
    """
    valid = [PydanticObjectId(job_id) for job_id in job_ids if ObjectId.is_valid(job_id)]

    if not valid:
        return {}

    clip_by_job: dict[str, PydanticObjectId] = {}

    for job in await Job.find(Job.user_id == user.id, In(Job.id, valid)).to_list():
        # Edit/master/video jobs name their input clip; generation jobs name their output
        # only once they have completed.
        raw = job.input_params.get("clip_id") or next(iter((job.result or {}).get("clip_ids", [])), None)

        try:
            if raw:
                clip_by_job[str(job.id)] = PydanticObjectId(str(raw))
        except (InvalidId, ValueError):
            continue

    if not clip_by_job:
        return {}

    clips = await Clip.find(Clip.user_id == user.id, In(Clip.id, list(clip_by_job.values()))).to_list()
    titles = {clip.id: clip.title for clip in clips}

    return {job_id: titles[clip_id] for job_id, clip_id in clip_by_job.items() if titles.get(clip_id) is not None}
