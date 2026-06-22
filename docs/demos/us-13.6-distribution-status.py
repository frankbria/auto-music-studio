"""US-13.6 demo harness — drives the real API + poller against local MongoDB.

Each acceptance criterion is exercised end-to-end with real persistence and the
actual response printed as outcome evidence. SoundCloud's gated HTTP API is the
only stubbed seam (a fake status fetcher returns real SoundCloud-shaped payloads);
everything else is the production code path.
"""

import asyncio
import uuid
from datetime import datetime, timezone

import httpx

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.database import close_db, init_db
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.models import Clip, NotificationEvent, Release, Workspace
from acemusic.api.models.distribution import SOUNDCLOUD_CHANNEL, DistributionStatus
from acemusic.api.services import users as user_service
from acemusic.api.services.mastering import APPROVED_GENERATION_MODE
from acemusic.api.settings import ApiSettings
from acemusic.api.tasks.soundcloud_poller import SoundCloudStatusPoller

RELEASES = f"{API_V1_PREFIX}/releases"


def hdr(title: str) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


async def main() -> None:
    settings = ApiSettings(
        _env_file=None,
        mongodb_url="mongodb://localhost:27017",
        mongodb_db_name=f"acemusic_demo_{uuid.uuid4().hex[:8]}",
        jwt_secret_key="demo-secret-key-at-least-32-bytes-long-xx",
        job_processor_enabled=False,
        soundcloud_poller_enabled=False,
    )
    client = await init_db(settings)
    try:
        app = create_app(settings)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://demo") as http:
            user = await user_service.get_or_create_user(
                email="demo@example.com", provider="google", oauth_id="g-demo", name="Demo"
            )
            token = create_access_token(
                user_id=str(user.id), email=user.email, subscription_tier=user.subscription_tier, settings=settings
            )
            auth = {"Authorization": f"Bearer {token}"}

            # A mastered clip + a release built from it.
            ws = Workspace(name="Demo WS", user_id=user.id)
            await ws.insert()
            clip = Clip(
                user_id=user.id,
                workspace_id=ws.id,
                file_path=f"{user.id}/{ws.id}/clips/demo.wav",
                format="wav",
                title="Demo Track",
                generation_mode=APPROVED_GENERATION_MODE,
                artwork_path=f"{user.id}/art/demo.png",
            )
            await clip.insert()
            created = (
                await http.post(
                    RELEASES,
                    json={
                        "clip_id": str(clip.id),
                        "title": "Demo Track",
                        "artist": "Demo Artist",
                        "genre": "house",
                        "release_date": "2026-08-01T00:00:00Z",
                    },
                    headers=auth,
                )
            ).json()
            rid = created["id"]
            print(f"Created release {rid} (clip {clip.id}); clip.is_public = {clip.is_public}")

            # ---- AC5: transitions follow the valid sequence ------------------
            hdr("AC5: status transitions follow the valid sequence (no skipping)")
            skip = await http.patch(
                f"{RELEASES}/{rid}/channels/landr/status", json={"status": "live"}, headers=auth
            )
            print(f"draft → live (skip) ......... HTTP {skip.status_code}: {skip.json()['detail']}")
            ok = await http.patch(
                f"{RELEASES}/{rid}/channels/landr/status", json={"status": "ready"}, headers=auth
            )
            print(f"draft → ready (valid step) .. HTTP {ok.status_code}: {ok.json()}")

            # ---- AC3: manual guided updates are stored and visible ------------
            hdr("AC3: manual status updates for guided channels are stored and visible")
            for step in ("submitted", "in_review"):
                r = await http.patch(
                    f"{RELEASES}/{rid}/channels/landr/status", json={"status": step}, headers=auth
                )
                print(f"landr → {step:10} HTTP {r.status_code}: {r.json()}")
            # SoundCloud is automated → manual update rejected.
            sc_manual = await http.patch(
                f"{RELEASES}/{rid}/channels/soundcloud/status", json={"status": "ready"}, headers=auth
            )
            print(f"soundcloud (manual) ......... HTTP {sc_manual.status_code}: {sc_manual.json()['detail']}")
            status = (await http.get(f"{RELEASES}/{rid}/status", headers=auth)).json()
            print(f"GET /status channels ........ {status['channels']}")

            # ---- AC1: listing shows per-channel status -----------------------
            hdr("AC1: release listing shows per-channel distribution status")
            listing = (await http.get(RELEASES, headers=auth)).json()["releases"][0]
            print(f"listed channel_statuses ..... {listing['channel_statuses']}")
            print(f"listed visibility ........... {listing['visibility']}")

            # ---- AC4: visibility updates the clip's sharing state ------------
            hdr("AC4: visibility changes update the clip's sharing state")
            vis = await http.patch(f"{RELEASES}/{rid}/visibility", json={"state": "public"}, headers=auth)
            refreshed_clip = await Clip.get(clip.id)
            print(f"PATCH visibility=public ..... HTTP {vis.status_code}: visibility={vis.json()['visibility']}")
            print(f"source clip.is_public now ... {refreshed_clip.is_public}  (was False)")

            # ---- AC2: SoundCloud status reflects actual track state ----------
            hdr("AC2: SoundCloud status reflects actual track state (polled via API)")
            scr = Release(
                clip_id=clip.id,
                user_id=user.id,
                title="SoundCloud Track",
                artist="Demo Artist",
                genre="house",
                release_date=datetime.now(timezone.utc),
                soundcloud_track_id="555",
                channel_statuses={SOUNDCLOUD_CHANNEL: DistributionStatus.SUBMITTED},
            )
            await scr.insert()
            print(f"SoundCloud release {scr.id} starts at: submitted")

            class _Conn:
                access_token = "tok"

            async def _conn(uid, _s):
                return _Conn()

            # Two poll cycles with real SoundCloud-shaped payloads.
            for state in ({"state": "processing"}, {"state": "finished", "sharing": "public"}):
                async def _fetch(_t, _id, _state=state):
                    return _state

                poller = SoundCloudStatusPoller(settings, connection_getter=_conn, status_fetcher=_fetch)
                changed = await poller.poll_once()
                cur = (await Release.get(scr.id)).channel_statuses[SOUNDCLOUD_CHANNEL].value
                print(f"poll (SoundCloud {state}) → changed={changed}, soundcloud status now: {cur}")

            events = await NotificationEvent.find(NotificationEvent.release_id == scr.id).to_list()
            print(f"notifications recorded ...... {[(e.event_type, e.channel) for e in events]}")

            hdr("All acceptance criteria demonstrated with real outcomes ✓")
    finally:
        await client.drop_database(settings.mongodb_db_name)
        await close_db(client)


if __name__ == "__main__":
    asyncio.run(main())
