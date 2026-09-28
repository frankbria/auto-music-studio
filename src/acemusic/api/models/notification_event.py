"""Notification event document model (US-13.6).

Records a notification-worthy event (a distribution channel went ``live`` or was
``rejected``, a voice model finished training, a moderation decision) for the
user it concerns. Delivery is the in-app inbox (#537, ``services/notifications``):
``delivered_at`` is set when the user reads it there.
"""

from datetime import datetime

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, DESCENDING, IndexModel

from .common import utcnow


class NotificationEvent(Document):
    """A recorded event for one user's in-app inbox."""

    user_id: PydanticObjectId

    # Exactly one of these identifies what the event is about. Two nullable keys
    # rather than a generic subject: the release path (US-21.x) is shipped and
    # working, and rewriting it to carry voice models is not what US-25.2 needs.
    release_id: PydanticObjectId | None = None
    voice_model_id: PydanticObjectId | None = None
    clip_id: PydanticObjectId | None = None

    event_type: str  # e.g. "status_live", "voice_training_complete", "moderation_clip_removed"
    channel: str
    payload: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)
    delivered_at: datetime | None = None  # set when the user reads it in the inbox

    class Settings:
        name = "notification_events"
        indexes = [
            # Serves "this user's notifications, newest first".
            IndexModel([("user_id", ASCENDING), ("created_at", DESCENDING)]),
        ]
