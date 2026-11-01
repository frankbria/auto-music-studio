"""API datetimes carry their UTC offset (#541).

Mongo drops tzinfo on the round trip, so without a timezone-aware client a response says
``2026-09-21T23:32:56.360000`` and a browser reads it as local time. Every timestamp must
end in an offset, which is what lets the web parse it with plain ``new Date``.
"""

from datetime import datetime

import httpx
import pytest
from beanie import PydanticObjectId

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.models import Clip, Workspace
from acemusic.api.settings import ApiSettings
from tests.users import make_user


@pytest.fixture
def settings(mongo_db, mongo_settings) -> ApiSettings:
    return mongo_settings.model_copy(
        update={"jwt_secret_key": "test-secret-key-at-least-32-bytes-long-xx", "job_processor_enabled": False}
    )


@pytest.mark.integration
async def test_a_stored_timestamp_comes_back_with_its_utc_offset(settings) -> None:
    owner = await make_user("tz@example.com")
    workspace = await Workspace(name="WS", user_id=owner.id).insert()
    clip = await Clip(
        id=PydanticObjectId(), user_id=owner.id, workspace_id=workspace.id, file_path="x.wav", format="wav"
    ).insert()
    token = create_access_token(
        user_id=str(owner.id), email=owner.email, subscription_tier=owner.subscription_tier, settings=settings
    )
    transport = httpx.ASGITransport(app=create_app(settings))
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.get(f"{API_V1_PREFIX}/clips/{clip.id}", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200, resp.text
    created_at = resp.json()["created_at"]
    assert created_at.endswith(("Z", "+00:00")), created_at
    assert datetime.fromisoformat(created_at).utcoffset().total_seconds() == 0
