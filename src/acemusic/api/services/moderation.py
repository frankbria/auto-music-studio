"""The admin moderation dashboard (US-27.3): review queue, clip and user actions, audit log.

The queue also carries flagged videos, generated artwork and voice models (#539), each
with the actions that fit it (see ``CONTENT_ACTIONS``).

Actions are bulk-native and per-target: a malformed or unknown id fails in its own
result instead of failing the batch, and every target acted on gets one log entry.
Writes are targeted ``$set`` updates, never whole-document saves, so an action cannot
revert a concurrent edit to the same clip or user.
"""

import asyncio
import base64
import logging
from datetime import datetime
from typing import Literal

from beanie import PydanticObjectId
from beanie.operators import In
from fastapi import HTTPException, status
from pydantic import BaseModel, ConfigDict, NaiveDatetime, TypeAdapter

from acemusic.storage import get_storage_backend

from ..auth.services import revoke_all_user_tokens
from ..models import (
    ArtworkOption,
    Clip,
    ClipReport,
    Job,
    ModerationLogEntry,
    NotificationEvent,
    ReportCategory,
    User,
    Video,
    VisibilityState,
    VoiceModel,
)
from ..models.common import utcnow
from . import clips as clip_service, releases as release_service
from .common import coerce_object_id

logger = logging.getLogger(__name__)

ClipAction = Literal["approve", "remove", "flag"]
UserAction = Literal["warn", "ban"]
QueueSource = Literal["report", "automated"]
QueueSort = Literal["reports", "severity", "newest"]
# #539: screening flags outputs that aren't clips too; each type takes the actions that fit it.
ContentType = Literal["video", "artwork", "voice_model"]
ContentAction = Literal["approve", "unpublish", "restore", "drop"]
CONTENT_ACTIONS: dict[str, tuple[str, ...]] = {
    "video": ("approve", "unpublish", "restore"),
    "artwork": ("approve", "drop"),
    "voice_model": ("approve",),
}
_CONTENT_DOCS = {"video": Video, "artwork": ArtworkOption, "voice_model": VoiceModel}
_CONTENT_NOUNS = {"video": "video", "artwork": "artwork", "voice_model": "voice model"}
_UNREVIEWED = {"moderation_flags": {"$type": "string"}, "moderation_reviewed_at": None}

MAX_QUEUE_LIMIT = 500
MAX_LOG_LIMIT = 500
CATEGORY_SEVERITY = {"inappropriate": 3, "copyright": 2, "spam": 1, "other": 1}
AUTOMATED_SEVERITY = 3


class QueueItem(BaseModel):
    target_type: Literal["clip"] | ContentType = "clip"
    target_id: str
    # The clip itself, or the song a video or artwork was made for. None for a voice model.
    clip_id: str | None
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
    # A video or artwork job's prompt, or a voice model's description: the text screening flagged.
    description: str | None = None
    published: bool | None = None


# Keyset cursors (#540): the last row's sort key, so a page boundary survives rows being acted
# on (the queue shrinks) or logged (the log grows at the head) between requests. Each cursor
# leads with its kind: a reports key and a severity key have the same shape, and replaying
# one under the other sort would silently skip or repeat rows instead of failing. Times are
# NaiveDatetime because pymongo hands back naive UTC, and the keys are built from what it read.
def _cursor(kind: str, *key: type) -> TypeAdapter:
    return TypeAdapter(tuple[(Literal[kind], *key)], config=ConfigDict(strict=True))


_CURSORS: dict[str, TypeAdapter] = {
    "reports": _cursor("reports", int, int, NaiveDatetime, str, str),
    "severity": _cursor("severity", int, int, NaiveDatetime, str, str),
    "newest": _cursor("newest", NaiveDatetime, str, str),
    "log": _cursor("log", NaiveDatetime, str),
    # #543: the appeals lists, keyed on (created_at, id) like the log.
    "appeals_oldest": _cursor("appeals_oldest", NaiveDatetime, str),
    "appeals_newest": _cursor("appeals_newest", NaiveDatetime, str),
}


def encode_cursor(kind: str, key: tuple) -> str:
    return base64.urlsafe_b64encode(_CURSORS[kind].dump_json((kind, *key))).decode()


def _decode_cursor(kind: str, cursor: str) -> tuple:
    try:
        return _CURSORS[kind].validate_json(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))[1:]
    except ValueError:  # bad base64, bad JSON, a wrong shape and another kind's cursor are all ValueErrors
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Invalid cursor.")


