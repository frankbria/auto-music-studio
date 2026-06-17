"""Credits service layer (US-9.6).

Module-level async functions (matching the other service modules) for the
credit cost table, atomic balance deduction, and the transaction ledger. The
layer raises plain exceptions, never ``HTTPException``, so it stays
transport-agnostic.
"""

from beanie import PydanticObjectId
from pymongo import DESCENDING, ReturnDocument

from ..models import CreditTransaction, User
from ..models.user import DEFAULT_CREDITS_BALANCE

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

# History page size for GET /users/me/credits.
HISTORY_LIMIT = 50


def get_cost(mode: str) -> float:
    """Credit cost of one generation in ``mode``. Raises for unknown modes."""
    try:
        return _COSTS[mode]
    except KeyError:
        raise ValueError(f"Unknown generation mode: {mode!r}") from None


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


async def refund_credits(user_id: PydanticObjectId, cost: float) -> None:
    """Compensating credit for a deduction whose job never got queued."""
    # Symmetric guard: a non-positive "refund" would silently deduct.
    if cost <= 0:
        raise ValueError("cost must be positive")
    await User.get_pymongo_collection().update_one(
        {"_id": user_id},
        {"$inc": {"credits_balance": cost}},
    )


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
