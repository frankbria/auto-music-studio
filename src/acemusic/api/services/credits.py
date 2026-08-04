"""Credits service layer (US-9.6).

Module-level async functions (matching the other service modules) for the
credit cost table, atomic balance deduction, and the transaction ledger. The
layer raises plain exceptions, never ``HTTPException``, so it stays
transport-agnostic.
"""

import logging

from beanie import PydanticObjectId
from pymongo import DESCENDING, ReturnDocument

from ..models import CreditTransaction, JobStatus, User
from ..models.user import DEFAULT_CREDITS_BALANCE

logger = logging.getLogger(__name__)

SONG_COST = 1.0
SOUND_COST = 0.5

# US-10.3: each single-source iterative generation runs one ACE-Step (or
# ElevenLabs) job, costing the same as a song generation. The ``sample`` endpoint
# multiplies this base by ``num_clips`` in the router (several outputs); mashup
# costs 2 credits per the documented pricing (it blends multiple sources).
ITERATIVE_COST = 1.0
MASHUP_COST = 2.0
_SINGLE_SOURCE_ITERATIVE_MODES = ("extend", "cover", "remix", "repaint", "sample", "add_vocal")

# US-10.4: full-song chains one extend per planned section, so ``full_song`` costs
# ITERATIVE_COST *per section*; the router multiplies this base by the section
# count (mirroring how ``sample`` multiplies by ``num_clips``).
FULL_SONG_COST = ITERATIVE_COST

_COSTS = {
    "song": SONG_COST,
    "sound": SOUND_COST,
    "mashup": MASHUP_COST,
    "full_song": FULL_SONG_COST,
    **{mode: ITERATIVE_COST for mode in _SINGLE_SOURCE_ITERATIVE_MODES},
}

# US-12.1: mastering is billed per external service, tiered within the
# documented 2-5 credit band by perceived service value (Dolby is the default).
MASTERING_DOLBY_COST = 3.0
MASTERING_LANDR_COST = 2.0
MASTERING_BAKUAGE_COST = 5.0

_MASTERING_COSTS = {
    "dolby": MASTERING_DOLBY_COST,
    "landr": MASTERING_LANDR_COST,
    "bakuage": MASTERING_BAKUAGE_COST,
}

# US-22.1: video rendering is billed within the documented 5-10 credit band by
# resolution, with a surcharge for long songs (rendering cost scales with both).
# Kept out of ``_COSTS`` — video is not a generation mode, and the cost is
# two-dimensional (resolution x duration) where ``_COSTS`` is flat.
_VIDEO_COSTS = {
    "720p": 5.0,
    "1080p": 7.0,
    "4k": 8.0,
}
VIDEO_LONG_DURATION_S = 180.0
VIDEO_LONG_DURATION_SURCHARGE = 2.0
VIDEO_MAX_COST = 10.0

# US-25.1: training a custom voice model is a premium action -- minutes of GPU
# fine-tuning rather than one inference pass -- and is priced accordingly. Kept
# out of ``_COSTS`` because it is not a generation mode; ``get_cost("voice_training")``
# would wrongly suggest it is one.
VOICE_TRAINING_COST = 10.0

# History page size for GET /users/me/credits.
HISTORY_LIMIT = 50


def get_cost(mode: str) -> float:
    """Credit cost of one generation in ``mode``. Raises for unknown modes."""
    try:
        return _COSTS[mode]
    except KeyError:
        raise ValueError(f"Unknown generation mode: {mode!r}") from None


def get_video_cost(resolution: str, duration_s: float | None = None) -> float:
    """Credit cost of one video render at ``resolution`` for a ``duration_s`` song.

    Raises for unknown resolutions. A song longer than ``VIDEO_LONG_DURATION_S``
    adds the long-duration surcharge; the total is capped at ``VIDEO_MAX_COST``
    (the top of the documented 5-10 band). ``duration_s`` may be ``None`` — some
    clips predate duration tracking — and then bills the base rate.
    """
    try:
        cost = _VIDEO_COSTS[resolution]
    except KeyError:
        raise ValueError(f"Unknown video resolution: {resolution!r}") from None
    if duration_s is not None and duration_s > VIDEO_LONG_DURATION_S:
        cost += VIDEO_LONG_DURATION_SURCHARGE
    return min(cost, VIDEO_MAX_COST)


def get_mastering_cost(service: str) -> float:
    """Credit cost of one mastering job on ``service``. Raises for unknown services."""
    try:
        return _MASTERING_COSTS[service]
    except KeyError:
        raise ValueError(f"Unknown mastering service: {service!r}") from None


async def deduct_credits(user_id: PydanticObjectId, cost: float) -> float | None:
    """Atomically deduct ``cost`` from the user's balance.

    A single ``find_one_and_update`` filtered on ``credits_balance >= cost``,
    so two concurrent requests racing over the last credit are serialised by
    MongoDB — exactly one matches and decrements; the loser matches nothing.
    Returns the balance *after* deduction, or ``None`` if the balance was
    insufficient (or the user does not exist).
    """
    # A non-positive cost would invert the operation: the $gte filter always
    # matches and the $inc would *grant* credits. Reject at the boundary.
    if cost <= 0:
        raise ValueError("cost must be positive")
    collection = User.get_pymongo_collection()
    update = (
        {"_id": user_id, "credits_balance": {"$gte": cost}},
        {"$inc": {"credits_balance": -cost}},
    )
    doc = await collection.find_one_and_update(*update, return_document=ReturnDocument.AFTER)
    if doc is None:
        # Documents predating US-9.6 have no credits_balance field, and a $gte
        # range filter never matches an absent field — without a backfill every
        # legacy account would be rejected while /users/me/credits shows the
        # (Pydantic-level) default. Materialise the default and retry once.
        # Concurrent backfills are harmless: $set of the same constant, gated
        # on the field still being absent, is idempotent.
        await collection.update_one(
            {"_id": user_id, "credits_balance": {"$exists": False}},
            {"$set": {"credits_balance": DEFAULT_CREDITS_BALANCE}},
        )
        # Retry unconditionally: a concurrent request may have won the backfill
        # (our update matched nothing), yet the now-present balance can still
        # cover this deduction. A genuinely insufficient balance just fails the
        # retry the same way it failed the first attempt.
        doc = await collection.find_one_and_update(*update, return_document=ReturnDocument.AFTER)
    if doc is None:
        return None
    return doc["credits_balance"]


