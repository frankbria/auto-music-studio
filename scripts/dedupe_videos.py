"""Remove duplicate ``Video`` documents per ``job_id``, keeping the earliest (#427).

#427 adds a unique index on ``videos.job_id``. Beanie builds it at API startup,
so a database that already holds two ``Video`` documents for one job (only
possible if the stale-requeue race ever ran under more than one worker process)
would refuse to start with an ``E11000`` error. Run this once against that
database first. Duplicates from that race point at the same storage object, so
dropping all but the earliest loses nothing.

Talks to MongoDB directly — deliberately NOT through Beanie, whose init would
try to build the very index this is clearing the way for.

Usage (dry run by default; nothing is deleted without ``--apply``)::

    uv run python scripts/dedupe_videos.py           # report duplicate groups
    uv run python scripts/dedupe_videos.py --apply   # delete the later copies

Connection comes from ``ACEMUSIC_API_MONGODB_URL`` / ``ACEMUSIC_API_MONGODB_DB_NAME``
(the API's own settings).
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

from pymongo import AsyncMongoClient
from pymongo.asynchronous.collection import AsyncCollection


async def dedupe(videos: AsyncCollection, *, apply: bool) -> dict[Any, list[Any]]:
    """Return ``{job_id: [ids that are (or would be) deleted]}``; delete them when ``apply``."""
    cursor = await videos.aggregate(
        [
            {"$sort": {"created_at": 1, "_id": 1}},
            {"$group": {"_id": "$job_id", "ids": {"$push": "$_id"}, "n": {"$sum": 1}}},
            {"$match": {"n": {"$gt": 1}}},
        ]
    )
    groups = await cursor.to_list()
    doomed = {group["_id"]: group["ids"][1:] for group in groups}  # keep the earliest of each
    if apply and doomed:
        await videos.delete_many({"_id": {"$in": [i for ids in doomed.values() for i in ids]}})
    return doomed


async def main(apply: bool) -> None:
    from acemusic.api.settings import ApiSettings

    settings = ApiSettings()
    client = AsyncMongoClient(settings.mongodb_url)
    try:
        doomed = await dedupe(client[settings.mongodb_db_name]["videos"], apply=apply)
    finally:
        await client.close()
    if not doomed:
        print("no duplicate videos per job_id")
        return
    for job_id, ids in doomed.items():
        print(
            f"job {job_id}: {'deleted' if apply else 'would delete'} {len(ids)} later cop{'y' if len(ids) == 1 else 'ies'}"
        )
    if not apply:
        print("dry run — re-run with --apply to delete")


if __name__ == "__main__":
    asyncio.run(main(apply="--apply" in sys.argv[1:]))
