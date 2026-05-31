"""User document model (US-8.2)."""

from datetime import datetime

from beanie import Document
from pydantic import EmailStr, Field
from pymongo import ASCENDING, IndexModel

from .common import utcnow


class User(Document):
    """A platform user. ``email`` is validated and uniquely indexed."""

    email: EmailStr
    name: str
    oauth_provider: str | None = None
    oauth_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime | None = None

    class Settings:
        name = "users"
        indexes = [IndexModel([("email", ASCENDING)], unique=True)]
