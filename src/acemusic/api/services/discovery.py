"""Public discovery listings for Feed, Explore and Search (#651).

Every listing reads the shared public pool, :func:`services.clips.public_clip_filter`.

Free text uses the ``clip_text_search`` index (#655): whole words, stemmed in English ("loving" finds "love"),
case- and diacritic-insensitive, any word matching. A partial word finds nothing ("lov" does not find "love").
Relevance is the index's weighted score: title 5, style tags 2, lyrics 1.
"""

import re
import time
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import HTTPException, status
from pymongo.errors import ExecutionTimeout

from ..models import Clip, ClipEngagement, User
from .clips import public_clip_filter
from .common import coerce_object_id
from .moderation import after_cursor, decode_cursor, encode_cursor

DiscoverSort = Literal["newest", "relevance", "popular", "trending_24h", "trending_7d", "staff_picks"]

_NEWEST = [("created_at", -1), ("_id", -1)]
# #656 owner decision: trending is plays + 3 x likes + 5 x shares inside the window.
_TRENDING_WINDOWS = {"trending_24h": timedelta(hours=24), "trending_7d": timedelta(days=7)}
_TRENDING_WEIGHTS = {"play": 1, "like": 3, "share": 5}
_LEADING_HYPHENS = re.compile(r"(?<!\S)-+")
# A query past this answers 503 rather than holding a connection: the pool is public and unauthenticated.
MAX_QUERY_MS = 3000
FACETS_TTL_SECONDS = 45.0
_facets_cache: tuple[float, dict[str, list[str]]] | None = None


def _text_criteria(q: str, style: str | None) -> dict:
    criteria: dict = {}
    if q:
        # Quotes and a leading "-" are $text syntax (phrase, negation); a user's search is plain words.
        criteria["$text"] = {"$search": _LEADING_HYPHENS.sub(" ", q.replace('"', " "))}
    words = [word for word in re.split(r"[\s-]+", style or "") if word]
    if words:
        # Generated clips store their whole style prompt as one tag ("dark hip hop beat"), so a
        # genre is a whole word or phrase inside a tag, and a slug's hyphen matches a space too.
        # Lookarounds, not \b, so a style that starts or ends in a symbol ("c++") still anchors.
        phrase = r"[\s-]".join(map(re.escape, words))
        criteria["style_tags"] = re.compile(rf"(?<!\w){phrase}(?!\w)", re.IGNORECASE)
    return criteria


def _exact_criteria(bpm_min: int | None, bpm_max: int | None, key: str | None, model: str | None) -> dict:
    bpm = {op: value for op, value in (("$gte", bpm_min), ("$lte", bpm_max)) if value is not None}
    return {field: value for field, value in (("bpm", bpm), ("key", key), ("model", model)) if value}


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


async def _by_relevance(match: dict, limit: int, cursor: str | None) -> tuple[list[Clip], str | None]:
    # The sort runs over the text-matched rows only; allowDiskUse lifts the 100MB in-memory cap for a broad query.
    rows = (
        await Clip.find(match)
        .aggregate(
            [
                {"$addFields": {"score": {"$meta": "textScore"}}},
                {"$match": _after_relevance(cursor)},
                {"$sort": {"score": -1, "created_at": -1, "_id": -1}},
                {"$limit": limit + 1},
            ],
            allowDiskUse=True,
            maxTimeMS=MAX_QUERY_MS,
        )
        .to_list()
    )
    page = rows[:limit]
    clips = [Clip.model_validate(row) for row in page]
    if len(rows) <= limit:
        return clips, None
    last = page[-1]
    return clips, encode_cursor("discover_relevance", (last["score"], last["created_at"], str(last["_id"])))


async def _count(match: dict) -> int:
    # count_documents directly: Beanie's count() forwards max_time_ms into an aggregate, which rejects it.
    return await Clip.get_pymongo_collection().count_documents(match, maxTimeMS=MAX_QUERY_MS)


async def _by_newest(match: dict, limit: int, cursor: str | None) -> tuple[list[Clip], str | None]:
    rows = await (
        Clip.find(match, after_cursor("discover_newest", cursor), max_time_ms=MAX_QUERY_MS)
        .sort(_NEWEST)
        .limit(limit + 1)
        .to_list()
    )
    page = rows[:limit]
    if len(rows) <= limit:
        return page, None
    return page, encode_cursor("discover_newest", (page[-1].created_at, str(page[-1].id)))


def _after_key(kind: str, cursor: str | None, field: str) -> dict:
    """Rows past ``cursor`` in descending ``(field, _id)`` order; empty on the first page."""
    if not cursor:
        return {}
    value, last_id = decode_cursor(kind, cursor)
    oid = coerce_object_id(last_id)
    if oid is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Invalid cursor.")
    return {"$or": [{field: {"$lt": value}}, {field: value, "_id": {"$lt": oid}}]}


async def _by_field(
    match: dict, field: str, kind: str, limit: int, cursor: str | None
) -> tuple[list[Clip], str | None]:
    rows = await (
        Clip.find(match, _after_key(kind, cursor, field), max_time_ms=MAX_QUERY_MS)
        .sort([(field, -1), ("_id", -1)])
        .limit(limit + 1)
        .to_list()
    )
    page = rows[:limit]
    if len(rows) <= limit:
        return page, None
    return page, encode_cursor(kind, (getattr(page[-1], field), str(page[-1].id)))