def after_cursor(kind: str, cursor: str | None, newest_first: bool = True) -> dict:
    """The filter for rows past ``cursor`` in ``(created_at, _id)`` order; empty on the first page."""
    if not cursor:
        return {}
    at, last_id = _decode_cursor(kind, cursor)
    oid = coerce_object_id(last_id)
    if oid is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Invalid cursor.")
    past = "$lt" if newest_first else "$gt"
    return {"$or": [{"created_at": {past: at}}, {"created_at": at, "_id": {past: oid}}]}


def _queue_key(item: "QueueItem", sort: QueueSort) -> tuple:
    rank = {
        "reports": (item.report_count, item.severity, item.latest_at),
        "severity": (item.severity, item.report_count, item.latest_at),
        "newest": (item.latest_at,),
    }[sort]
    return (*rank, item.target_type, item.target_id)


class ActionResult(BaseModel):
    ok: bool
    detail: str | None = None


async def get_queue(
    sort: QueueSort = "reports",
    source: Literal["all"] | QueueSource = "all",
    category: Literal["all"] | ReportCategory = "all",
    limit: int = 100,
    cursor: str | None = None,
) -> tuple[list[QueueItem], str | None]:
    """One item per clip with open reports and/or unreviewed automated flags, and per flagged
    video, artwork option or voice model: a page of them in ``sort`` order, plus the cursor
    for the next page (None on the last)."""
    after = _decode_cursor(sort, cursor) if cursor else None
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

    flagged = await _unreviewed(Clip)
    videos = await _unreviewed(Video)
    artwork = await _unreviewed(ArtworkOption)
    voices = await _unreviewed(VoiceModel)
    clips = {clip.id: clip for clip in flagged}
    missing = {cid for cid in [*reports, *(d.clip_id for d in [*videos, *artwork])] if cid not in clips}
    if missing:
        clips.update({clip.id: clip for clip in await Clip.find(In(Clip.id, list(missing))).to_list()})
    owners = {clip.user_id for clip in clips.values()} | {d.user_id for d in [*videos, *artwork, *voices]}
    creators = {user.id: user for user in await User.find(In(User.id, list(owners))).to_list()}
    jobs = {job.id: job for job in await Job.find(In(Job.id, [d.job_id for d in [*videos, *artwork]])).to_list()}

    items = [
        _queue_item(clip_id, clips.get(clip_id), reports.get(clip_id), creators)
        for clip_id in {*reports, *(c.id for c in flagged)}
    ]
    for kind, docs in (("video", videos), ("artwork", artwork)):
        for doc in docs:
            job = jobs.get(doc.job_id)
            params = (job.input_params or {}) if job else {}
            # A replace_scene edit keeps its prompt inside the edit spec.
            prompt = params.get("prompt") or (params.get("edit") or {}).get("prompt")
            items.append(_content_item(kind, doc, clips.get(doc.clip_id), creators, prompt))
    items.extend(_content_item("voice_model", voice, None, creators, voice.description) for voice in voices)
    items = [
        i
        for i in items
        if (source == "all" or source in i.sources)
        and (category == "all" or i.categories.get(category, 0) > 0)
        and (after is None or _queue_key(i, sort) < after)
    ]
    items.sort(key=lambda i: _queue_key(i, sort), reverse=True)
    page = items[:limit]
    return page, encode_cursor(sort, _queue_key(page[-1], sort)) if len(items) > limit else None


# ponytail: every open report and unreviewed flag is read and ranked in memory on each page;
# move to a $unionWith aggregation that sorts and limits in Mongo if the backlog reaches thousands.
async def _unreviewed(document: type) -> list:
    return await document.find(_UNREVIEWED).to_list()


def _creator_name(creator: User | None) -> str | None:
    return (creator.display_name or creator.name or creator.email) if creator else None


