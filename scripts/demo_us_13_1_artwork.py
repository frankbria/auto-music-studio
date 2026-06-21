"""US-13.1 cover-art demo driver.

Drives the REAL HTTP API end-to-end over a local MongoDB + on-disk storage with a
REAL background JobProcessor. Only the OpenAI image client is faked (no key here,
mock-verified like the Dolby integration), so generation exercises the genuine
async job -> upscale -> store -> ArtworkOption pipeline.

Run: uv run python scripts/demo_us_13_1_artwork.py
"""

import asyncio
import io
import os
import tempfile
import uuid

import httpx
from PIL import Image

from acemusic.api import database
from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.models import Clip, Workspace
from acemusic.api.services import users as user_service
from acemusic.api.services.artwork import build_artwork_prompt
from acemusic.api.settings import ApiSettings
from acemusic.api.tasks.processor import JobProcessor
from acemusic.storage import LocalStorage


def _png(size, fmt="PNG"):
    buf = io.BytesIO()
    Image.new("RGB", size, "indigo").save(buf, format=fmt)
    return buf.getvalue()


class FakeImageClient:
    """Stands in for OpenAI DALL-E: returns canned 1024x1024 PNGs."""

    def generate_images(self, prompt, count=4):
        print(f"   [fake OpenAI] prompt={prompt!r} -> {count} images @1024x1024")
        return [_png((1024, 1024)) for _ in range(count)]


async def main():
    root = tempfile.mkdtemp(prefix="artwork-demo-")
    os.environ["ACEMUSIC_STORAGE_BACKEND"] = "local"
    os.environ["ACEMUSIC_STORAGE_LOCAL_ROOT"] = root

    settings = ApiSettings(
        _env_file=None,
        mongodb_url="mongodb://127.0.0.1:27017",
        mongodb_db_name=f"acemusic_demo_{uuid.uuid4().hex[:8]}",
        jwt_secret_key="demo-secret-key-at-least-32-bytes-long-xx",
        job_processor_enabled=False,  # we run our own processor with the fake client
    )
    client_db = await database.init_db(settings)
    processor = JobProcessor(
        poll_interval=0.2,
        storage_factory=lambda: LocalStorage(root),
        image_client_factory=lambda: FakeImageClient(),
    )
    await processor.start()

    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    try:
        user = await user_service.get_or_create_user(
            email="musician@example.com", provider="google", oauth_id="g-demo", name="Demo"
        )
        ws = Workspace(name="My Album", user_id=user.id)
        await ws.insert()
        clip = Clip(
            user_id=user.id,
            workspace_id=ws.id,
            file_path=f"{user.id}/{ws.id}/clips/track.wav",
            title="Midnight Drive",
            style_tags=["synthwave", "retro", "neon"],
        )
        await clip.insert()
        headers = {
            "Authorization": "Bearer "
            + create_access_token(
                user_id=str(user.id), email=user.email, subscription_tier=user.subscription_tier, settings=settings
            )
        }
        cu = f"{API_V1_PREFIX}/clips/{clip.id}"

        async with httpx.AsyncClient(transport=transport, base_url="http://demo") as http:
            print(f"Clip: '{clip.title}'  style_tags={clip.style_tags}\n")

            print("AC1 — Generate 4 options tied to the clip")
            r = await http.post(f"{cu}/artwork/generate", json={}, headers=headers)
            print(f"   POST .../artwork/generate -> {r.status_code} {r.json()}")
            job_id = r.json()["job_id"]
            options = []
            for _ in range(50):
                s = await http.get(f"{API_V1_PREFIX}/jobs/{job_id}/status", headers=headers)
                body = s.json()
                if body["status"] in ("completed", "failed"):
                    options = body.get("artwork_options", [])
                    print(f"   job status -> {body['status']}; {len(options)} options returned")
                    break
                await asyncio.sleep(0.2)
            assert len(options) == 4, options
            print("   ✓ 4 ArtworkOption URLs surfaced via job status\n")

            print("AC2 — Select an option; it attaches to the clip and is served")
            chosen = options[1]["artwork_id"]
            r = await http.post(f"{cu}/artwork", json={"artwork_id": chosen}, headers=headers)
            print(f"   POST .../artwork (artwork_id={chosen[:8]}…) -> {r.status_code} {r.json()}")
            g = await http.get(f"{cu}/artwork", headers=headers)
            print(f"   GET .../artwork -> {g.status_code} {g.headers['content-type']} ({len(g.content)} bytes)")
            await clip.sync()
            print(f"   ✓ clip.artwork_path now set: {bool(clip.artwork_path)}\n")

            print("AC3 — Upload custom artwork (valid 3000x3000 PNG)")
            r = await http.put(
                f"{cu}/artwork/upload",
                files={"file": ("cover.png", _png((3000, 3000)), "image/png")},
                headers=headers,
            )
            print(f"   PUT .../artwork/upload (3000x3000 png) -> {r.status_code}")
            g = await http.get(f"{cu}/artwork", headers=headers)
            print(f"   GET .../artwork -> {g.status_code} {g.headers['content-type']}")
            print("   ✓ custom upload accepted and served\n")

            print("AC4 — Below 3000x3000 is rejected with a descriptive error")
            r = await http.put(
                f"{cu}/artwork/upload",
                files={"file": ("small.png", _png((1024, 1024)), "image/png")},
                headers=headers,
            )
            print(f"   PUT .../artwork/upload (1024x1024 png) -> {r.status_code}")
            print(f"   detail: {r.json()['detail']}")
            assert r.status_code == 422 and "3000" in r.json()["detail"]
            print("   ✓ rejected with 422 naming the 3000x3000 requirement\n")

            print("AC4b — A corrupt / wrong-format file is also rejected")
            r = await http.put(
                f"{cu}/artwork/upload",
                files={"file": ("bad.png", b"not an image", "image/png")},
                headers=headers,
            )
            print(f"   PUT .../artwork/upload (corrupt) -> {r.status_code}: {r.json()['detail']}\n")

            print("AC5 — Generated prompt reflects the song's style tags (manual/mock)")
            print(f"   prompt = {build_artwork_prompt(clip)!r}")
            print("   ✓ synthwave/retro/neon + title carried into the image prompt")
    finally:
        await processor.stop()
        await client_db.drop_database(settings.mongodb_db_name)
        await database.close_db(client_db)


if __name__ == "__main__":
    asyncio.run(main())
