"""Experimental features on /labs and their rollout from the admin panel (US-28.5, #342)."""

import asyncio

import httpx
import pytest

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.models import ModerationLogEntry, User
from acemusic.api.services import feature_flags
from acemusic.api.settings import ApiSettings
from tests.users import make_user

LABS = f"{API_V1_PREFIX}/labs"
FLAGS = f"{API_V1_PREFIX}/admin/feature-flags"

pytestmark = pytest.mark.integration


@pytest.fixture
def settings(mongo_db, mongo_settings) -> ApiSettings:
    return mongo_settings.model_copy(
        update={"jwt_secret_key": "test-secret-key-at-least-32-bytes-long-xx", "job_processor_enabled": False}
    )


@pytest.fixture
async def client(settings):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(settings)), base_url="http://t") as c:
        yield c


def _auth(user, settings) -> dict[str, str]:
    token = create_access_token(
        user_id=str(user.id), email=user.email, subscription_tier=user.subscription_tier, settings=settings
    )
    return {"Authorization": f"Bearer {token}"}


def _by_key(resp: httpx.Response) -> dict[str, dict]:
    return {e["key"]: e for e in resp.json()["experiments"]}


async def test_labs_lists_the_four_experiments_with_their_stage_and_nothing_on_by_default(client, settings) -> None:
    user = await make_user("labs-default@example.com")

    resp = await client.get(LABS, headers=_auth(user, settings))

    experiments = _by_key(resp)
    assert {k: e["stage"] for k, e in experiments.items()} == {
        "real_time_generation": "alpha",
        "collaborative_workspaces": "alpha",
        "ai_arrangement": "beta",
        "style_transfer": "beta",
    }
    assert not any(e["available"] or e["enabled"] for e in experiments.values())


async def test_an_experiment_not_available_to_you_cant_be_switched_on(client, settings) -> None:
    user = await make_user("labs-closed@example.com")

    resp = await client.put(f"{LABS}/style_transfer", json={"enabled": True}, headers=_auth(user, settings))
    unknown = await client.put(f"{LABS}/time_travel", json={"enabled": True}, headers=_auth(user, settings))

    assert resp.status_code == 403
    assert unknown.status_code == 404


async def test_an_admin_grants_one_user_who_then_switches_it_on(client, settings) -> None:
    admin = await make_user("labs-admin@example.com", is_admin=True)
    granted, other = await make_user("labs-granted@example.com"), await make_user("labs-other@example.com")

    resp = await client.put(f"{FLAGS}/ai_arrangement/users/{granted.email}", headers=_auth(admin, settings))
    assert resp.status_code == 200
    [flag] = [f for f in resp.json()["flags"] if f["key"] == "ai_arrangement"]
    assert flag["users"] == [{"id": str(granted.id), "email": granted.email}]

    switched = await client.put(f"{LABS}/ai_arrangement", json={"enabled": True}, headers=_auth(granted, settings))
    switched_on = _by_key(switched)["ai_arrangement"]
    assert (switched_on["available"], switched_on["enabled"]) == (True, True)
    assert await feature_flags.is_enabled(await User.get(granted.id), "ai_arrangement")
    others = _by_key(await client.get(LABS, headers=_auth(other, settings)))
    assert others["ai_arrangement"]["available"] is False


async def test_a_global_rollout_reaches_everyone_and_rolling_back_keeps_named_grants(client, settings) -> None:
    admin = await make_user("labs-admin2@example.com", is_admin=True)
    named, anyone = await make_user("labs-named@example.com"), await make_user("labs-anyone@example.com")
    await client.put(f"{FLAGS}/style_transfer/users/{named.email}", headers=_auth(admin, settings))

    await client.put(f"{FLAGS}/style_transfer", json={"enabled": True}, headers=_auth(admin, settings))
    assert _by_key(await client.get(LABS, headers=_auth(anyone, settings)))["style_transfer"]["available"]

    await client.put(f"{FLAGS}/style_transfer", json={"enabled": False}, headers=_auth(admin, settings))
    assert not _by_key(await client.get(LABS, headers=_auth(anyone, settings)))["style_transfer"]["available"]
    assert _by_key(await client.get(LABS, headers=_auth(named, settings)))["style_transfer"]["available"]


