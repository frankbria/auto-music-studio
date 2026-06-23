"""Playback queue router (US-14.3), mounted under ``/api/v1/queue``.

A single server-side queue per authenticated user, so the web player can queue
songs, support next/previous, and restore state across page navigations.

Endpoints (all require a valid Bearer access token; the queue is implicitly
scoped to the authenticated user):

* ``POST   /queue``            → add clips (optionally at a position)
* ``GET    /queue``            → current queue + playback position
* ``DELETE /queue/{clip_id}``  → remove a clip
* ``POST   /queue/next``       → advance (repeat/shuffle aware)
* ``POST   /queue/previous``   → go back (repeat/shuffle aware)
* ``PUT    /queue/reorder``    → move a clip to a new position
* ``DELETE /queue``            → clear the whole queue (204)
* ``PATCH  /queue``            → update repeat_mode / shuffle_enabled

Request/response schemas live here (same convention as the workspaces router);
business rules live in :mod:`acemusic.api.services.queue`.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, ConfigDict, Field

from ..auth.dependencies import CurrentUser, get_current_user, require_existing_user
from ..models import PlaybackQueue, RepeatMode
from ..services import queue as queue_service

router = APIRouter(prefix="/queue", tags=["queue"], dependencies=[Depends(get_current_user)])


class QueueAddRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clip_ids: Annotated[list[str], Field(min_length=1)]
    # None appends; a value beyond the end appends; negatives clamp to the front.
    position: int | None = None


class QueueReorderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clip_id: str
    new_position: int


class QueueUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repeat_mode: RepeatMode | None = None
    shuffle_enabled: bool | None = None


class QueueResponse(BaseModel):
    clips: list[str]
    current_index: int | None
    current_clip_id: str | None
    repeat_mode: str
    shuffle_enabled: bool
    updated_at: datetime | None

    @classmethod
    def from_queue(cls, queue: PlaybackQueue) -> "QueueResponse":
        current_clip_id = None
        if queue.current_index is not None and 0 <= queue.current_index < len(queue.clips):
            current_clip_id = str(queue.clips[queue.current_index])
        return cls(
            clips=[str(clip_id) for clip_id in queue.clips],
            current_index=queue.current_index,
            current_clip_id=current_clip_id,
            repeat_mode=queue.repeat_mode.value,
            shuffle_enabled=queue.shuffle_enabled,
            updated_at=queue.updated_at,
        )


class NavigationResponse(QueueResponse):
    """Same shape as :class:`QueueResponse`; signals that navigation occurred."""


@router.post("", response_model=QueueResponse)
async def add_clips(
    body: QueueAddRequest,
    current: CurrentUser = Depends(require_existing_user),
) -> QueueResponse:
    queue = await queue_service.add_clips(current.user_id, body.clip_ids, body.position)
    return QueueResponse.from_queue(queue)


@router.get("", response_model=QueueResponse)
async def get_queue(current: CurrentUser = Depends(require_existing_user)) -> QueueResponse:
    queue = await queue_service.get_or_create_queue(current.user_id)
    return QueueResponse.from_queue(queue)


@router.delete("/{clip_id}", response_model=QueueResponse)
async def remove_clip(
    clip_id: str,
    current: CurrentUser = Depends(require_existing_user),
) -> QueueResponse:
    queue = await queue_service.remove_clip(current.user_id, clip_id)
    return QueueResponse.from_queue(queue)


@router.post("/next", response_model=NavigationResponse)
async def next_clip(current: CurrentUser = Depends(require_existing_user)) -> NavigationResponse:
    queue = await queue_service.go_next(current.user_id)
    return NavigationResponse.from_queue(queue)


@router.post("/previous", response_model=NavigationResponse)
async def previous_clip(current: CurrentUser = Depends(require_existing_user)) -> NavigationResponse:
    queue = await queue_service.go_previous(current.user_id)
    return NavigationResponse.from_queue(queue)


@router.put("/reorder", response_model=QueueResponse)
async def reorder_clip(
    body: QueueReorderRequest,
    current: CurrentUser = Depends(require_existing_user),
) -> QueueResponse:
    queue = await queue_service.reorder_clip(current.user_id, body.clip_id, body.new_position)
    return QueueResponse.from_queue(queue)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def clear_queue(current: CurrentUser = Depends(require_existing_user)) -> Response:
    await queue_service.clear_queue(current.user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("", response_model=QueueResponse)
async def update_modes(
    body: QueueUpdateRequest,
    current: CurrentUser = Depends(require_existing_user),
) -> QueueResponse:
    queue = await queue_service.update_modes(current.user_id, body.repeat_mode, body.shuffle_enabled)
    return QueueResponse.from_queue(queue)