async def _by_trending(match: dict, sort: str, limit: int, cursor: str | None) -> tuple[list[Clip], str | None]:
    """Clips by weighted engagement inside the window, keyset-paged on (score, _id) over the public pool."""
    kind = f"discover_{sort}"
    weight = {
        "$switch": {"branches": [{"case": {"$eq": ["$kind", k]}, "then": w} for k, w in _TRENDING_WEIGHTS.items()]}
    }
    rows = await ClipEngagement.aggregate(
        [
            {"$match": {"created_at": {"$gte": datetime.now(timezone.utc) - _TRENDING_WINDOWS[sort]}}},
            {"$group": {"_id": "$clip_id", "score": {"$sum": weight}}},
            {"$match": _after_key(kind, cursor, "score")},
            {"$sort": {"score": -1, "_id": -1}},
            {
                "$lookup": {
                    "from": "clips",
                    "localField": "_id",
                    "foreignField": "_id",
                    "pipeline": [{"$match": match}],
                    "as": "clip",
                }
            },
            {"$unwind": "$clip"},
            {"$limit": limit + 1},
        ],
        allowDiskUse=True,
        maxTimeMS=MAX_QUERY_MS,
    ).to_list()
    page = rows[:limit]
    clips = [Clip.model_validate(row["clip"]) for row in page]
    if len(rows) <= limit:
        return clips, None
    return clips, encode_cursor(kind, (page[-1]["score"], str(page[-1]["_id"])))


async def _page(
    sort: DiscoverSort, q: str, match: dict, limit: int, cursor: str | None
) -> tuple[list[Clip], str | None]:
    if sort == "relevance" and q:
        return await _by_relevance(match, limit, cursor)
    if sort == "popular":
        return await _by_field(match, "play_count", "discover_popular", limit, cursor)
    if sort == "staff_picks":
        return await _by_field(match, "staff_picked_at", "discover_staff_picks", limit, cursor)
    if sort in _TRENDING_WINDOWS:
        return await _by_trending(match, sort, limit, cursor)
    return await _by_newest(match, limit, cursor)


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
) -> tuple[list[Clip], str | None, int | None]:
    """One keyset page of the public pool, its next cursor, and how many clips match in all.

    ``total`` is counted on the first page only (no cursor), and None after it: the caller keeps the first page's.
    ``relevance`` with no query ranks newest, as the client-side search did. A query past ``MAX_QUERY_MS`` is a 503.
    ``trending_*`` has no total and refuses a text query (422).
    """
    q = q.strip()
    if q and sort in _TRENDING_WINDOWS:
        # $text can only lead a pipeline, and trending's leads with the engagement window.
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Trending can't be searched.")
    match = {**await public_clip_filter(), **_text_criteria(q, style), **_exact_criteria(bpm_min, bpm_max, key, model)}
    if sort == "staff_picks":
        match["staff_picked_at"] = {"$ne": None}
    try:
        # Trending ranks only the clips engaged with in its window, so the pool's size is not its total.
        total = None if cursor or sort in _TRENDING_WINDOWS else await _count(match)
        clips, next_cursor = await _page(sort, q, match, limit, cursor)
    except ExecutionTimeout as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Search took too long. Try narrowing it."
        ) from exc
    return clips, next_cursor, total


async def public_facets() -> dict[str, list[str]]:
    """The keys and models present in the public pool, for Search's filter options.

    Cached per process for ``FACETS_TTL_SECONDS``: Search asks on every load, and a filter option missing for
    that long is harmless.
    """
    global _facets_cache
    if _facets_cache is not None and time.monotonic() - _facets_cache[0] < FACETS_TTL_SECONDS:
        return _facets_cache[1]
    facets = await _read_facets()
    _facets_cache = (time.monotonic(), facets)
    return facets


async def _read_facets() -> dict[str, list[str]]:
    pool = await public_clip_filter()
    return {
        "keys": sorted(v for v in await Clip.find(pool).distinct("key") if v),
        "models": sorted(v for v in await Clip.find(pool).distinct("model") if v),
    }


def clear_facets_cache() -> None:
    """For tests, which change the pool between requests in one process."""
    global _facets_cache
    _facets_cache = None


#: shortcut: a profile lists its newest public clips without paging; page it when a creator publishes more than this.
PROFILE_CLIP_LIMIT = 50


async def public_profile(handle: str) -> tuple[User, list[Clip]]:
    """A creator's public profile and newest public clips (#654); 404 for an unknown handle or a banned creator."""
    user = await User.find_one({"handle": handle.removeprefix("@"), "banned_at": None})
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    clips = (
        # $and, not a merged dict: the filter's own user_id predicate is what keeps out a creator banned since.
        await Clip.find({"$and": [await public_clip_filter(), {"user_id": user.id}]})
        .sort(-Clip.created_at, -Clip.id)
        .limit(PROFILE_CLIP_LIMIT)
        .to_list()
    )
    return user, clips
