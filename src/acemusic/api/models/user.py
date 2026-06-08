"""User document model (US-8.2)."""

from datetime import datetime

from beanie import Document
from pydantic import EmailStr, Field
from pymongo import ASCENDING, IndexModel

from .common import utcnow


class User(Document):
    """A platform user. ``email`` is validated and uniquely indexed.

    ``name`` is the raw display name reported by the OAuth provider; ``display_name``
    is the user-editable profile name (defaulted from ``name`` on first login).
    ``handle`` is the unique, user-chosen public identifier (US-8.4).
    """

    email: EmailStr
    name: str
    oauth_provider: str | None = None
    oauth_id: str | None = None
    subscription_tier: str = "free"
    # Profile fields (US-8.4). All optional so existing/OAuth-created users remain
    # valid; ``handle`` stays null until the user claims one.
    display_name: str | None = None
    handle: str | None = None
    bio: str | None = None
    style_tags: list[str] = Field(default_factory=list)
    avatar_url: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime | None = None

    class Settings:
        name = "users"
        indexes = [
            IndexModel([("email", ASCENDING)], unique=True),
            # Enforce one account per OAuth identity. The index is *partial* so it
            # only applies when both fields are present — otherwise the many users
            # with null oauth_provider/oauth_id (e.g. created before linking) would
            # all collide on a single (null, null) key under a plain unique index.
            IndexModel(
                [("oauth_provider", ASCENDING), ("oauth_id", ASCENDING)],
                unique=True,
                partialFilterExpression={
                    "oauth_provider": {"$type": "string"},
                    "oauth_id": {"$type": "string"},
                },
            ),
            # Handles are globally unique. Partial (same reasoning as the OAuth
            # index): the many users with a null handle must not collide on a
            # single null key under a plain unique index.
            IndexModel(
                [("handle", ASCENDING)],
                unique=True,
                partialFilterExpression={"handle": {"$type": "string"}},
            ),
        ]
