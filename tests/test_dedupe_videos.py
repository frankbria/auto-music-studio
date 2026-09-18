"""scripts/dedupe_videos.py (#427): clears duplicate ``Video`` rows per ``job_id`` so the
unique index can be built. Runs against a raw collection on the real local MongoDB —
the ``videos`` collection itself already carries the index and would refuse the
duplicates this test needs to plant."""

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from bson import ObjectId

from acemusic.api import database

_SPEC = importlib.util.spec_from_file_location(
    "dedupe_videos", Path(__file__).resolve().parents[1] / "scripts" / "dedupe_videos.py"
)
dedupe_videos = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(dedupe_videos)


@pytest.mark.integration
class TestDedupeVideos:
    async def _plant(self):
        videos = database.get_database()["videos_dedupe_test"]
        await videos.drop()
        t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
        job_a, job_b = ObjectId(), ObjectId()
        docs = [
            {"job_id": job_a, "created_at": t0 + timedelta(minutes=5), "storage_path": "a.mp4"},  # the later copy
            {"job_id": job_a, "created_at": t0, "storage_path": "a.mp4"},  # the earliest: must survive
            {"job_id": job_b, "created_at": t0, "storage_path": "b.mp4"},  # no duplicate: untouched
        ]
        await videos.insert_many(docs)
        return videos, job_a, docs[1]["_id"]

    async def test_dry_run_reports_and_deletes_nothing(self, mongo_db) -> None:
        videos, job_a, _ = await self._plant()

        doomed = await dedupe_videos.dedupe(videos, apply=False)

        assert list(doomed) == [job_a] and len(doomed[job_a]) == 1
        assert await videos.count_documents({}) == 3

    async def test_apply_keeps_the_earliest_copy_per_job(self, mongo_db) -> None:
        videos, job_a, earliest_id = await self._plant()

        await dedupe_videos.dedupe(videos, apply=True)

        remaining = await videos.find({}, sort=[("storage_path", 1)]).to_list()
        assert [d["storage_path"] for d in remaining] == ["a.mp4", "b.mp4"]
        assert remaining[0]["_id"] == earliest_id
        assert await dedupe_videos.dedupe(videos, apply=False) == {}
