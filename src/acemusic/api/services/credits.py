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

_COSTS = {"song": SONG_COST, "sound": SOUND_COST}

# History page size for GET /users/me/credits.
HISTORY_LIMIT = 50


def get_cost(mode: str) -> float:
    """Credit cost of one generation in ``mode``. Raises for unknown modes."""
    try:
        return _COSTS[mode]
    except KeyError:
        raise ValueError(f"Unknown generation mode: {mode!r}") from None


async def deduct_credits(user_id: PydanticObjectId, cost: float) -> float | None:
    """Atomically deduct ``cost`` from the user's balance.

    A single ``find_one_and_update`` filtered on ``credits_balance >= cost``,
    so two concurrent requests racing over the last credit are serialised by
    MongoDB — exactly one matches and decrements; the loser matches nothing.
    Returns the balance *after* deduction, or ``None`` if the balance was
    insufficient (or the user does not exist).
    """
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
