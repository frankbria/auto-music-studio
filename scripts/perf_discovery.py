"""Scale check for #338: discovery reads over 20k public clips and 200k engagement rows in a throwaway database.

Needs a local MongoDB on 27017. Creates and drops ``acemusic_perf_338``; touches nothing else.

    uv run python scripts/perf_discovery.py
"""

import asyncio
import random
import statistics
import time
from datetime import timedelta

from beanie import PydanticObjectId

from acemusic.api.database import close_db, init_db
from acemusic.api.models import Clip, ClipEngagement
from acemusic.api.models.common import utcnow
from acemusic.api.services import discovery
from acemusic.api.settings import ApiSettings

CLIPS, ROWS, RUNS = 20_000, 200_000, 30


async def main() -> None:
    settings = ApiSettings(
        _env_file=None,
        mongodb_url="mongodb://127.0.0.1:27017",
        mongodb_db_name="acemusic_perf_338",
        jwt_secret_key="x" * 40,
    )
    client = await init_db(settings)
    await client.drop_database("acemusic_perf_338")
    client = await init_db(settings)
    now, owner, workspace = utcnow(), PydanticObjectId(), PydanticObjectId()
    clips = [
        {
            "_id": PydanticObjectId(),
            "user_id": owner,
            "workspace_id": workspace,
            "file_path": "x.wav",
            "format": "wav",
            "title": f"Song {i} {random.choice(['night', 'drive', 'river', 'glass', 'harbor'])}",
            "style_tags": ["lofi"],
            "is_public": True,
            "visibility": "public",
            "removed_at": None,
            "owner_banned_at": None,
            "play_count": random.randint(0, 5000),
            "like_count": 0,
            "share_count": 0,
            "staff_picked_at": now - timedelta(hours=i) if i % 200 == 0 else None,
            "created_at": now - timedelta(minutes=i),
            "parent_clip_ids": [],
            "moderation_flags": [],
        }
        for i in range(CLIPS)
    ]
    await Clip.get_pymongo_collection().insert_many(clips)
    ids = [c["_id"] for c in clips]
    rows = [
        {
            "clip_id": random.choice(ids),
            "kind": random.choice(["play"] * 8 + ["like", "share"]),
            "actor": f"u{n}",
            "bucket": str(n),
            "created_at": now - timedelta(minutes=random.randint(0, 7 * 24 * 60)),
        }
        for n in range(ROWS)
    ]
    await ClipEngagement.get_pymongo_collection().insert_many(rows)
    for sort, q in [
        ("newest", ""),
        ("popular", ""),
        ("staff_picks", ""),
        ("relevance", "river glass"),
        ("trending_24h", ""),
        ("trending_7d", ""),
    ]:
        times = []
        for _ in range(RUNS):
            started = time.perf_counter()
            await discovery.list_public_clips(sort=sort, q=q, limit=20)
            times.append((time.perf_counter() - started) * 1000)
        times.sort()
        print(f"{sort:13} p50={statistics.median(times):7.1f}ms p95={times[int(RUNS * 0.95) - 1]:7.1f}ms")
    await client.drop_database("acemusic_perf_338")
    await close_db()


asyncio.run(main())
