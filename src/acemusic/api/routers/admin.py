"""Admin-only platform settings (US-27.1).

``GET/PUT /admin/screening-rules`` read and replace the live content-screening rules.
A save applies to the next generation request — no deploy, no restart.
"""

from fastapi import APIRouter, Depends

from ..auth.dependencies import require_admin
from ..models.screening import ScreeningRules
from ..services import screening

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/screening-rules", response_model=ScreeningRules)
async def get_screening_rules() -> ScreeningRules:
    return await screening.get_rules()


@router.put("/screening-rules", response_model=ScreeningRules)
async def put_screening_rules(rules: ScreeningRules) -> ScreeningRules:
    return await screening.save_rules(rules)
