"""Admin-only platform settings (US-27.1) and the moderation queue (US-27.2).

``GET/PUT /admin/screening-rules`` read and replace the live content-screening rules.
A save applies to the next generation request — no deploy, no restart.
``GET /admin/moderation/reports`` lists listener reports, newest first.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from ..auth.dependencies import require_admin
from ..models import ReportCategory
from ..models.screening import ScreeningRules
from ..services import reports as report_service, screening

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/screening-rules", response_model=ScreeningRules)
async def get_screening_rules() -> ScreeningRules:
    return await screening.get_rules()


@router.put("/screening-rules", response_model=ScreeningRules)
async def put_screening_rules(rules: ScreeningRules) -> ScreeningRules:
    return await screening.save_rules(rules)


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