def _content_item(
    kind: ContentType, doc, clip: Clip | None, creators: dict[PydanticObjectId, User], description: str | None
) -> QueueItem:
    creator = creators.get(doc.user_id)
    return QueueItem(
        target_type=kind,
        target_id=str(doc.id),
        clip_id=str(doc.clip_id) if kind != "voice_model" else None,
        clip_deleted=kind != "voice_model" and clip is None,
        title=doc.name if kind == "voice_model" else (clip.title if clip else None),
        style_tags=clip.style_tags if clip else [],
        creator_id=str(doc.user_id),
        creator_name=_creator_name(creator),
        creator_banned=bool(creator and creator.banned_at),
        visibility=None,
        content_warning=False,
        report_count=0,
        categories={},
        moderation_flags=doc.moderation_flags,
        sources=["automated"],
        severity=AUTOMATED_SEVERITY,
        latest_at=doc.created_at,
        description=description,
        published=doc.published if kind == "video" else None,
    )


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
        target_id=str(clip_id),
        clip_id=str(clip_id),
        clip_deleted=clip is None,
        title=clip.title if clip else None,
        style_tags=clip.style_tags if clip else [],
        creator_id=str(clip.user_id) if clip else None,
        creator_name=_creator_name(creator),
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
            # Before the write, so a failure here leaves nothing half-applied and the admin can retry (#569).
            details.update(await release_service.unshare_releases({"clip_id": oid}, {"_id": oid}))
        elif action == "flag":
            updates.update(content_warning=True, flagged_at=now)
        await clip.set(updates)
        resolved = await _resolve_reports(oid, now)
        if action == "remove":
            # And again once stamped: an upload or share that landed in between saw no removal either, so its
            # track is queued and its release made private here. Both are idempotent; anything from here on
            # sees removed_at and takes itself down (unshare_if_source_removed).
            await release_service.unshare_releases({"clip_id": oid}, {"_id": oid})
            await NotificationEvent(
                user_id=clip.user_id,
                clip_id=clip.id,
                event_type="moderation_clip_removed",
                channel="in_app",
                payload={"clip_id": str(clip.id), "title": clip.title, "reason": reason},
            ).insert()
    await log_action(actor_id, action, "clip", str(oid), reason, {"reports_resolved": resolved, **details})
    return ActionResult(ok=True)


async def act_on_content(
    actor_id: str, target_type: ContentType, action: ContentAction, target_id: str, reason: str | None
) -> ActionResult:
    """Approve, unpublish or restore (video), or drop (artwork) one flagged non-clip output (#539, #571)."""
    noun = _CONTENT_NOUNS[target_type]
    oid = coerce_object_id(target_id)
    if oid is None:
        return ActionResult(ok=False, detail=f"Invalid {noun} id.")
    doc = await _CONTENT_DOCS[target_type].get(oid)
    if doc is None:
        return ActionResult(ok=False, detail=f"{noun.capitalize()} not found.")
    now = utcnow()
    details: dict = {}
    notice: tuple[str, dict] | None = None
    if action == "drop":
        details = await _drop_artwork(doc)
        notice = ("moderation_artwork_dropped", {"was_cover": details["was_cover"]})
    elif action == "restore":
        if refused := await _restore_video(doc):
            return ActionResult(ok=False, detail=refused)
        notice = ("moderation_video_restored", {"video_id": str(oid)})
    else:
        updates: dict = {"moderation_reviewed_at": now}
        if action == "unpublish":
            details["was_published"] = doc.published
            if doc.removed_at is None:  # re-unpublishing a video already down tells the owner nothing new
                notice = ("moderation_video_unpublished", {"video_id": str(oid)})
            updates.update(published=False, removed_at=now)
        await doc.set(updates)
    await log_action(actor_id, action, target_type, str(oid), reason, details)
    # After the log: a failed insert must not leave an applied drop, which can't be retried, unlogged.
    if notice:
        await _notify_owner(doc, notice[0], reason, **notice[1])
    return ActionResult(ok=True)


async def _restore_video(video: Video) -> str | None:
    """Lift a takedown so the owner may publish again (#571). The video stays unpublished until they do."""
    if video.removed_at is None:
        return "This video is not taken down."
    owner = await User.get(video.user_id)
    if owner is not None and owner.banned_at is not None:
        return "The video's owner is banned."
    # Conditional on the takedown read: of two concurrent restores only one applies, and an unpublish that
    # re-stamps removed_at meanwhile is not lifted by a restore aimed at the older one.
    lifted = await Video.find({"_id": video.id, "removed_at": video.removed_at}).update({"$set": {"removed_at": None}})
    return None if lifted.modified_count else "This video is not taken down."


async def _notify_owner(doc: Video | ArtworkOption, event_type: str, reason: str | None, **payload) -> None:
    """Tell a video's or artwork's owner what moderation did to it, naming the song it was made for."""
    clip = await Clip.get(doc.clip_id)
    await NotificationEvent(
        user_id=doc.user_id,
        clip_id=doc.clip_id,
        event_type=event_type,
        channel="in_app",
        payload={**payload, "title": clip.title if clip else None, "reason": reason},
    ).insert()