async def refund_credits(
    user_id: PydanticObjectId,
    cost: float,
    *,
    action_type: str,
    job_id: str,
) -> None:
    """Compensating credit for a deduction, ledgered (US-26.1).

    ``action_type`` and ``job_id`` are keyword-*required* on purpose. This used to
    move the balance and write nothing, so most refunds were invisible in the
    history and the ledger could not answer "how much has this job been paid back?".
    Both now have one answer, in one place, because
    :func:`refund_failed_job` depends on the ledger being complete.

    ``job_id`` may be ``""``: the request paths refund when job creation itself
    failed, so there is no id to attribute the movement to.
    """
    # Symmetric guard: a non-positive "refund" would silently deduct.
    if cost <= 0:
        raise ValueError("cost must be positive")

    # find_one_and_update rather than update_one + re-read: the balance recorded on
    # the ledger row has to be the one this movement produced, not whatever a
    # concurrent charge left behind a moment later.
    doc = await User.get_pymongo_collection().find_one_and_update(
        {"_id": user_id},
        {"$inc": {"credits_balance": cost}},
        return_document=ReturnDocument.AFTER,
    )

    if doc is None:
        # No user, so no balance moved — recording a movement would be a lie.
        logger.warning("Refund of %s credits skipped: user %s not found", cost, user_id)
        return

    await record_transaction(
        user_id=user_id,
        amount=cost,
        action_type=action_type,
        job_id=job_id,
        balance_after=doc["credits_balance"],
    )


async def reverse_unrecorded_charge(user_id: PydanticObjectId, cost: float) -> None:
    """Undo a deduction whose ledger row was never written — balance only, no row.

    The request paths deduct, create the job, and ledger the charge **last**. So when
    their compensating ``except`` runs, the charge was never recorded, and writing a
    refund row would leave a lone positive movement in the history: a credit the user
    appears to have been granted out of nowhere. A deduction and its reversal that
    both leave no trace are, correctly, invisible.

    Everywhere the charge *was* ledgered, use :func:`refund_credits` instead, so the
    money that moved is money the user can see.
    """
    if cost <= 0:
        raise ValueError("cost must be positive")

    await User.get_pymongo_collection().update_one({"_id": user_id}, {"$inc": {"credits_balance": cost}})


async def amount_owed_for_job(job_id: str) -> float:
    """What is still owed back for ``job_id``: charges taken, less refunds already made.

    Charges are negative and refunds positive in the ledger, so the sum is the net
    movement and its negation is the outstanding debt. Clamped at zero — a job
    refunded past what it was charged owes nothing, and feeding a negative back into
    :func:`refund_credits` would charge the user instead.
    """
    if not job_id:
        return 0.0

    rows = await CreditTransaction.find(CreditTransaction.job_id == job_id).to_list()
    return max(0.0, -sum(row.amount for row in rows))


async def refund_failed_job(job) -> None:
    """Give back whatever a failed job was charged and has not already been returned.

    Idempotent by construction: the refund it writes is itself a ledger row, so a
    second call finds nothing owed. That is what lets the blanket "refund on failure"
    coexist with the handlers that already refund their own partial work (full-song
    sections, mastering pre-flight, voice training) without paying twice.

    A free job — an edit, an export — has no charges and so gets nothing, rather than
    having credits minted for it.
    """
    if job.status is not JobStatus.FAILED:
        # Refunding a job that succeeded would be a straight giveaway; refuse rather
        # than trust the caller wired this to the right lifecycle transition.
        raise ValueError(f"refund_failed_job called for a {job.status.value} job ({job.id})")

    owed = await amount_owed_for_job(str(job.id))

    if owed <= 0:
        return

    await refund_credits(job.user_id, owed, action_type=f"{job.job_type}_refund", job_id=str(job.id))


async def record_transaction(
    *,
    user_id: PydanticObjectId,
    amount: float,
    action_type: str,
    job_id: str,
    balance_after: float,
) -> CreditTransaction:
    """Append one movement to the credit ledger."""
    txn = CreditTransaction(
        user_id=user_id,
        amount=amount,
        action_type=action_type,
        job_id=job_id,
        balance_after=balance_after,
    )
    await txn.insert()
    return txn


async def get_recent_transactions(user_id: PydanticObjectId, limit: int = HISTORY_LIMIT) -> list[CreditTransaction]:
    """The user's most recent credit movements, newest first.

    ``_id`` breaks ties: BSON datetimes have millisecond resolution, so two
    movements in the same millisecond would otherwise sort unstably.
    """
    return (
        await CreditTransaction.find(CreditTransaction.user_id == user_id)
        .sort([("created_at", DESCENDING), ("_id", DESCENDING)])
        .limit(limit)
        .to_list()
    )
