"""Admin-only platform settings (US-27.1) and moderation (US-27.2, US-27.3).

``GET/PUT /admin/screening-rules`` read and replace the live content-screening rules.
A save applies to the next generation request — no deploy, no restart.
``GET /admin/moderation/reports`` lists listener reports, newest first.
``GET /admin/moderation/queue`` groups open reports and automated flags per clip, and lists
flagged videos, artwork and voice models (#539); ``POST /admin/moderation/clips``, ``/content``
and ``/users`` act on them in bulk, and every action
(including a screening-rules save) is recorded in ``GET /admin/moderation/log``.
``GET /admin/moderation/appeals`` is the creators' appeals queue (US-27.4); ``POST
/admin/moderation/appeals/{id}`` upholds, reverses or asks for more information.
"""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, model_validator

from ..auth.dependencies import CurrentUser, get_settings, require_admin
from ..models import ReportCategory
from ..models.screening import ScreeningRules
from ..services import appeals as appeal_service, moderation, reports as report_service, screening
from ..settings import ApiSettings

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
    next_cursor: str | None


@router.get("/moderation/queue", response_model=ModerationQueueItemsResponse)
async def get_moderation_queue(
    sort: moderation.QueueSort = "reports",
    source: Literal["all"] | moderation.QueueSource = "all",
    category: Literal["all"] | ReportCategory = "all",
    limit: int = Query(default=100, ge=1, le=moderation.MAX_QUEUE_LIMIT),
    cursor: str | None = None,
) -> ModerationQueueItemsResponse:
    items, next_cursor = await moderation.get_queue(sort, source, category, limit, cursor)
    return ModerationQueueItemsResponse(items=items, next_cursor=next_cursor)


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
async def moderate_clips(
    body: ClipActionRequest,
    current: CurrentUser = Depends(require_admin),
    settings: ApiSettings = Depends(get_settings),
) -> ClipActionResponse:
    results = []
    for clip_id in body.clip_ids:
        outcome = await moderation.act_on_clip(current.user_id, body.action, clip_id, body.reason, settings)
        results.append(ClipActionResult(clip_id=clip_id, **outcome.model_dump()))
    return ClipActionResponse(results=results)


class ContentActionRequest(BaseModel):
    target_type: moderation.ContentType
    action: moderation.ContentAction
    ids: list[str] = Field(min_length=1, max_length=MAX_BATCH)
    reason: Reason = None

    @model_validator(mode="after")
    def _action_fits_type(self) -> "ContentActionRequest":
        allowed = moderation.CONTENT_ACTIONS[self.target_type]
        if self.action not in allowed:
            raise ValueError(f"A {self.target_type} takes only: {', '.join(allowed)}.")
        return self


class ContentActionResult(moderation.ActionResult):
    id: str


class ContentActionResponse(BaseModel):
    results: list[ContentActionResult]


@router.post("/moderation/content", response_model=ContentActionResponse)
async def moderate_content(
    body: ContentActionRequest, current: CurrentUser = Depends(require_admin)
) -> ContentActionResponse:
    results = []
    for target_id in body.ids:
        outcome = await moderation.act_on_content(
            current.user_id, body.target_type, body.action, target_id, body.reason
        )
        results.append(ContentActionResult(id=target_id, **outcome.model_dump()))
    return ContentActionResponse(results=results)


class UserActionRequest(BaseModel):
    action: moderation.UserAction
    user_ids: list[str] = Field(min_length=1, max_length=MAX_BATCH)
    reason: Reason = None


class UserActionResult(moderation.ActionResult):
    user_id: str


class UserActionResponse(BaseModel):
    results: list[UserActionResult]


@router.post("/moderation/users", response_model=UserActionResponse)
async def moderate_users(
    body: UserActionRequest,
    current: CurrentUser = Depends(require_admin),
    settings: ApiSettings = Depends(get_settings),
) -> UserActionResponse:
    results = []
    for user_id in body.user_ids:
        outcome = await moderation.act_on_user(current.user_id, body.action, user_id, body.reason, settings)
        results.append(UserActionResult(user_id=user_id, **outcome.model_dump()))
    return UserActionResponse(results=results)


class ModerationLogResponse(BaseModel):
    entries: list[moderation.LogItem]
    next_cursor: str | None


@router.get("/moderation/log", response_model=ModerationLogResponse)
async def get_moderation_log(
    limit: int = Query(default=100, ge=1, le=moderation.MAX_LOG_LIMIT),
    cursor: str | None = None,
) -> ModerationLogResponse:
    entries, next_cursor = await moderation.list_log(limit, cursor)
    return ModerationLogResponse(entries=entries, next_cursor=next_cursor)


class AppealQueueResponse(BaseModel):
    appeals: list[appeal_service.AppealQueueItem]


@router.get("/moderation/appeals", response_model=AppealQueueResponse)
async def get_appeals(status: appeal_service.QueueFilter = "open") -> AppealQueueResponse:
    return AppealQueueResponse(appeals=await appeal_service.list_queue(status))


class AppealDecisionRequest(BaseModel):
    decision: appeal_service.AppealDecision
    note: Reason = None

    @model_validator(mode="after")
    def _question_for_request_info(self) -> "AppealDecisionRequest":
        self.note = (self.note or "").strip() or None
        if self.decision == "request_info" and self.note is None:
            raise ValueError("Say what information the creator should send.")
        return self


@router.post("/moderation/appeals/{appeal_id}", response_model=appeal_service.AppealView)
async def decide_appeal(
    appeal_id: str, body: AppealDecisionRequest, current: CurrentUser = Depends(require_admin)
) -> appeal_service.AppealView:
    return appeal_service.AppealView.of(
        await appeal_service.decide(current.user_id, appeal_id, body.decision, body.note)
    )
