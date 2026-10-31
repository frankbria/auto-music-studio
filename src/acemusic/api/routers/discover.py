"""Anonymous public discovery reads behind Feed, Explore and Search (#651)."""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from ..services import discovery
from ..utils.rate_limit import enforce_discover_rate_limit
from .clips import PublicClipResponse

router = APIRouter(prefix="/discover", tags=["discover"], dependencies=[Depends(enforce_discover_rate_limit)])


class DiscoverClipsResponse(BaseModel):
    clips: list[PublicClipResponse]
    next_cursor: str | None
    total: int


class DiscoverFacetsResponse(BaseModel):
    keys: list[str]
    models: list[str]


@router.get("/clips", response_model=DiscoverClipsResponse)
async def list_public_clips(
    q: str = Query(default="", max_length=200),
    style: str | None = Query(default=None, max_length=100),
    bpm_min: int | None = Query(default=None, ge=0),
    bpm_max: int | None = Query(default=None, ge=0),
    key: str | None = Query(default=None, max_length=50),
    model: str | None = Query(default=None, max_length=100),
    sort: discovery.DiscoverSort = "newest",
    limit: int = Query(default=20, ge=1, le=50),
    cursor: str | None = None,
) -> DiscoverClipsResponse:
    """Public clips, keyset-paged: pass ``next_cursor`` back as ``cursor`` with the same filters."""
    clips, next_cursor, total = await discovery.list_public_clips(
        q=q, style=style, bpm_min=bpm_min, bpm_max=bpm_max, key=key, model=model, sort=sort, limit=limit, cursor=cursor
    )
    return DiscoverClipsResponse(
        clips=[PublicClipResponse.from_clip_for(clip, None) for clip in clips], next_cursor=next_cursor, total=total
    )


@router.get("/facets", response_model=DiscoverFacetsResponse)
async def public_facets() -> DiscoverFacetsResponse:
    """The musical keys and models present in the public pool, for Search's filter options."""
    return DiscoverFacetsResponse(**await discovery.public_facets())
