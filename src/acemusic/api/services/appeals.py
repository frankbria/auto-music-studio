"""Appeals of moderation decisions (US-27.4).

A creator appeals the latest removal or content-warning flag on their own clip. Admins
uphold it, reverse it (restoring the clip) or ask for more information; each outcome records
a notice for the creator and a moderation log entry. Status changes are conditional ``$set``s
on an open appeal, so two admins deciding at once cannot both win.
"""

from datetime import datetime
from typing import Literal

from beanie import PydanticObjectId, UpdateResponse
from beanie.operators import In
from fastapi import HTTPException, status
from pydantic import BaseModel
from pymongo.errors import DuplicateKeyError

from ..models import (
    OPEN_APPEAL_STATUSES,
    AppealStatus,
    Clip,
    ClipAppeal,
    ModerationLogEntry,
    NotificationEvent,
    User,
    VisibilityState,
)
from ..models.clip_appeal import AppealedAction
from ..models.common import utcnow
from .clips import get_owned_clip
from .common import coerce_object_id
from .moderation import log_action

AppealDecision = Literal["uphold", "reverse", "request_info"]
QueueFilter = Literal["open", "all"]

MAX_APPEALS = 500
_DECISION_STATUS: dict[AppealDecision, AppealStatus] = {
    "uphold": "upheld",
    "reverse": "reversed",
    "request_info": "info_requested",
}


class AppealView(BaseModel):
    id: str
    clip_id: str
    action: AppealedAction
    reason: str
    context: str | None
    status: AppealStatus
    admin_note: str | None
    created_at: datetime
    decided_at: datetime | None

    @classmethod
    def of(cls, appeal: ClipAppeal) -> "AppealView":
        return cls(
            id=str(appeal.id),
            clip_id=str(appeal.clip_id),
            action=appeal.action,
            reason=appeal.reason,
            context=appeal.context,
            status=appeal.status,
            admin_note=appeal.admin_note,
            created_at=appeal.created_at,
            decided_at=appeal.decided_at,
        )


class AppealQueueItem(AppealView):
    clip_title: str | None
    clip_deleted: bool
    creator_id: str
    creator_name: str | None
    action_reason: str | None
    action_at: datetime | None


async def submit_appeal(clip_id: str, user_id: str, reason: str, context: str | None) -> ClipAppeal:
    """404 not the caller's clip, 400 nothing to appeal, 409 this decision was already appealed."""
    clip = await get_owned_clip(clip_id, user_id)
    action = await _appealable_action(clip)
    if action is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="This clip has no moderation decision to appeal."
        )
    appeal = ClipAppeal(
        clip_id=clip.id, user_id=clip.user_id, action_id=action.id, action=action.action, reason=reason, context=context
    )
    try:
        await appeal.insert()
    except DuplicateKeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="You have already appealed this decision."
        ) from exc
    return appeal


async def _appealable_action(clip: Clip) -> ModerationLogEntry | None:
    """The decision currently in force on the clip: its latest removal, else its latest flag."""
    if clip.removed_at is not None:
        action = "remove"
    elif clip.content_warning:
        action = "flag"
    else:
        return None
    return (
        await ModerationLogEntry.find({"target_type": "clip", "target_id": str(clip.id), "action": action})
        .sort(-ModerationLogEntry.created_at, -ModerationLogEntry.id)
        .first_or_none()
    )


async def answer_info_request(clip_id: str, user_id: str, context: str) -> ClipAppeal:
    """Add the requested information and send the appeal back to the queue; 409 if none was requested."""
    clip = await get_owned_clip(clip_id, user_id)
    requested = (
        await ClipAppeal.find({"clip_id": clip.id, "status": "info_requested"})
        .sort(-ClipAppeal.created_at)
        .first_or_none()
    )
    appeal = None
    if requested is not None:
        # Appended, not replaced: the admin still sees what the creator first wrote.
        combined = f"{requested.context}\n\n{context}" if requested.context else context
        appeal = await ClipAppeal.find_one({"_id": requested.id, "status": "info_requested"}).update(
            {"$set": {"context": combined, "status": "pending"}}, response_type=UpdateResponse.NEW_DOCUMENT
        )
    if appeal is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="No more information was requested for this appeal."
        )
    return appeal


