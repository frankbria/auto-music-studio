"""Appeals of moderation decisions (US-27.4).

A creator appeals the latest removal or content-warning flag on their own clip, or the unpublish in force on one
of their videos (#623). Admins
uphold it, reverse it (restoring the clip) or ask for more information; each outcome records
a notice for the creator and a moderation log entry. Status changes are conditional ``$set``s
on an open appeal, so two admins deciding at once cannot both win.
"""

import logging
from datetime import datetime
from typing import Literal

from beanie import PydanticObjectId, SortDirection, UpdateResponse
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
    Video,
    VisibilityState,
)
from ..models.clip_appeal import AppealedAction
from ..models.common import utcnow
from ..settings import ApiSettings
from . import moderation, releases as release_service
from .clips import get_owned_clip
from .common import coerce_object_id
from .moderation import after_cursor, encode_cursor, log_action
from .video import get_owned_video

logger = logging.getLogger(__name__)

AppealDecision = Literal["uphold", "reverse", "request_info"]
QueueFilter = Literal["open", "all"]

MAX_APPEALS = 500
_SUPERSEDED = "A newer moderation decision has replaced the one appealed."
_DECISION_STATUS: dict[AppealDecision, AppealStatus] = {
    "uphold": "upheld",
    "reverse": "reversed",
    "request_info": "info_requested",
}


class AppealView(BaseModel):
    id: str
    clip_id: str
    # Set for an appeal of a video unpublish (#623); clip_id is then the video's song.
    video_id: str | None = None
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
            video_id=str(appeal.video_id) if appeal.video_id else None,
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
    # #543: a newer moderation decision replaced the appealed one, so only upholding (closing) it is left.
    superseded: bool


async def submit_appeal(clip_id: str, user_id: str, reason: str, context: str | None) -> ClipAppeal:
    """404 not the caller's clip, 400 nothing to appeal, 409 this decision was already appealed."""
    clip = await get_owned_clip(clip_id, user_id)
    action = await _appealable_action(clip)
    if action is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="This clip has no moderation decision to appeal."
        )
    return await _insert(
        ClipAppeal(
            clip_id=clip.id,
            user_id=clip.user_id,
            action_id=action.id,
            action=action.action,
            reason=reason,
            context=context,
        )
    )


async def submit_video_appeal(video_id: str, user_id: str, reason: str, context: str | None) -> ClipAppeal:
    """Appeal the unpublish in force on your own video (#623). 404 not yours, 400 nothing to appeal, 409 appealed.

    A takedown stamped by the owner's ban is not appealable here: the ban is contested as a whole (#581).
    """
    video = await get_owned_video(video_id, user_id)
    if video is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found.")
    action_id = await _video_in_force(video)
    if action_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="This video has no moderation decision to appeal."
        )
    return await _insert(
        ClipAppeal(
            clip_id=video.clip_id,
            video_id=video.id,
            user_id=video.user_id,
            action_id=action_id,
            action="unpublish",
            reason=reason,
            context=context,
        )
    )


async def _insert(appeal: ClipAppeal) -> ClipAppeal:
    """The unique ``action_id`` index is the one-appeal-per-decision rule."""
    try:
        await appeal.insert()
    except DuplicateKeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="You have already appealed this decision."
        ) from exc
    return appeal


async def _video_in_force(video: Video) -> PydanticObjectId | None:
    """The unpublish entry in force on the video (moderation.unpublishes_in_force), if any."""
    in_force = await moderation.unpublishes_in_force([video.id])
    return PydanticObjectId(next(iter(in_force))) if in_force else None


def _in_force_kind(clip: Clip) -> AppealedAction | None:
    if clip.removed_at is not None:
        return "remove"
    return "flag" if clip.content_warning else None


async def _appealable_action(clip: Clip) -> ModerationLogEntry | None:
    """The decision currently in force on the clip: its latest removal, else its latest flag."""
    action = _in_force_kind(clip)
    if action is None:
        return None
    return (
        await ModerationLogEntry.find({"target_type": "clip", "target_id": str(clip.id), "action": action})
        .sort(-ModerationLogEntry.created_at, -ModerationLogEntry.id)
        .first_or_none()
    )


