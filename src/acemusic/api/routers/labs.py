"""The signed-in user's experimental features on /labs (US-28.5, #342)."""

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..auth.dependencies import CurrentUser, require_existing_user
from ..models import User
from ..services import feature_flags

router = APIRouter(prefix="/labs", tags=["labs"])


class Experiment(BaseModel):
    key: str
    name: str
    description: str
    stage: Literal["alpha", "beta"]
    #: An admin has made it available to this user (to everyone, or to them).
    available: bool
    #: The user has switched it on, and it is available.
    enabled: bool


class LabsResponse(BaseModel):
    experiments: list[Experiment]


class OptIn(BaseModel):
    enabled: bool


async def _user(current: CurrentUser) -> User:
    return await User.get(current.user_id)


@router.get("", response_model=LabsResponse)
async def list_experiments(current: CurrentUser = Depends(require_existing_user)) -> LabsResponse:
    return LabsResponse(experiments=await feature_flags.labs_for(await _user(current)))


@router.put("/{key}", response_model=LabsResponse)
async def switch_experiment(
    key: str, body: OptIn, current: CurrentUser = Depends(require_existing_user)
) -> LabsResponse:
    """Switch an experiment on or off for yourself; 403 when it isn't available to you, 404 for an unknown key."""
    await feature_flags.set_opt_in(await _user(current), key, body.enabled)
    return LabsResponse(experiments=await feature_flags.labs_for(await _user(current)))
