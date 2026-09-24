"""The admin moderation dashboard (US-27.3): review queue, clip and user actions, audit log.

Actions are bulk-native and per-target: a malformed or unknown id fails in its own
result instead of failing the batch, and every target acted on gets one log entry.
Writes are targeted ``$set`` updates, never whole-document saves, so an action cannot
revert a concurrent edit to the same clip or user.
"""

from datetime import datetime
from typing import Literal

from beanie import PydanticObjectId
from beanie.operators import In
from pydantic import BaseModel

from ..auth.services import revoke_all_user_tokens
from ..models import Clip, ClipReport, ModerationLogEntry, NotificationEvent, User, Video, VisibilityState
from ..models.common import utcnow
from .common import coerce_object_id

ClipAction = Literal["approve", "remove", "flag"]
UserAction = Literal["warn", "ban"]
QueueSource = Literal["report", "automated"]

MAX_QUEUE_ITEMS = 500
MAX_LOG_LIMIT = 500
CATEGORY_SEVERITY = {"inappropriate": 3, "copyright": 2, "spam": 1, "other": 1}
AUTOMATED_SEVERITY = 3


class QueueItem(BaseModel):
    clip_id: str
    clip_deleted: bool
    title: str | None
    style_tags: list[str]
    creator_id: str | None
    creator_name: str | None
    creator_banned: bool
    visibility: VisibilityState | None
    content_warning: bool
    report_count: int
    categories: dict[str, int]
    moderation_flags: list[str]
    sources: list[QueueSource]
    severity: int
    latest_at: datetime


class ActionResult(BaseModel):
    ok: bool
    detail: str | None = None


async def get_queue() -> list[QueueItem]:
    """One item per clip with open reports and/or unreviewed automated flags, most urgent first."""
    groups = await ClipReport.aggregate(
        [
            {"$match": {"resolved_at": None}},
            {
                "$group": {
                    "_id": {"clip_id": "$clip_id", "category": "$category"},
                    "count": {"$sum": 1},
                    "latest": {"$max": "$created_at"},
                }
            },
        ]
    ).to_list()
    reports: dict[PydanticObjectId, dict] = {}
    for group in groups:
        entry = reports.setdefault(group["_id"]["clip_id"], {"categories": {}, "latest": group["latest"]})
        entry["categories"][group["_id"]["category"]] = group["count"]
        entry["latest"] = max(entry["latest"], group["latest"])

    flagged = (
        await Clip.find({"moderation_flags": {"$type": "string"}, "moderation_reviewed_at": None})
        .sort(-Clip.created_at)
        .limit(MAX_QUEUE_ITEMS)
        .to_list()
    )
    clips = {clip.id: clip for clip in flagged}
    missing = [cid for cid in reports if cid not in clips]
    if missing:
        clips.update({clip.id: clip for clip in await Clip.find(In(Clip.id, missing)).to_list()})
    creators = {
        user.id: user
        for user in await User.find(In(User.id, list({clip.user_id for clip in clips.values()}))).to_list()
    }

    items = [
        _queue_item(clip_id, clips.get(clip_id), reports.get(clip_id), creators)
        for clip_id in {*reports, *(c.id for c in flagged)}
    ]
    items.sort(key=lambda i: (i.report_count, i.severity, i.latest_at), reverse=True)
    return items[:MAX_QUEUE_ITEMS]


def _queue_item(
    clip_id: PydanticObjectId, clip: Clip | None, report: dict | None, creators: dict[PydanticObjectId, User]
) -> QueueItem:
    categories = report["categories"] if report else {}
    flags = clip.moderation_flags if clip is not None and clip.moderation_reviewed_at is None else []
    sources: list[QueueSource] = (["report"] if categories else []) + (["automated"] if flags else [])
    severity = max(
        [CATEGORY_SEVERITY.get(c, 1) for c in categories] + ([AUTOMATED_SEVERITY] if flags else []), default=0
    )
    creator = creators.get(clip.user_id) if clip is not None else None
    return QueueItem(
        clip_id=str(clip_id),
        clip_deleted=clip is None,
        title=clip.title if clip else None,
        style_tags=clip.style_tags if clip else [],
        creator_id=str(clip.user_id) if clip else None,
        creator_name=(creator.display_name or creator.name or creator.email) if creator else None,
        creator_banned=bool(creator and creator.banned_at),
        visibility=clip.visibility if clip else None,
        content_warning=bool(clip and clip.content_warning),
        report_count=sum(categories.values()),
        categories=categories,
        moderation_flags=flags,
        sources=sources,
        severity=severity,
        latest_at=report["latest"] if report else clip.created_at,
    )


