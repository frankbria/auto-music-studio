"""A play, like or share of a public clip (#656).

The unique (clip, kind, actor, bucket) index is the counting rule: a play counts once per listener per hour and a
share once per user per day (``bucket`` is that hour or day), and a like once per user (``bucket`` is empty). A row
that inserts is one more count; a duplicate is not. Trending sums the rows inside its window.
"""

from datetime import datetime
from typing import Literal

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, DESCENDING, IndexModel

from .common import utcnow

EngagementKind = Literal["play", "like", "share"]


class ClipEngagement(Document):
    clip_id: PydanticObjectId
    kind: EngagementKind
    #: The user id, or ``ip:<address>`` for a signed-out listener.
    actor: str
    bucket: str = ""
    created_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "clip_engagements"
        indexes = [
            IndexModel(
                [("clip_id", ASCENDING), ("kind", ASCENDING), ("actor", ASCENDING), ("bucket", ASCENDING)],
                unique=True,
            ),
            IndexModel([("created_at", DESCENDING), ("clip_id", ASCENDING)]),
        ]
