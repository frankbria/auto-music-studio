"""Clip reports and the moderation queue (US-27.2)."""

from beanie import PydanticObjectId
from fastapi import HTTPException, status
from pymongo.errors import DuplicateKeyError

from ..models import ClipReport, ReportCategory
from .clips import get_clip_for_audio_access

MAX_QUEUE_LIMIT = 500


async def report_clip(clip_id: str, reporter_id: str, category: ReportCategory, details: str | None) -> ClipReport:
    """File ``reporter_id``'s report on ``clip_id``.

    404 unknown clip, 403 another user's private clip, 400 the reporter's own clip,
    409 a repeat report. Unlisted clips are reportable: a shared link can carry abuse too.
    """
    clip = await get_clip_for_audio_access(clip_id, reporter_id)
    if str(clip.user_id) == reporter_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot report your own clip.")
    report = ClipReport(
        clip_id=clip.id, reporter_id=PydanticObjectId(reporter_id), category=category, details=details or None
    )
    try:
        await report.insert()
    except DuplicateKeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="You have already reported this clip."
        ) from exc
    return report


async def list_reports(limit: int) -> list[ClipReport]:
    # ponytail: flat newest-first list; per-clip counts and sorting belong to the dashboard (#336).
    return await ClipReport.find_all().sort(-ClipReport.created_at, -ClipReport.id).limit(limit).to_list()
