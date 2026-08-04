"""US-26.1: what each action costs, and what happens when the balance cannot cover it.

Stems, MIDI and remaster shipped **free** — both routers documented them as
"non-generative local CPU work, so no credits are deducted". This story prices them,
so these tests pin the new behaviour *and* the boundaries that keep it fair: a cached
result costs nothing, and a rejected request costs nothing.
"""

import httpx
import pytest
from beanie import PydanticObjectId

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.models import Clip, CreditTransaction, Job, User
from acemusic.api.services import credits as credits_service, users as user_service
from acemusic.api.settings import ApiSettings

pytestmark = pytest.mark.integration

BALANCE_URL = f"{API_V1_PREFIX}/credits/balance"


@pytest.fixture
def settings(mongo_db, mongo_settings) -> ApiSettings:
    return mongo_settings.model_copy(
        update={
            "jwt_secret_key": "test-secret-key-at-least-32-bytes-long-xx",
            "job_processor_enabled": False,
        }
    )


@pytest.fixture
async def client(settings):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings)), base_url="http://testserver"
    ) as ac:
        yield ac


def _auth(user: User, settings: ApiSettings) -> dict[str, str]:
    token = create_access_token(
        user_id=str(user.id),
        email=user.email,
        subscription_tier=user.subscription_tier,
        settings=settings,
    )
    return {"Authorization": f"Bearer {token}"}


async def _user(email: str, credits: float = 100.0) -> User:
    user = await user_service.get_or_create_user(email=email, provider="google", oauth_id=f"g-{email}", name="T")
    user.credits_balance = credits
    await user.save()
    return user


async def _wav_clip(user: User) -> Clip:
    workspace_id = PydanticObjectId()
    clip = Clip(
        user_id=user.id,
        workspace_id=workspace_id,
        file_path=f"{user.id}/{workspace_id}/clips/source.wav",
        format="wav",
        duration=30.0,
    )
    await clip.insert()
    return clip


async def _balance(user: User) -> float:
    return (await User.get(user.id)).credits_balance


class TestNewlyPricedActions:
    """These three used to be free. Changing that is the point of the story."""

    @pytest.mark.parametrize(
        "op,body,cost",
        [
            ("stems", None, 1.0),
            ("midi", None, 1.0),
            ("remaster", {"target_lufs": -14.0}, 0.5),
        ],
    )
    async def test_the_documented_cost_is_deducted(self, client, settings, op, body, cost) -> None:
        user = await _user(f"{op}-cost@example.com", credits=10.0)
        clip = await _wav_clip(user)

        resp = await client.post(
            f"{API_V1_PREFIX}/clips/{clip.id}/{op}",
            json=body,
            headers=_auth(user, settings),
        )

        assert resp.status_code == 202, resp.text
        assert await _balance(user) == 10.0 - cost

    @pytest.mark.parametrize(
        "op,body,action_type",
        [
            ("stems", None, "stems"),
            ("midi", None, "midi"),
            ("remaster", {"target_lufs": -14.0}, "remaster"),
        ],
    )
    async def test_the_charge_lands_in_the_history(self, client, settings, op, body, action_type) -> None:
        # A balance that drops with no row to explain it is the complaint this avoids.
        user = await _user(f"{op}-ledger@example.com", credits=10.0)
        clip = await _wav_clip(user)

        resp = await client.post(
            f"{API_V1_PREFIX}/clips/{clip.id}/{op}",
            json=body,
            headers=_auth(user, settings),
        )
        job_id = resp.json()["job_id"]

        rows = await CreditTransaction.find(CreditTransaction.job_id == job_id).to_list()
        assert [r.action_type for r in rows] == [action_type]
        assert rows[0].amount < 0

    @pytest.mark.parametrize(
        "op,body",
        [("stems", None), ("midi", None), ("remaster", {"target_lufs": -14.0})],
    )
    async def test_an_empty_balance_is_refused_and_charges_nothing(self, client, settings, op, body) -> None:
        user = await _user(f"{op}-broke@example.com", credits=0.0)
        clip = await _wav_clip(user)

        resp = await client.post(
            f"{API_V1_PREFIX}/clips/{clip.id}/{op}",
            json=body,
            headers=_auth(user, settings),
        )

        assert resp.status_code == 402, resp.text
        assert await _balance(user) == 0.0
        assert await Job.find(Job.user_id == user.id).count() == 0, "a job was queued without payment"

    @pytest.mark.parametrize("op", ["stems", "midi"])
    async def test_a_rejected_request_costs_nothing(self, client, settings, op) -> None:
        # Non-wav is rejected before the charge, so a request that could never run
        # is free — the ordering that makes pricing these fair.
        user = await _user(f"{op}-mp3@example.com", credits=10.0)
        workspace_id = PydanticObjectId()
        clip = Clip(
            user_id=user.id,
            workspace_id=workspace_id,
            file_path=f"{user.id}/{workspace_id}/clips/source.mp3",
            format="mp3",
            duration=30.0,
        )
        await clip.insert()

        resp = await client.post(f"{API_V1_PREFIX}/clips/{clip.id}/{op}", headers=_auth(user, settings))

        assert resp.status_code == 422, resp.text
        assert await _balance(user) == 10.0

    async def test_cached_stems_are_free(self, client, settings) -> None:
        # The credit buys the separation, not the lookup. Without this, polling the
        # endpoint would bill on every call.
        from acemusic.stems_client import STEM_LABELS

        user = await _user("stems-cached@example.com", credits=10.0)
        clip = await _wav_clip(user)
        for label in STEM_LABELS:
            stem = Clip(
                user_id=user.id,
                workspace_id=clip.workspace_id,
                file_path=f"{user.id}/{clip.workspace_id}/clips/{label}.wav",
                format="wav",
                title=label,
                parent_clip_ids=[clip.id],
                generation_mode="stems",
            )
            await stem.insert()

        resp = await client.post(f"{API_V1_PREFIX}/clips/{clip.id}/stems", headers=_auth(user, settings))

        assert resp.status_code == 200, resp.text
        assert await _balance(user) == 10.0

    async def test_cached_midi_is_free(self, client, settings) -> None:
        user = await _user("midi-cached@example.com", credits=10.0)
        clip = await _wav_clip(user)
        clip.midi_paths = {"melody": f"{user.id}/midi/melody.mid"}
        await clip.save()

        resp = await client.post(f"{API_V1_PREFIX}/clips/{clip.id}/midi", headers=_auth(user, settings))

        assert resp.status_code == 200, resp.text
        assert await _balance(user) == 10.0