async def _drop_artwork(option: ArtworkOption) -> dict:
    """Delete a generated cover option, and clear the clip's cover if it was that option."""
    queued: list[str] = []
    is_cover = await Clip.find_one({"_id": option.clip_id, "artwork_path": option.storage_path}) is not None
    if is_cover:
        # #569: the cover went out with the song's SoundCloud uploads, so those tracks come down with it. Queued
        # before anything is deleted, so a failure here leaves the drop retryable.
        queued = await release_service.queue_unshares({"clip_id": option.clip_id}, {"_id": option.clip_id})
    await option.delete()
    cleared = await Clip.find({"_id": option.clip_id, "artwork_path": option.storage_path}).update(
        {"$set": {"artwork_path": None}}
    )
    if is_cover:
        # And again once cleared: an upload that recorded its track in between still saw the cover. Anything
        # recorded from here on sees the cover gone and queues itself (routers/distribution.soundcloud_upload).
        queued = await release_service.queue_unshares({"clip_id": option.clip_id}, {"_id": option.clip_id})
    try:
        await asyncio.to_thread(get_storage_backend().delete, option.storage_path)
    except Exception:  # best-effort: the option can no longer be selected or served either way
        logger.warning("Failed to delete dropped artwork object %s", option.storage_path)
    details: dict = {"clip_id": str(option.clip_id), "was_cover": bool(cleared.modified_count)}
    if queued:
        details["soundcloud_unshare_queued"] = queued
    return details


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
    clips_removed = await clip_service.take_down_visible({"user_id": user.id})
    # #539: removed, like the clips, so a still-live access token can't publish them again.
    videos = await Video.find({"user_id": user.id, "published": True}).update(
        {"$set": {"published": False, "removed_at": now}}
    )
    releases = await release_service.unshare_releases({"user_id": user.id}, {"user_id": user.id})
    return {"clips_removed": clips_removed, "videos_unpublished": videos.modified_count, **releases}


async def log_screening_rules_update(actor_id: str, before: dict, after: dict) -> None:
    await log_action(
        actor_id, "update_screening_rules", "screening_rules", None, None, {"before": before, "after": after}
    )


class LogItem(BaseModel):
    id: str
    actor_id: str | None
    # Display names resolved at read time (#540); None when the admin or target is gone.
    actor_name: str | None
    action: str
    target_type: str
    target_id: str | None
    target_label: str | None
    reason: str | None
    details: dict
    created_at: datetime


async def list_log(limit: int, cursor: str | None = None) -> tuple[list[LogItem], str | None]:
    """A page of the log, newest first, plus the cursor for the next page (None on the last)."""
    entries = (
        await ModerationLogEntry.find(after_cursor("log", cursor))
        .sort(-ModerationLogEntry.created_at, -ModerationLogEntry.id)
        .limit(limit + 1)
        .to_list()
    )
    page = entries[:limit]
    actors, labels = await _log_names(page)
    items = [
        LogItem(
            id=str(e.id),
            actor_id=str(e.actor_id) if e.actor_id else None,
            actor_name=_creator_name(actors.get(e.actor_id)),
            action=e.action,
            target_type=e.target_type,
            target_id=e.target_id,
            target_label=labels.get((e.target_type, e.target_id)),
            reason=e.reason,
            details=e.details,
            created_at=e.created_at,
        )
        for e in page
    ]
    more = len(entries) > limit
    return items, encode_cursor("log", (page[-1].created_at, str(page[-1].id))) if more else None


async def _log_names(
    entries: list[ModerationLogEntry],
) -> tuple[dict[PydanticObjectId, User], dict[tuple[str, str | None], str | None]]:
    """The admins who acted, and a label per (target_type, target_id): a clip's title, a user's
    name, the title of the song a video or artwork was made for, a voice model's name."""
    targets: dict[str, set[PydanticObjectId]] = {}
    for e in entries:
        if (oid := coerce_object_id(e.target_id or "")) is not None:
            targets.setdefault(e.target_type, set()).add(oid)

    async def load(document: type, ids: set[PydanticObjectId]) -> dict:
        return {d.id: d for d in await document.find(In(document.id, list(ids))).to_list()} if ids else {}

    users, videos, artwork, voices = await asyncio.gather(
        load(User, {e.actor_id for e in entries if e.actor_id} | targets.get("user", set())),
        load(Video, targets.get("video", set())),
        load(ArtworkOption, targets.get("artwork", set())),
        load(VoiceModel, targets.get("voice_model", set())),
    )
    songs = {d.id: d.clip_id for d in [*videos.values(), *artwork.values()]}
    clips = await load(Clip, targets.get("clip", set()) | set(songs.values()))

    def title(clip_id: PydanticObjectId | None) -> str | None:
        return clips[clip_id].title if clip_id in clips else None

    by_kind = {
        "user": lambda oid: _creator_name(users.get(oid)),
        "clip": title,
        "video": lambda oid: title(songs.get(oid)),
        "artwork": lambda oid: title(songs.get(oid)),
        "voice_model": lambda oid: voices[oid].name if oid in voices else None,
    }
    labels = {(kind, str(oid)): by_kind[kind](oid) for kind, oids in targets.items() if kind in by_kind for oid in oids}
    return users, labels


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
