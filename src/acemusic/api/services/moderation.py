"""The admin moderation dashboard (US-27.3): review queue, clip and user actions, audit log.

The queue also carries flagged videos, generated artwork and voice models (#539), each
with the actions that fit it (see ``CONTENT_ACTIONS``).

Actions are bulk-native and per-target: a malformed or unknown id fails in its own
result instead of failing the batch, and every target acted on gets one log entry.
Writes are targeted ``$set`` updates, never whole-document saves, so an action cannot
revert a concurrent edit to the same clip or user.
"""

import asyncio
import logging
from datetime import datetime
from typing import Literal

from beanie import PydanticObjectId
from beanie.operators import In
from pydantic import BaseModel

from acemusic.storage import get_storage_backend

from ..auth.services import revoke_all_user_tokens
from ..models import (
    ArtworkOption,
    Clip,
    ClipReport,
    Job,
    ModerationLogEntry,
    NotificationEvent,
    User,
    Video,
    VisibilityState,
    VoiceModel,
)
from ..models.common import utcnow
from ..settings import ApiSettings
from . import clips as clip_service, releases as release_service
from .common import coerce_object_id

logger = logging.getLogger(__name__)

ClipAction = Literal["approve", "remove", "flag"]
UserAction = Literal["warn", "ban"]
QueueSource = Literal["report", "automated"]
# #539: screening flags outputs that aren't clips too; each type takes the actions that fit it.
ContentType = Literal["video", "artwork", "voice_model"]
ContentAction = Literal["approve", "unpublish", "drop"]
CONTENT_ACTIONS: dict[str, tuple[str, ...]] = {
    "video": ("approve", "unpublish"),
    "artwork": ("approve", "drop"),
    "voice_model": ("approve",),
}
_CONTENT_DOCS = {"video": Video, "artwork": ArtworkOption, "voice_model": VoiceModel}
_CONTENT_NOUNS = {"video": "video", "artwork": "artwork", "voice_model": "voice model"}
_UNREVIEWED = {"moderation_flags": {"$type": "string"}, "moderation_reviewed_at": None}

MAX_QUEUE_ITEMS = 500
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


class ActionResult(BaseModel):
    ok: bool
    detail: str | None = None


async def get_queue() -> list[QueueItem]:
    """One item per clip with open reports and/or unreviewed automated flags, and per flagged
    video, artwork option or voice model, most urgent first."""
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
            prompt = (job.input_params or {}).get("prompt") if job else None
            items.append(_content_item(kind, doc, clips.get(doc.clip_id), creators, prompt))
    items.extend(_content_item("voice_model", voice, None, creators, voice.description) for voice in voices)
    items.sort(key=lambda i: (i.report_count, i.severity, i.latest_at), reverse=True)
    return items[:MAX_QUEUE_ITEMS]


async def _unreviewed(document: type) -> list:
    return await document.find(_UNREVIEWED).sort(-document.created_at).limit(MAX_QUEUE_ITEMS).to_list()


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


async def act_on_clip(
    actor_id: str, action: ClipAction, clip_id: str, reason: str | None, settings: ApiSettings
) -> ActionResult:
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
            details.update(await release_service.unshare_releases({"clip_id": oid}, settings))
            await NotificationEvent(
                user_id=clip.user_id,
                clip_id=clip.id,
                event_type="moderation_clip_removed",
                channel="in_app",
                payload={"clip_id": str(clip.id), "title": clip.title, "reason": reason},
            ).insert()
    await log_action(actor_id, action, "clip", str(oid), reason, {"reports_resolved": resolved, **details})
    return ActionResult(ok=True, detail=_unshare_failure(details))


async def act_on_content(
    actor_id: str, target_type: ContentType, action: ContentAction, target_id: str, reason: str | None
) -> ActionResult:
    """Approve, unpublish (video) or drop (artwork) one flagged non-clip output (#539)."""
    noun = _CONTENT_NOUNS[target_type]
    oid = coerce_object_id(target_id)
    if oid is None:
        return ActionResult(ok=False, detail=f"Invalid {noun} id.")
    doc = await _CONTENT_DOCS[target_type].get(oid)
    if doc is None:
        return ActionResult(ok=False, detail=f"{noun.capitalize()} not found.")
    now = utcnow()
    details: dict = {}
    if action == "drop":
        details = await _drop_artwork(doc)
    else:
        updates: dict = {"moderation_reviewed_at": now}
        if action == "unpublish":
            details["was_published"] = doc.published
            updates.update(published=False, removed_at=now)
        await doc.set(updates)
    await log_action(actor_id, action, target_type, str(oid), reason, details)
    return ActionResult(ok=True)


async def _drop_artwork(option: ArtworkOption) -> dict:
    """Delete a generated cover option, and clear the clip's cover if it was that option."""
    await option.delete()
    cleared = await Clip.find({"_id": option.clip_id, "artwork_path": option.storage_path}).update(
        {"$set": {"artwork_path": None}}
    )
    try:
        await asyncio.to_thread(get_storage_backend().delete, option.storage_path)
    except Exception:  # best-effort: the option can no longer be selected or served either way
        logger.warning("Failed to delete dropped artwork object %s", option.storage_path)
    return {"clip_id": str(option.clip_id), "was_cover": bool(cleared.modified_count)}


def _unshare_failure(details: dict) -> str | None:
    failed = [f["track_id"] for f in details.get("soundcloud_unshare_failed", [])]
    if not failed:
        return None
    noun, pronoun = ("track", "it") if len(failed) == 1 else ("tracks", "they")
    return f"Couldn't make SoundCloud {noun} {', '.join(failed)} private; {pronoun} may still be public on the owner's account."


async def _resolve_reports(clip_id: PydanticObjectId, now: datetime) -> int:
    result = await ClipReport.find({"clip_id": clip_id, "resolved_at": None}).update({"$set": {"resolved_at": now}})
    return result.modified_count


async def act_on_user(
    actor_id: str, action: UserAction, user_id: str, reason: str | None, settings: ApiSettings
) -> ActionResult:
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
        details = await _ban(user, settings)
    await log_action(actor_id, action, "user", str(oid), reason, details)
    return ActionResult(ok=True, detail=_unshare_failure(details))


async def _ban(user: User, settings: ApiSettings) -> dict:
    now = utcnow()
    if user.banned_at is None:
        await user.set({"banned_at": now})
    await revoke_all_user_tokens(user.id)
    clips_removed = await clip_service.take_down_visible({"user_id": user.id})
    # #539: removed, like the clips, so a still-live access token can't publish them again.
    videos = await Video.find({"user_id": user.id, "published": True}).update(
        {"$set": {"published": False, "removed_at": now}}
    )
    releases = await release_service.unshare_releases({"user_id": user.id}, settings)
    return {"clips_removed": clips_removed, "videos_unpublished": videos.modified_count, **releases}


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
