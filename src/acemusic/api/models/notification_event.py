"""Notification event document model (US-13.6).

Records a notification-worthy distribution event (a channel went ``live`` or was
``rejected``) so it can be delivered later. This is deliberately just the
*recorder*: actual delivery (email/push/in-app) is out of scope for US-13.6, so
``delivered_at`` stays null and a future delivery worker fills it in.
"""

from datetime import datetime

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, DESCENDING, IndexModel

from .common import utcnow


class NotificationEvent(Document):
    """A recorded status-change event awaiting (future) delivery."""

    user_id: PydanticObjectId
    release_id: PydanticObjectId
    event_type: str  # e.g. "status_live", "status_rejected"
    channel: str
    payload: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)
    delivered_at: datetime | None = None  # set by a future delivery worker

    class Settings:
        name = "notification_events"
        indexes = [
            # Serves "this user's notifications, newest first".
            IndexModel([("user_id", ASCENDING), ("created_at", DESCENDING)]),
        ]