async def _in_force_actions(clips: list[Clip]) -> dict[PydanticObjectId, PydanticObjectId]:
    """Each clip's in-force decision id (see ``_appealable_action``), in one read; clips with none are absent."""
    kinds = {str(c.id): _in_force_kind(c) for c in clips}
    ids = [clip_id for clip_id, kind in kinds.items() if kind]
    rows = await ModerationLogEntry.aggregate(
        [
            {"$match": {"target_type": "clip", "target_id": {"$in": ids}, "action": {"$in": ["remove", "flag"]}}},
            {"$sort": {"created_at": -1, "_id": -1}},
            {"$group": {"_id": {"target_id": "$target_id", "action": "$action"}, "entry_id": {"$first": "$_id"}}},
        ]
    ).to_list()
    return {
        PydanticObjectId(row["_id"]["target_id"]): row["entry_id"]
        for row in rows
        if row["_id"]["action"] == kinds[row["_id"]["target_id"]]
    }


def _is_superseded(subject: Clip | Video | None, appeal: ClipAppeal, in_force_id: PydanticObjectId | None) -> bool:
    return subject is not None and in_force_id != appeal.action_id


async def _appealed_videos(appeals: list[ClipAppeal]) -> tuple[dict[PydanticObjectId, Video], set[str]]:
    """The page's appealed videos still around, and the unpublish entries in force on them."""
    ids = [a.video_id for a in appeals if a.video_id]
    videos = {v.id: v for v in await Video.find(In(Video.id, ids)).to_list()}
    return videos, await moderation.unpublishes_in_force(list(videos))


def _queue_superseded(
    appeal: ClipAppeal,
    clip: Clip | None,
    clips_in_force: dict[PydanticObjectId, PydanticObjectId],
    videos: dict[PydanticObjectId, Video],
    videos_in_force: set[str],
) -> bool:
    if appeal.video_id is None:
        return _is_superseded(clip, appeal, clips_in_force.get(appeal.clip_id))
    return appeal.video_id in videos and str(appeal.action_id) not in videos_in_force


async def answer_info_request(clip_id: str, user_id: str, context: str) -> ClipAppeal:
    """Add the requested information and send the appeal back to the queue; 409 if none was requested."""
    clip = await get_owned_clip(clip_id, user_id)
    # Not the clip's videos' appeals: those share its clip_id and are answered on the video (#623).
    return await _answer({"clip_id": clip.id, "video_id": None}, context)


async def answer_video_info_request(video_id: str, user_id: str, context: str) -> ClipAppeal:
    """``answer_info_request`` for an appeal of a video unpublish (#623)."""
    video = await get_owned_video(video_id, user_id)
    if video is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found.")
    return await _answer({"video_id": video.id}, context)


