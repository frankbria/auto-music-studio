"""Workspace document model (US-8.2)."""

from datetime import datetime

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, IndexModel

from .common import utcnow


class Workspace(Document):
    """A user-owned container for clips. ``is_default`` marks the auto-created one."""

    name: str
    user_id: PydanticObjectId
    is_default: bool = False
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime | None = None

    class Settings:
        name = "workspaces"
        indexes = [
            IndexModel([("user_id", ASCENDING)]),
            # At most one default workspace per user. The partial filter scopes
            # uniqueness to ``is_default == True`` so a user may still hold many
            # non-default workspaces. This makes the lazy "get-or-create default"
            # in the generation service race-safe: a concurrent double-insert
            # fails the unique index instead of creating two defaults.
            IndexModel(
                [("user_id", ASCENDING), ("is_default", ASCENDING)],
                unique=True,
                partialFilterExpression={"is_default": True},
            ),
        ]
