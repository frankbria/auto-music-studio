"""Workspace CRUD router (US-9.4), mounted under ``/api/v1/workspaces``.

Endpoints (all require a valid Bearer access token and operate only on the
authenticated user's workspaces):

* ``POST   /workspaces``      → create (201; 409 on duplicate name)
* ``GET    /workspaces``      → list with per-workspace clip counts
* ``GET    /workspaces/{id}`` → single workspace (404 if missing/not owned)
* ``PATCH  /workspaces/{id}`` → rename (409 on duplicate name)
* ``DELETE /workspaces/{id}`` → delete (409 if non-empty without ``?force=true``,
  400 for the last workspace)

Request/response schemas live here (same convention as the users router);
business rules live in :mod:`acemusic.api.services.workspaces`.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..auth.dependencies import CurrentUser, get_current_user, require_existing_user
from ..models import Workspace
from ..services import workspaces as workspace_service

# Names are stored verbatim and re-served on every list; cap them so one POST
# cannot bloat the document (mirrors the users router's field caps).
WORKSPACE_NAME_MAX_LENGTH = 100

# Router-level dependency gates every route; endpoints additionally take
# ``current`` to read the identity. FastAPI caches the dependency, so
# ``get_current_user`` still runs once per request.
router = APIRouter(prefix="/workspaces", tags=["workspaces"], dependencies=[Depends(get_current_user)])


def _validate_name(value: str) -> str:
    """Strip surrounding whitespace and reject names that are blank after it."""
    value = value.strip()
    if not value:
        raise ValueError("Workspace name must not be blank.")
    return value


class WorkspaceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=WORKSPACE_NAME_MAX_LENGTH)]

    _check_name = field_validator("name")(_validate_name)


class WorkspaceUpdate(BaseModel):
    """Rename payload. ``extra="forbid"`` rejects unknown keys with 422."""

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=WORKSPACE_NAME_MAX_LENGTH)] | None = None

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str | None) -> str | None:
        return value if value is None else _validate_name(value)


class WorkspaceResponse(BaseModel):
    id: str
    name: str
    clip_count: int
    is_default: bool
    created_at: datetime
    updated_at: datetime | None

    @classmethod
    def from_workspace(cls, workspace: Workspace, clip_count: int) -> "WorkspaceResponse":
        return cls(
            id=str(workspace.id),
            name=workspace.name,
            clip_count=clip_count,
            is_default=workspace.is_default,
            created_at=workspace.created_at,
            updated_at=workspace.updated_at,
        )


class WorkspaceListResponse(BaseModel):
    workspaces: list[WorkspaceResponse]
    total: int


@router.post("", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    body: WorkspaceCreate,
    current: CurrentUser = Depends(require_existing_user),
) -> WorkspaceResponse:
    workspace = await workspace_service.create_workspace(current.user_id, body.name)
    return WorkspaceResponse.from_workspace(workspace, clip_count=0)


@router.get("", response_model=WorkspaceListResponse)
async def list_workspaces(current: CurrentUser = Depends(require_existing_user)) -> WorkspaceListResponse:
    pairs = await workspace_service.list_workspaces(current.user_id)
    return WorkspaceListResponse(
        workspaces=[WorkspaceResponse.from_workspace(workspace, count) for workspace, count in pairs],
        total=len(pairs),
    )


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace(
    workspace_id: str,
    current: CurrentUser = Depends(require_existing_user),
) -> WorkspaceResponse:
    workspace = await workspace_service.get_workspace(workspace_id, current.user_id)
    clip_count = await workspace_service.count_clips(workspace)
    return WorkspaceResponse.from_workspace(workspace, clip_count)


@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
async def update_workspace(
    workspace_id: str,
    body: WorkspaceUpdate,
    current: CurrentUser = Depends(require_existing_user),
) -> WorkspaceResponse:
    """Rename the workspace; an empty body is a no-op returning the current state."""
    if body.name is None:
        workspace = await workspace_service.get_workspace(workspace_id, current.user_id)
    else:
        workspace = await workspace_service.update_workspace(workspace_id, current.user_id, body.name)
    clip_count = await workspace_service.count_clips(workspace)
    return WorkspaceResponse.from_workspace(workspace, clip_count)


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace(
    workspace_id: str,
    force: bool = Query(
        default=False,
        description="Required (true) to delete a workspace that still contains clips, along with those clips.",
    ),
    current: CurrentUser = Depends(require_existing_user),
) -> Response:
    await workspace_service.delete_workspace(workspace_id, current.user_id, force=force)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
