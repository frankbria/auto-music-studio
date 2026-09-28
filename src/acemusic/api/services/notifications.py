"""The creator-facing read side of ``NotificationEvent`` (#537).

Moderation, appeals, voice training and distribution record events; this lists a user's own
events newest first and marks them read. "Read" is ``delivered_at``: the in-app inbox is the
delivery channel.
"""

from datetime import datetime, timezone

from beanie import PydanticObjectId
from pydantic import BaseModel

from ..models import NotificationEvent
from ..models.common import utcnow

MAX_PAGE = 100


class NotificationView(BaseModel):
    id: str
    event_type: str
    channel: str
    clip_id: str | None
    release_id: str | None
    voice_model_id: str | None
    payload: dict
    read: bool
    created_at: datetime

    @classmethod
    def of(cls, event: NotificationEvent) -> "NotificationView":
        return cls(
            id=str(event.id),
            event_type=event.event_type,
            channel=event.channel,
            clip_id=_str(event.clip_id),
            release_id=_str(event.release_id),
            voice_model_id=_str(event.voice_model_id),
            payload=event.payload,
            read=event.delivered_at is not None,
            # Mongo hands datetimes back naive; the web parses a naive ISO string as local time.
            created_at=event.created_at.replace(tzinfo=timezone.utc),
        )


def _str(oid: PydanticObjectId | None) -> str | None:
    return None if oid is None else str(oid)


async def list_for_user(user_id: str, limit: int, offset: int) -> tuple[list[NotificationEvent], bool, int]:
    """One page of the user's events newest first, whether more follow, and the unread total."""
    oid = PydanticObjectId(user_id)
    page = (
        await NotificationEvent.find({"user_id": oid})
        .sort(-NotificationEvent.created_at, -NotificationEvent.id)
        .skip(offset)
        .limit(limit + 1)
        .to_list()
    )
    unread = await NotificationEvent.find({"user_id": oid, "delivered_at": None}).count()
    return page[:limit], len(page) > limit, unread


async def mark_read(user_id: str, ids: list[PydanticObjectId] | None) -> int:
    """Stamp ``delivered_at`` on the user's unread events (``ids`` None = all). Returns how many changed."""
    query: dict = {"user_id": PydanticObjectId(user_id), "delivered_at": None}
    if ids is not None:
        query["_id"] = {"$in": ids}
    result = await NotificationEvent.find(query).update({"$set": {"delivered_at": utcnow()}})
    return result.modified_count
