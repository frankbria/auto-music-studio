"""US-16.4 demo: live response from GET /api/v1/models (no DB required).

Drives the real FastAPI app over httpx ASGITransport — the same code path the
server serves — and prints the actual JSON the frontend selector consumes,
proving the endpoint returns all six models with display metadata and the
Pro-only flags the UI renders.
"""

import asyncio
import json

import httpx

from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.settings import ApiSettings
from acemusic.constants import MODELS


async def main() -> None:
    app = create_app(ApiSettings(jwt_secret_key="demo-secret-key-at-least-32-bytes-long-xx"))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://demo") as client:
        resp = await client.get(f"{API_V1_PREFIX}/models")
        print(f"GET {API_V1_PREFIX}/models -> {resp.status_code} (no Authorization header sent)\n")
        body = resp.json()
        for m in body["models"]:
            pro = "  [Pro]" if m["pro_only"] else ""
            print(f"  {m['key']:<9} {m['display_name']:<32} cat={m['category']:<9} {m['vram']:>7}{pro}")
        keys = {m["key"] for m in body["models"]}
        print(
            f"\n  models returned: {len(body['models'])}  ==  registry size: {len(MODELS)}: {keys == set(MODELS.keys())}"
        )
        pro_keys = sorted(m["key"] for m in body["models"] if m["pro_only"])
        print(f"  pro-only (lock + badge for free tier): {pro_keys}")


if __name__ == "__main__":
    asyncio.run(main())
