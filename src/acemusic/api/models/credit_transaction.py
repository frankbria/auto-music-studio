"""Credit transaction document model (US-9.6).

An append-only ledger of credit movements. Each successful deduction at
job-queue time writes one row; the credits endpoint serves usage history from
it. ``amount`` is signed (negative for deductions) so future credit grants and
refunds fit the same shape without a schema change.
"""

from datetime import datetime

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, DESCENDING, IndexModel

from .common import utcnow


class CreditTransaction(Document):
    """One credit movement on a user's balance."""

    user_id: PydanticObjectId
    amount: float
    action_type: str
    job_id: str
    # Balance immediately after this movement, denormalised from the atomic
    # update so history rows are self-describing without replaying the ledger.
    balance_after: float
    created_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "credit_transactions"
        indexes = [
            # Serves the "this user's history, newest first" query entirely
            # from the index (same pattern as Clip's workspace listing).
            IndexModel([("user_id", ASCENDING), ("created_at", DESCENDING)]),
        ]
