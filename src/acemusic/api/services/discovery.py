"""Public discovery listings for Feed, Explore and Search (#651).

Every listing reads the shared public pool, :func:`services.clips.public_clip_filter`.
"""

import re
from typing import Literal

from fastapi import HTTPException, status

from ..models import Clip
from .clips import public_clip_filter
from .common import coerce_object_id
from .moderation import after_cursor, decode_cursor, encode_cursor

DiscoverSort = Literal["newest", "relevance"]

_NEWEST = [("created_at", -1), ("_id", -1)]


def _text_criteria(q: str, style: str | None) -> dict:
    criteria: dict = {}
    if q:
        # shortcut: an unanchored regex over the public pool (bounded by the is_public index, scanned
        # again for total); move to a search index once the public pool reaches tens of thousands.
        needle = re.compile(re.escape(q), re.IGNORECASE)
        criteria["$or"] = [{"title": needle}, {"style_tags": needle}, {"lyrics": needle}]
    style = (style or "").strip()
    if style:
        # Generated clips store their whole style prompt as one tag ("dark hip hop beat"), so a
        # genre is a whole word or phrase inside a tag, and a slug's hyphen matches a space too.
        phrase = r"[\s-]".join(re.escape(word) for word in re.split(r"[\s-]+", style))
        criteria["style_tags"] = re.compile(rf"\b{phrase}\b", re.IGNORECASE)
    return criteria


def _exact_criteria(bpm_min: int | None, bpm_max: int | None, key: str | None, model: str | None) -> dict:
    bpm = {op: value for op, value in (("$gte", bpm_min), ("$lte", bpm_max)) if value is not None}
    return {field: value for field, value in (("bpm", bpm), ("key", key), ("model", model)) if value}


def _relevance_score(q: str) -> dict:
    """The old client-side ranking (title prefix 5, title 3, a tag 2, lyrics 1), computed in Mongo."""

    def matches(field: str, pattern: str) -> dict:
        return {"$regexMatch": {"input": {"$ifNull": [field, ""]}, "regex": pattern, "options": "i"}}

    needle = re.escape(q)
    title = {"$cond": [matches("$title", f"^{needle}"), 5, {"$cond": [matches("$title", needle), 3, 0]}]}
    tags = {
        "$anyElementTrue": [
            {"$map": {"input": {"$ifNull": ["$style_tags", []]}, "as": "tag", "in": matches("$$tag", needle)}}
        ]
    }
    return {"$add": [title, {"$cond": [tags, 2, 0]}, {"$cond": [matches("$lyrics", needle), 1, 0]}]}


def _after_relevance(cursor: str | None) -> dict:
    if not cursor:
        return {}
    score, at, last_id = decode_cursor("discover_relevance", cursor)
    oid = coerce_object_id(last_id)
    if oid is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Invalid cursor.")
    return {
        "$or": [
            {"score": {"$lt": score}},
            {"score": score, "created_at": {"$lt": at}},
            {"score": score, "created_at": at, "_id": {"$lt": oid}},
        ]
    }


async def _by_relevance(match: dict, q: str, limit: int, cursor: str | None) -> tuple[list[Clip], str | None]:
    rows = (
        await Clip.find(match)
        .aggregate(
            [
                {"$addFields": {"score": _relevance_score(q)}},
                {"$match": _after_relevance(cursor)},
                {"$sort": {"score": -1, "created_at": -1, "_id": -1}},
                {"$limit": limit + 1},
            ]
        )
        .to_list()
    )
    page = rows[:limit]
    clips = [Clip.model_validate(row) for row in page]
    if len(rows) <= limit:
        return clips, None
    last = page[-1]
    return clips, encode_cursor("discover_relevance", (last["score"], last["created_at"], str(last["_id"])))


async def _by_newest(match: dict, limit: int, cursor: str | None) -> tuple[list[Clip], str | None]:
    rows = await Clip.find(match, after_cursor("discover_newest", cursor)).sort(_NEWEST).limit(limit + 1).to_list()
    page = rows[:limit]
    if len(rows) <= limit:
        return page, None
    return page, encode_cursor("discover_newest", (page[-1].created_at, str(page[-1].id)))


async def list_public_clips(
    *,
    q: str = "",
    style: str | None = None,
    bpm_min: int | None = None,
    bpm_max: int | None = None,
    key: str | None = None,
    model: str | None = None,
    sort: DiscoverSort = "newest",
    limit: int = 20,
    cursor: str | None = None,
) -> tuple[list[Clip], str | None, int]:
    """One keyset page of the public pool, its next cursor, and how many clips match in all.

    ``relevance`` with no query ranks newest, as the client-side search did.
    """
    q = q.strip()
    match = {**await public_clip_filter(), **_text_criteria(q, style), **_exact_criteria(bpm_min, bpm_max, key, model)}
    total = await Clip.find(match).count()
    if sort == "relevance" and q:
        clips, next_cursor = await _by_relevance(match, q, limit, cursor)
    else:
        clips, next_cursor = await _by_newest(match, limit, cursor)
    return clips, next_cursor, total


async def public_facets() -> dict[str, list[str]]:
    """The keys and models present in the public pool, for Search's filter options."""
    pool = await public_clip_filter()
    return {
        "keys": sorted(v for v in await Clip.find(pool).distinct("key") if v),
        "models": sorted(v for v in await Clip.find(pool).distinct("model") if v),
    }