async def act_on_clip(actor_id: str, action: ClipAction, clip_id: str, reason: str | None) -> ActionResult:
    oid = coerce_object_id(clip_id)
    if oid is None:
        return ActionResult(ok=False, detail="Invalid clip id.")
    now = utcnow()
    clip = await Clip.get(oid)
    details: dict = {}
    if clip is None:
        # A deleted clip's orphaned reports can still be dismissed, and nothing else.
        resolved = await _resolve_reports(oid, now) if action == "approve" else 0
        if not resolved:
            return ActionResult(ok=False, detail="Clip not found.")
    else:
        updates: dict = {"moderation_reviewed_at": now}
        if action == "remove":
            # US-27.4: a reversed appeal restores the visibility recorded here.
            details["previous_visibility"] = clip.visibility.value
            updates.update(visibility=VisibilityState.PRIVATE, is_public=False, removed_at=now)
        elif action == "flag":
            updates["content_warning"] = True
        await clip.set(updates)
        resolved = await _resolve_reports(oid, now)
        if action == "remove":
            await NotificationEvent(
                user_id=clip.user_id,
                clip_id=clip.id,
                event_type="moderation_clip_removed",
                channel="in_app",
                payload={"clip_id": str(clip.id), "title": clip.title, "reason": reason},
            ).insert()
    await log_action(actor_id, action, "clip", str(oid), reason, {"reports_resolved": resolved, **details})
    return ActionResult(ok=True)


async def _resolve_reports(clip_id: PydanticObjectId, now: datetime) -> int:
    result = await ClipReport.find({"clip_id": clip_id, "resolved_at": None}).update({"$set": {"resolved_at": now}})
    return result.modified_count


async def act_on_user(actor_id: str, action: UserAction, user_id: str, reason: str | None) -> ActionResult:
    oid = coerce_object_id(user_id)
    if oid is None:
        return ActionResult(ok=False, detail="Invalid user id.")
    user = await User.get(oid)
    if user is None:
        return ActionResult(ok=False, detail="User not found.")

    if action == "warn":
        await NotificationEvent(
            user_id=oid, event_type="moderation_warning", channel="in_app", payload={"reason": reason}
        ).insert()
        details: dict = {}
    else:
        if str(oid) == actor_id:
            return ActionResult(ok=False, detail="You cannot ban yourself.")
        details = await _ban(user)
    await log_action(actor_id, action, "user", str(oid), reason, details)
    return ActionResult(ok=True)


async def _ban(user: User) -> dict:
    now = utcnow()
    if user.banned_at is None:
        await user.set({"banned_at": now})
    await revoke_all_user_tokens(user.id)
    clips = await Clip.find({"user_id": user.id, "visibility": {"$ne": VisibilityState.PRIVATE.value}}).update(
        {"$set": {"visibility": VisibilityState.PRIVATE.value, "is_public": False, "removed_at": now}}
    )
    videos = await Video.find({"user_id": user.id, "published": True}).update({"$set": {"published": False}})
    return {"clips_removed": clips.modified_count, "videos_unpublished": videos.modified_count}


async def log_screening_rules_update(actor_id: str, before: dict, after: dict) -> None:
    await log_action(
        actor_id, "update_screening_rules", "screening_rules", None, None, {"before": before, "after": after}
    )


async def list_log(limit: int) -> list[ModerationLogEntry]:
    return (
        await ModerationLogEntry.find_all()
        .sort(-ModerationLogEntry.created_at, -ModerationLogEntry.id)
        .limit(limit)
        .to_list()
    )


async def log_action(
    actor_id: str, action: str, target_type: str, target_id: str | None, reason: str | None, details: dict
) -> None:
    await ModerationLogEntry(
        actor_id=PydanticObjectId(actor_id),
        action=action,
        target_type=target_type,
        target_id=target_id,
        reason=reason,
        details=details,
    ).insert()