class TestStillFreeActions:
    """Crop and speed were free before this story and stay free."""

    @pytest.mark.parametrize(
        "op,body",
        [
            ("crop", {"start": "0s", "end": "10s"}),
            ("speed", {"multiplier": 1.5}),
        ],
    )
    async def test_local_edits_remain_free(self, client, settings, op, body) -> None:
        user = await _user(f"{op}-free@example.com", credits=10.0)
        clip = await _wav_clip(user)

        resp = await client.post(
            f"{API_V1_PREFIX}/clips/{clip.id}/{op}",
            json=body,
            headers=_auth(user, settings),
        )

        assert resp.status_code == 202, resp.text
        assert await _balance(user) == 10.0

    async def test_a_free_edit_writes_no_ledger_row(self, client, settings) -> None:
        user = await _user("crop-noledger@example.com", credits=10.0)
        clip = await _wav_clip(user)

        resp = await client.post(
            f"{API_V1_PREFIX}/clips/{clip.id}/crop",
            json={"start": "0s", "end": "10s"},
            headers=_auth(user, settings),
        )

        rows = await CreditTransaction.find(CreditTransaction.job_id == resp.json()["job_id"]).to_list()
        assert rows == []


class TestInsufficientCreditsResponse:
    async def test_the_402_says_what_is_needed_and_where_to_go(self, client, settings) -> None:
        user = await _user("402-shape@example.com", credits=0.0)
        clip = await _wav_clip(user)

        resp = await client.post(f"{API_V1_PREFIX}/clips/{clip.id}/stems", headers=_auth(user, settings))

        assert resp.status_code == 402
        detail = resp.json()["detail"]
        assert detail["error"] == "insufficient_credits"
        assert detail["required"] == 1.0
        assert detail["balance"] == 0.0
        # An error that only says "no" leaves the musician stuck.
        assert detail["upgrade_url"] == credits_service.UPGRADE_URL
        assert "credits" in detail["message"]


class TestBalanceEndpoint:
    async def test_it_returns_the_current_balance(self, client, settings) -> None:
        user = await _user("balance@example.com", credits=42.5)

        resp = await client.get(BALANCE_URL, headers=_auth(user, settings))

        assert resp.status_code == 200, resp.text
        assert resp.json()["balance"] == 42.5
        assert resp.json()["upgrade_url"] == credits_service.UPGRADE_URL

    async def test_it_reflects_a_deduction_made_after_the_token_was_issued(self, client, settings) -> None:
        # The sidebar shows this on every page, so a stale claim-derived figure would
        # tell the musician they still have credits they have already spent.
        user = await _user("balance-fresh@example.com", credits=10.0)
        headers = _auth(user, settings)
        clip = await _wav_clip(user)

        await client.post(f"{API_V1_PREFIX}/clips/{clip.id}/stems", headers=headers)
        resp = await client.get(BALANCE_URL, headers=headers)

        assert resp.json()["balance"] == 9.0

    async def test_it_needs_a_token(self, client) -> None:
        assert (await client.get(BALANCE_URL)).status_code == 401
