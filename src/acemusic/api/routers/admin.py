"""Admin-only platform settings (US-27.1) and moderation (US-27.2, US-27.3).

``GET/PUT /admin/screening-rules`` read and replace the live content-screening rules.
A save applies to the next generation request — no deploy, no restart.
``GET /admin/moderation/reports`` lists listener reports, newest first.
``GET /admin/moderation/queue`` groups open reports and automated flags per clip;
``POST /admin/moderation/clips`` and ``/users`` act on them in bulk, and every action
(including a screening-rules save) is recorded in ``GET /admin/moderation/log``.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from ..auth.dependencies import CurrentUser, require_admin
from ..models import ReportCategory
from ..models.screening import ScreeningRules
from ..services import moderation, reports as report_service, screening

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/screening-rules", response_model=ScreeningRules)
async def get_screening_rules() -> ScreeningRules:
    return await screening.get_rules()


@router.put("/screening-rules", response_model=ScreeningRules)
async def put_screening_rules(rules: ScreeningRules, current: CurrentUser = Depends(require_admin)) -> ScreeningRules:
    before = await screening.get_rules()
    saved = await screening.save_rules(rules)
    await moderation.log_screening_rules_update(current.user_id, before.model_dump(), saved.model_dump())
    return saved


class ReportEntry(BaseModel):
    id: str
    clip_id: str
    reporter_id: str
    category: ReportCategory
    details: str | None
    created_at: datetime


class ModerationQueueResponse(BaseModel):
    reports: list[ReportEntry]


@router.get("/moderation/reports", response_model=ModerationQueueResponse)
async def get_moderation_reports(
    limit: int = Query(default=100, ge=1, le=report_service.MAX_QUEUE_LIMIT),
) -> ModerationQueueResponse:
    reports = await report_service.list_reports(limit)
    return ModerationQueueResponse(
        reports=[
            ReportEntry(
                id=str(r.id),
                clip_id=str(r.clip_id),
                reporter_id=str(r.reporter_id),
                category=r.category,
                details=r.details,
                created_at=r.created_at,
            )
            for r in reports
        ]
    )


class ModerationQueueItemsResponse(BaseModel):
    items: list[moderation.QueueItem]


@router.get("/moderation/queue", response_model=ModerationQueueItemsResponse)
async def get_moderation_queue() -> ModerationQueueItemsResponse:
    return ModerationQueueItemsResponse(items=await moderation.get_queue())


MAX_BATCH = 100
Reason = Annotated[str | None, Field(max_length=1000)]


class ClipActionRequest(BaseModel):
    action: moderation.ClipAction
    clip_ids: list[str] = Field(min_length=1, max_length=MAX_BATCH)
    reason: Reason = None


class ClipActionResult(moderation.ActionResult):
    clip_id: str


class ClipActionResponse(BaseModel):
    results: list[ClipActionResult]


@router.post("/moderation/clips", response_model=ClipActionResponse)
async def moderate_clips(body: ClipActionRequest, current: CurrentUser = Depends(require_admin)) -> ClipActionResponse:
    results = []
    for clip_id in body.clip_ids:
        outcome = await moderation.act_on_clip(current.user_id, body.action, clip_id, body.reason)
        results.append(ClipActionResult(clip_id=clip_id, **outcome.model_dump()))
    return ClipActionResponse(results=results)


class UserActionRequest(BaseModel):
    action: moderation.UserAction
    user_ids: list[str] = Field(min_length=1, max_length=MAX_BATCH)
    reason: Reason = None


class UserActionResult(moderation.ActionResult):
    user_id: str


class UserActionResponse(BaseModel):
    results: list[UserActionResult]


@router.post("/moderation/users", response_model=UserActionResponse)
async def moderate_users(body: UserActionRequest, current: CurrentUser = Depends(require_admin)) -> UserActionResponse:
    results = []
    for user_id in body.user_ids:
        outcome = await moderation.act_on_user(current.user_id, body.action, user_id, body.reason)
        results.append(UserActionResult(user_id=user_id, **outcome.model_dump()))
    return UserActionResponse(results=results)


class ModerationLogItem(BaseModel):
    id: str
    actor_id: str
    action: str
    target_type: str
    target_id: str | None
    reason: str | None
    details: dict
    created_at: datetime


class ModerationLogResponse(BaseModel):
    entries: list[ModerationLogItem]


@router.get("/moderation/log", response_model=ModerationLogResponse)
async def get_moderation_log(
    limit: int = Query(default=100, ge=1, le=moderation.MAX_LOG_LIMIT),
) -> ModerationLogResponse:
    entries = await moderation.list_log(limit)
    return ModerationLogResponse(
        entries=[
            ModerationLogItem(
                id=str(e.id),
                actor_id=str(e.actor_id),
                action=e.action,
                target_type=e.target_type,
                target_id=e.target_id,
                reason=e.reason,
                details=e.details,
                created_at=e.created_at,
            )
            for e in entries
        ]
    )
