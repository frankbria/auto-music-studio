"""SoundCloud account-link document model (US-13.2).

Persists the OAuth tokens for a user's linked SoundCloud account so the platform
can upload tracks on their behalf. One connection per user (unique ``user_id``);
linking again upserts the same row. Tokens are stored as-is — they are
short-lived third-party credentials behind the DB's access controls, matching how
the platform stores other provider credentials.
"""

from datetime import datetime

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, IndexModel

from .common import utcnow


class SoundCloudConnection(Document):
    """A user's linked SoundCloud account with its OAuth tokens."""

    user_id: PydanticObjectId
    soundcloud_user_id: str
    soundcloud_username: str | None = None
    access_token: str
    refresh_token: str
    token_expires_at: datetime
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime | None = None

    class Settings:
        name = "soundcloud_connections"
        indexes = [
            # One SoundCloud link per user: re-linking upserts this row, and the
            # unique index makes a concurrent double-connect race-safe.
            IndexModel([("user_id", ASCENDING)], unique=True),
            IndexModel([("soundcloud_user_id", ASCENDING)]),
        ]