async def list_user_appeals(user_id: str) -> list[ClipAppeal]:
    return (
        await ClipAppeal.find({"user_id": PydanticObjectId(user_id)})
        .sort(-ClipAppeal.created_at)
        .limit(MAX_APPEALS)
        .to_list()
    )


async def list_queue(which: QueueFilter) -> list[AppealQueueItem]:
    """Open appeals oldest first (first come, first served); ``all`` is newest first."""
    if which == "open":
        query = ClipAppeal.find(In(ClipAppeal.status, list(OPEN_APPEAL_STATUSES))).sort(+ClipAppeal.created_at)
    else:
        query = ClipAppeal.find_all().sort(-ClipAppeal.created_at)
    appeals = await query.limit(MAX_APPEALS).to_list()
    clips = {c.id: c for c in await Clip.find(In(Clip.id, [a.clip_id for a in appeals])).to_list()}
    users = {u.id: u for u in await User.find(In(User.id, list({a.user_id for a in appeals}))).to_list()}
    actions = {
        e.id: e
        for e in await ModerationLogEntry.find(In(ModerationLogEntry.id, [a.action_id for a in appeals])).to_list()
    }
    items = []
    for appeal in appeals:
        clip, creator, action = clips.get(appeal.clip_id), users.get(appeal.user_id), actions.get(appeal.action_id)
        items.append(
            AppealQueueItem(
                **AppealView.of(appeal).model_dump(),
                clip_title=clip.title if clip else None,
                clip_deleted=clip is None,
                creator_id=str(appeal.user_id),
                creator_name=(creator.display_name or creator.name or creator.email) if creator else None,
                action_reason=action.reason if action else None,
                action_at=action.created_at if action else None,
            )
        )
    return items


async def decide(actor_id: str, appeal_id: str, decision: AppealDecision, note: str | None) -> ClipAppeal:
    """404 unknown appeal, 409 already upheld or reversed."""
    oid = coerce_object_id(appeal_id)
    if oid is None:
        raise _appeal_not_found()
    new_status = _DECISION_STATUS[decision]
    updates: dict = {"status": new_status, "admin_note": note}
    if decision != "request_info":
        updates.update(decided_at=utcnow(), decided_by=PydanticObjectId(actor_id))
    appeal = await ClipAppeal.find_one({"_id": oid, "status": {"$in": list(OPEN_APPEAL_STATUSES)}}).update(
        {"$set": updates}, response_type=UpdateResponse.NEW_DOCUMENT
    )
    if appeal is None:
        if await ClipAppeal.get(oid) is None:
            raise _appeal_not_found()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This appeal has already been decided.")

    clip = await Clip.get(appeal.clip_id)
    if decision == "reverse" and clip is not None:
        await _restore(clip, appeal)
    await NotificationEvent(
        user_id=appeal.user_id,
        clip_id=appeal.clip_id,
        event_type=f"moderation_appeal_{new_status}",
        channel="in_app",
        payload={
            "appeal_id": str(appeal.id),
            "clip_id": str(appeal.clip_id),
            "title": clip.title if clip else None,
            "note": note,
        },
    ).insert()
    await log_action(
        actor_id,
        f"appeal_{new_status}",
        "clip",
        str(appeal.clip_id),
        note,
        {"appeal_id": str(appeal.id), "appealed_action": appeal.action},
    )
    return appeal


async def _restore(clip: Clip, appeal: ClipAppeal) -> None:
    """Undo the appealed decision, unless a newer one has replaced it since the appeal was filed."""
    in_force = await _appealable_action(clip)
    if in_force is None or in_force.id != appeal.action_id:
        return
    if appeal.action == "flag":
        restore: dict = {"content_warning": False}
    else:
        restore = {"removed_at": None}
        # Removals logged before the snapshot existed stay private; the owner re-publishes.
        previous = in_force.details.get("previous_visibility")
        if previous is not None:
            restore.update(visibility=previous, is_public=previous == VisibilityState.PUBLIC.value)
    await Clip.find_one({"_id": clip.id, "removed_at": clip.removed_at}).update({"$set": restore})


def _appeal_not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appeal not found.")
