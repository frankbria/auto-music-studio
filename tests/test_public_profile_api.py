"""Public creator profiles (#654): the read behind /@handle, from real users and their public clips."""

import itertools
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from beanie import PydanticObjectId

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.models import Clip, VisibilityState, Workspace
from acemusic.api.settings import ApiSettings
from tests.users import make_user

PROFILES_URL = f"{API_V1_PREFIX}/discover/profiles"
_SEQ = itertools.count(1)
_BASE_TIME = datetime(2026, 10, 1, tzinfo=timezone.utc)


@pytest.fixture
def settings(mongo_db, mongo_settings) -> ApiSettings:
    return mongo_settings.model_copy(
        update={"jwt_secret_key": "test-secret-key-at-least-32-bytes-long-xx", "job_processor_enabled": False}
    )


@pytest.fixture
async def client(settings):
    transport = httpx.ASGITransport(app=create_app(settings))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


async def _creator(handle: str = "nova", **fields):
    return await make_user(
        f"profile-{next(_SEQ)}@example.com",
        handle=handle,
        display_name="Nova Bloom",
        bio="Synthwave at 2am.",
        style_tags=["synthwave"],
        **fields,
    )


async def _clip(owner, *, minutes: int = 0, visibility=VisibilityState.PUBLIC, **fields) -> Clip:
    workspace = Workspace(name=f"WS-{next(_SEQ)}", user_id=owner.id)
    await workspace.insert()
    clip = Clip(
        id=PydanticObjectId(),
        user_id=owner.id,
        workspace_id=workspace.id,
        file_path="x.wav",
        format="wav",
        visibility=visibility,
        created_at=_BASE_TIME + timedelta(minutes=minutes),
        **{"title": "Song", "style_tags": ["synthwave"], **fields},
    )
    await clip.insert()
    return clip


@pytest.mark.integration
class TestPublicProfile:
    async def test_profile_shows_the_creator_and_only_their_public_clips_newest_first(self, client) -> None:
        nova = await _creator()
        older = await _clip(nova, title="Older", minutes=0)
        newer = await _clip(nova, title="Newer", minutes=5)
        await _clip(nova, title="Private", visibility=VisibilityState.PRIVATE)
        await _clip(nova, title="Removed", removed_at=_BASE_TIME)
        await _clip(await _creator(handle="ember"), title="Someone else's")

        resp = await client.get(f"{PROFILES_URL}/nova")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert (body["handle"], body["display_name"], body["bio"], body["style_tags"]) == (
            "nova",
            "Nova Bloom",
            "Synthwave at 2am.",
            ["synthwave"],
        )
        assert body["joined_at"]
        assert [c["id"] for c in body["clips"]] == [str(newer.id), str(older.id)]
        assert all(c["is_owner"] is False for c in body["clips"])
        assert "email" not in body

    async def test_a_leading_at_sign_is_accepted(self, client) -> None:
        await _creator()
        assert (await client.get(f"{PROFILES_URL}/@nova")).status_code == 200

    @pytest.mark.parametrize("handle", ["nobody", "Nova"])
    async def test_an_unknown_handle_is_404(self, client, handle) -> None:
        await _creator()
        resp = await client.get(f"{PROFILES_URL}/{handle}")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Profile not found."

    async def test_a_banned_creator_has_no_public_profile(self, client) -> None:
        await _creator(banned_at=datetime.now(timezone.utc))
        assert (await client.get(f"{PROFILES_URL}/nova")).status_code == 404

    async def test_the_creator_sees_their_own_clips_marked(self, client, settings) -> None:
        nova = await _creator()
        await _clip(nova)
        token = create_access_token(
            user_id=str(nova.id), email=nova.email, subscription_tier=nova.subscription_tier, settings=settings
        )

        resp = await client.get(f"{PROFILES_URL}/nova", headers={"Authorization": f"Bearer {token}"})

        assert [c["is_owner"] for c in resp.json()["clips"]] == [True]
