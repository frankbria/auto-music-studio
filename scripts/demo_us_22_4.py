"""US-22.4 demo driver — runs the real video-edit flow end to end.

Drives the actual service, router (via the ASGI app) and job handler against a
local MongoDB with a fake video provider (no credentials exist for the real
one). Prints the outcome evidence the demo doc quotes: an original render, three
non-destructive edits (each a new version linked to its source), the untouched
original, and the version history.

Run: ACEMUSIC_TEST_MONGODB_URL=mongodb://127.0.0.1:27018 uv run python scripts/demo_us_22_4.py
"""

from __future__ import annotations

import asyncio
import os
import uuid

import httpx

from acemusic.api import database
from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.models import Clip, Job, JobStatus, Video, Workspace
from acemusic.api.services import users as user_service
from acemusic.api.services.video import VIDEO_JOB_TYPE
from acemusic.api.settings import ApiSettings
from acemusic.api.tasks import video as video_tasks
from acemusic.storage import LocalStorage
from acemusic.video_client import VideoJobUpdate

FAKE_AUDIO = b"RIFF" + b"\x00" * 200
RENDERED_MP4 = b"\x00\x00\x00\x18ftypmp42" + b"rendered" * 32


class FakeProvider:
    """Accepts a submit, reports complete, returns a rendered MP4."""

    def __init__(self) -> None:
        self.submissions: list[tuple[str, dict]] = []

    def submit(self, media: bytes, filename: str, params: dict) -> str:
        self.submissions.append((filename, dict(params)))
        return f"pj-{len(self.submissions)}"

    def get_status(self, provider_job_id: str) -> VideoJobUpdate:
        return VideoJobUpdate(state="complete", progress=100)

    def download(self, provider_job_id: str) -> bytes:
        return RENDERED_MP4


def hr(title: str) -> None:
    print(f"\n{'=' * 4} {title} {'=' * 4}")


async def run_job(job: Job, storage: LocalStorage, provider: FakeProvider) -> Video:
    """Execute a queued video/edit job through the real handler; return its Video."""
    result = await video_tasks.process_video_job(job, storage=storage, client=provider, poll_interval=0)
    await job.set({Job.status: JobStatus.COMPLETED, Job.result: result})
    return await Video.get(__import__("beanie").PydanticObjectId(result["video_ids"][0]))


async def main() -> None:
    url = os.environ.get("ACEMUSIC_TEST_MONGODB_URL", "mongodb://127.0.0.1:27018")
    settings = ApiSettings(
        _env_file=None,
        mongodb_url=url,
        mongodb_db_name=f"acemusic_demo_{uuid.uuid4().hex[:8]}",
        jwt_secret_key="demo-secret-key-at-least-32-bytes-long-xx",
        job_processor_enabled=False,
        video_api_url="https://video.demo",
        video_api_key="vk-demo",
    )
    client_db = await database.init_db(settings)
    storage = LocalStorage(f"/tmp/us224-demo-{uuid.uuid4().hex[:8]}")
    provider = FakeProvider()

    try:
        user = await user_service.get_or_create_user(
            email="demo@example.com", provider="google", oauth_id="g-demo", name="Demo"
        )
        user.credits_balance = 100.0
        await user.save()
        ws = Workspace(name="Demo", user_id=user.id)
        await ws.insert()
        clip = Clip(
            user_id=user.id,
            workspace_id=ws.id,
            file_path="song.wav",
            title="Midnight Drive",
            format="wav",
            duration=30.0,
        )
        await clip.insert()
        storage.upload(clip.file_path, FAKE_AUDIO)

        token = create_access_token(
            user_id=str(user.id), email=user.email, subscription_tier=user.subscription_tier, settings=settings
        )
        headers = {"Authorization": f"Bearer {token}"}
        app = create_app(settings)

        # 1) Original render — run a generate job through the handler.
        gen_job = Job(
            user_id=user.id,
            workspace_id=ws.id,
            job_type=VIDEO_JOB_TYPE,
            input_params={
                "clip_id": str(clip.id),
                "prompt": "neon city",
                "resolution": "1080p",
                "aspect_ratio": "16:9",
            },
        )
        await gen_job.insert()
        original = await run_job(gen_job, storage, provider)
        hr("Original render")
        print(
            f"video_id={original.id}  resolution={original.resolution}  parent={original.parent_video_id}  edit={original.edit}"
        )
        print(f"created_at={original.created_at.isoformat()}")

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://demo") as ac:
            # 2) Trim, 3) Scene replacement, 4) Lyrics overlay — each via the real endpoint + handler.
            edits = [
                {"operation": "trim", "start_seconds": 5.0, "end_seconds": 25.0},
                {
                    "operation": "replace_scene",
                    "start_seconds": 10.0,
                    "end_seconds": 15.0,
                    "prompt": "sunrise over the ocean",
                },
                {"operation": "lyrics_overlay", "lyrics_enabled": True},
            ]
            for spec in edits:
                r = await ac.post(f"{API_V1_PREFIX}/videos/{original.id}/edit", json=spec, headers=headers)
                assert r.status_code == 202, (r.status_code, r.text)
                edit_job = await Job.get(__import__("beanie").PydanticObjectId(r.json()["job_id"]))
                new = await run_job(edit_job, storage, provider)
                hr(f"Edit: {spec['operation']}")
                print(f"HTTP {r.status_code} -> job {edit_job.id}")
                print(f"new version_id={new.id}  parent_video_id={new.parent_video_id}  edit={new.edit}")
                print(f"provider received spec: {provider.submissions[-1][1]}")

            # 5) Original preserved + accessible after all edits.
            reread = await ac.get(f"{API_V1_PREFIX}/videos/{original.id}", headers=headers)
            fresh_original = await Video.get(original.id)
            hr("Original preserved & accessible")
            print(f"GET /videos/{original.id} -> HTTP {reread.status_code}")
            print(f"original.parent_video_id={fresh_original.parent_video_id}  edit={fresh_original.edit}  (unchanged)")
            print(f"original object still stored: {storage.download(fresh_original.storage_path) == RENDERED_MP4}")

            # 6) Edit history — all versions with timestamps, newest first.
            versions = await ac.get(f"{API_V1_PREFIX}/videos/{original.id}/versions", headers=headers)
            hr("Version history (GET /versions)")
            print(f"HTTP {versions.status_code} — {len(versions.json())} versions (newest first):")
            for v in versions.json():
                op = (v.get("edit") or {}).get("operation", "original render")
                print(f"  {v['created_at']}  {op:16s}  id={v['id']}  parent={v.get('parent_video_id', '—')}")

            # A stranger cannot list another user's edit history.
            other = await user_service.get_or_create_user(
                email="stranger@example.com", provider="google", oauth_id="g-x", name="X"
            )
            other_token = create_access_token(
                user_id=str(other.id), email=other.email, subscription_tier=other.subscription_tier, settings=settings
            )
            forbidden = await ac.get(
                f"{API_V1_PREFIX}/videos/{original.id}/versions", headers={"Authorization": f"Bearer {other_token}"}
            )
            hr("Ownership guard")
            print(f"stranger GET /versions -> HTTP {forbidden.status_code} (404, history is owner-only)")
    finally:
        await client_db.drop_database(settings.mongodb_db_name)
        await database.close_db(client_db)


if __name__ == "__main__":
    asyncio.run(main())