async def _answer(query: dict, context: str) -> ClipAppeal:
    requested = (
        await ClipAppeal.find({**query, "status": "info_requested"}).sort(-ClipAppeal.created_at).first_or_none()
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


async def _page(query: dict, newest_first: bool, limit: int, cursor: str | None) -> tuple[list[ClipAppeal], str | None]:
    """A keyset page of appeals in ``(created_at, _id)`` order, plus the cursor for the next (None on the last)."""
    kind = "appeals_newest" if newest_first else "appeals_oldest"
    direction = SortDirection.DESCENDING if newest_first else SortDirection.ASCENDING
    rows = (
        await ClipAppeal.find(query, after_cursor(kind, cursor, newest_first))
        .sort([("created_at", direction), ("_id", direction)])
        .limit(limit + 1)
        .to_list()
    )
    page = rows[:limit]
    return page, encode_cursor(kind, (page[-1].created_at, str(page[-1].id))) if len(rows) > limit else None


async def list_user_appeals(user_id: str, limit: int, cursor: str | None) -> tuple[list[ClipAppeal], str | None]:
    return await _page({"user_id": PydanticObjectId(user_id)}, True, limit, cursor)


async def list_queue(which: QueueFilter, limit: int, cursor: str | None) -> tuple[list[AppealQueueItem], str | None]:
    """Open appeals oldest first (first come, first served); ``all`` is newest first."""
    if which == "open":
        appeals, next_cursor = await _page({"status": {"$in": list(OPEN_APPEAL_STATUSES)}}, False, limit, cursor)
    else:
        appeals, next_cursor = await _page({}, True, limit, cursor)
    clips = {c.id: c for c in await Clip.find(In(Clip.id, [a.clip_id for a in appeals])).to_list()}
    users = {u.id: u for u in await User.find(In(User.id, list({a.user_id for a in appeals}))).to_list()}
    actions = {
        e.id: e
        for e in await ModerationLogEntry.find(In(ModerationLogEntry.id, [a.action_id for a in appeals])).to_list()
    }
    in_force = await _in_force_actions(list(clips.values()))
    videos, videos_in_force = await _appealed_videos(appeals)
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
                superseded=_queue_superseded(appeal, clip, in_force, videos, videos_in_force),
            )
        )
    return items, next_cursor


async def decide(
    actor_id: str, appeal_id: str, decision: AppealDecision, note: str | None, settings: ApiSettings
) -> ClipAppeal:
    """404 unknown appeal, 409 already upheld or reversed, or a newer decision replaced it.

    A superseded appeal can still be upheld, which closes it: reversing it would undo the newer decision, and
    asking the creator for more about a decision no longer in force goes nowhere.
    """
    oid = coerce_object_id(appeal_id)
    existing = await ClipAppeal.get(oid) if oid is not None else None
    if existing is None:
        raise _appeal_not_found()
    clip, subject, in_force, in_force_id = await _load(existing)
    if decision != "uphold" and _is_superseded(subject, existing, in_force_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_SUPERSEDED)

    new_status = _DECISION_STATUS[decision]
    updates: dict = {"status": new_status, "admin_note": note}
    if decision != "request_info":
        updates.update(decided_at=utcnow(), decided_by=PydanticObjectId(actor_id))
    # The pre-claim state, not `existing`: a creator's answer landing before the claim must survive a rollback.
    claimed_from = await ClipAppeal.find_one({"_id": oid, "status": {"$in": list(OPEN_APPEAL_STATUSES)}}).update(
        {"$set": updates}, response_type=UpdateResponse.OLD_DOCUMENT
    )
    if claimed_from is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This appeal has already been decided.")
    appeal = claimed_from.model_copy(update=updates)
    await _apply_unless_superseded(claimed_from, appeal, subject, in_force, decision)
    restored = await _restore_releases(clip, appeal, in_force, decision, settings)
    await NotificationEvent(
        user_id=appeal.user_id,
        clip_id=appeal.clip_id,
        event_type=f"moderation_appeal_{new_status}",
        channel="in_app",
        payload={
            "appeal_id": str(appeal.id),
            "clip_id": str(appeal.clip_id),
            # A video appeal's outcome opens that video's appeal panel (#623).
            "video_id": str(appeal.video_id) if appeal.video_id else None,
            "title": clip.title if clip else None,
            "note": note,
        },
    ).insert()
    await log_action(
        actor_id,
        f"appeal_{new_status}",
        "video" if appeal.video_id else "clip",
        str(appeal.video_id or appeal.clip_id),
        note,
        {"appeal_id": str(appeal.id), "appealed_action": appeal.action, **restored},
    )
    return appeal


async def _load(
    appeal: ClipAppeal,
) -> tuple[Clip | None, Clip | Video | None, ModerationLogEntry | None, PydanticObjectId | None]:
    """The appeal's song, what it appeals (that clip, or a video of it), and the decision in force on that: its log
    entry for a clip, which a reversal reads, and its id for either."""
    clip = await Clip.get(appeal.clip_id)
    if appeal.video_id is not None:
        video = await Video.get(appeal.video_id)
        return clip, video, None, await _video_in_force(video) if video else None
    in_force = await _appealable_action(clip) if clip is not None else None
    return clip, clip, in_force, in_force.id if in_force else None