async def test_revoking_turns_it_off_even_for_a_user_who_switched_it_on(client, settings) -> None:
    admin = await make_user("labs-admin3@example.com", is_admin=True)
    user = await make_user("labs-revoked@example.com")
    await client.put(f"{FLAGS}/real_time_generation/users/{user.email}", headers=_auth(admin, settings))
    await client.put(f"{LABS}/real_time_generation", json={"enabled": True}, headers=_auth(user, settings))

    await client.delete(f"{FLAGS}/real_time_generation/users/{user.email}", headers=_auth(admin, settings))

    revoked = _by_key(await client.get(LABS, headers=_auth(user, settings)))["real_time_generation"]
    assert (revoked["available"], revoked["enabled"]) == (False, False)
    assert not await feature_flags.is_enabled(await User.get(user.id), "real_time_generation")

    await client.put(f"{FLAGS}/real_time_generation/users/{user.email}", headers=_auth(admin, settings))
    regranted = _by_key(await client.get(LABS, headers=_auth(user, settings)))["real_time_generation"]
    assert regranted["enabled"], "the user's own switch outlives a revoke, so a re-grant turns it back on"


async def test_only_admins_roll_out_and_every_change_is_logged(client, settings) -> None:
    admin = await make_user("labs-admin4@example.com", is_admin=True)
    user = await make_user("labs-user4@example.com")

    refused = await client.put(f"{FLAGS}/ai_arrangement", json={"enabled": True}, headers=_auth(user, settings))
    unknown = await client.put(f"{FLAGS}/ai_arrangement/users/nobody@example.com", headers=_auth(admin, settings))
    no_such_flag = await client.put(f"{FLAGS}/time_travel", json={"enabled": True}, headers=_auth(admin, settings))
    await client.put(f"{FLAGS}/ai_arrangement", json={"enabled": True}, headers=_auth(admin, settings))
    await client.put(f"{FLAGS}/ai_arrangement/users/{user.email}", headers=_auth(admin, settings))

    assert refused.status_code == 403
    assert unknown.status_code == 404
    assert no_such_flag.status_code == 404
    log = await ModerationLogEntry.find(ModerationLogEntry.target_type == "feature_flag").sort("created_at").to_list()
    assert [(e.action, e.target_id) for e in log] == [
        ("feature_flag_everyone", "ai_arrangement"),
        ("feature_flag_granted", "ai_arrangement"),
    ]


async def test_switching_off_and_granting_twice(client, settings) -> None:
    admin = await make_user("labs-admin5@example.com", is_admin=True)
    user = await make_user("labs-twice@example.com")
    for _ in range(2):
        await client.put(f"{FLAGS}/ai_arrangement/users/{user.email}", headers=_auth(admin, settings))
    await client.put(f"{LABS}/ai_arrangement", json={"enabled": True}, headers=_auth(user, settings))

    off = await client.put(f"{LABS}/ai_arrangement", json={"enabled": False}, headers=_auth(user, settings))

    assert (_by_key(off)["ai_arrangement"]["available"], _by_key(off)["ai_arrangement"]["enabled"]) == (True, False)
    [flag] = await feature_flags.FeatureFlagSetting.find({"key": "ai_arrangement"}).to_list()
    assert flag.user_ids == [user.id]


async def test_concurrent_first_writes_to_a_flag_all_succeed(client, settings) -> None:
    # MongoDB retries an upsert that loses the race on the unique `key` index, so none of these is a 500.
    admin = await make_user("labs-admin6@example.com", is_admin=True)

    responses = await asyncio.gather(
        *(
            client.put(f"{FLAGS}/style_transfer", json={"enabled": True}, headers=_auth(admin, settings))
            for _ in range(8)
        )
    )

    assert {r.status_code for r in responses} == {200}
    assert await feature_flags.FeatureFlagSetting.find({"key": "style_transfer"}).count() == 1
