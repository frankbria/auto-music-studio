"""Refresh token document model (US-8.3).

Only the SHA-256 hash of a refresh token is ever persisted (``token_hash``), so a
database leak does not expose usable credentials. A TTL index on ``expires_at``
lets MongoDB reap expired tokens automatically; the service layer also checks
expiry/revocation on lookup for defense in depth.
"""

from datetime import datetime

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, IndexModel

from .common import utcnow


class RefreshToken(Document):
    """A stored refresh token (hashed) bound to a user."""

    token_hash: str
    user_id: PydanticObjectId
    expires_at: datetime
    revoked: bool = False
    created_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "refresh_tokens"
        indexes = [
            IndexModel([("token_hash", ASCENDING)], unique=True),
            IndexModel([("user_id", ASCENDING)]),
            # TTL index: MongoDB deletes documents once ``expires_at`` is in the
            # past (expireAfterSeconds=0 means "expire at the stored time").
            IndexModel([("expires_at", ASCENDING)], expireAfterSeconds=0),
        ]