async def _still_in_force(
    subject: Clip | Video, appeal: ClipAppeal, in_force: ModerationLogEntry | None, decision: AppealDecision
) -> bool:
    """A reversal undoes the decision here, only if no moderation action landed since it was read."""
    if isinstance(subject, Video):
        return await _video_still_in_force(subject, decision)
    clip = subject
    if decision == "request_info":
        return await Clip.find_one({"_id": clip.id, "moderation_reviewed_at": clip.moderation_reviewed_at}).exists()
    fields = {"content_warning": False} if appeal.action == "flag" else _undo_removal(in_force)
    return await _set_unless_moderated_since(clip, fields)


async def _video_still_in_force(video: Video, decision: AppealDecision) -> bool:
    """Reversal runs the admin restore (#571), which lifts only the takedown read and its edits' copies of it."""
    if decision == "request_info":
        # Both stamps: a re-unpublish keeps removed_at and only refreshes moderation_reviewed_at.
        return await Video.find_one(
            {"_id": video.id, "removed_at": video.removed_at, "moderation_reviewed_at": video.moderation_reviewed_at}
        ).exists()
    return await moderation.restore_video(video) is None


async def _apply_unless_superseded(
    claimed_from: ClipAppeal,
    appeal: ClipAppeal,
    subject: Clip | Video | None,
    in_force: ModerationLogEntry | None,
    decision: AppealDecision,
) -> None:
    """Applies a reversal to the clip, or 409s if a moderation action landed since the read (#587).

    A superseded decision must not be undone, and neither outcome may reach the creator, so the claimed appeal
    goes back to how it was. Owner edits that add a screening flag also reset the stamp checked here, so they
    earn the same 409; it is retryable and errs toward leaving the decision in force.
    """
    if decision == "uphold" or subject is None or await _still_in_force(subject, appeal, in_force, decision):
        return
    await ClipAppeal.find_one({"_id": claimed_from.id, "status": appeal.status}).update(
        {
            "$set": {
                "status": claimed_from.status,
                "admin_note": claimed_from.admin_note,
                "decided_at": claimed_from.decided_at,
                "decided_by": claimed_from.decided_by,
            }
        }
    )
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_SUPERSEDED)


def _reverses_a_removal(clip: Clip | None, appeal: ClipAppeal, decision: AppealDecision) -> bool:
    return decision == "reverse" and clip is not None and appeal.action == "remove"


async def _restore_releases(
    clip: Clip | None, appeal: ClipAppeal, in_force: ModerationLogEntry, decision: AppealDecision, settings: ApiSettings
) -> dict:
    """What the reversal's log entry records about the releases a reversed removal put back."""
    if not _reverses_a_removal(clip, appeal, decision):
        return {}
    releases = in_force.details.get("previous_release_visibility")
    if releases is None:
        return {}
    try:
        return await release_service.restore_releases(clip, releases, in_force.created_at, settings)
    except Exception:  # best-effort: the appeal is already decided, so a raise here could never be retried
        logger.exception("Restoring the releases of clip %s after a reversed removal failed", clip.id)
        return {"releases_restore_failed": True}


def _undo_removal(removal: ModerationLogEntry) -> dict:
    """Removals logged before the snapshot existed stay private; the owner re-publishes."""
    previous = removal.details.get("previous_visibility")
    if previous is None:
        return {"removed_at": None}
    return {"removed_at": None, "visibility": previous, "is_public": previous == VisibilityState.PUBLIC.value}


async def _set_unless_moderated_since(clip: Clip, fields: dict) -> bool:
    """Every moderation action stamps moderation_reviewed_at, so one landing after the read is not undone."""
    result = await Clip.find_one({"_id": clip.id, "moderation_reviewed_at": clip.moderation_reviewed_at}).update(
        {"$set": fields}
    )
    return bool(result.matched_count)


def _appeal_not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appeal not found.")
