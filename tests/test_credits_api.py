"""Tests for credit deduction (US-9.6).

CI-safe classes (no DB): the 401 auth gate for the credits endpoint and unit
tests for the cost table. ``@pytest.mark.integration`` classes drive the real
app with ``httpx.AsyncClient`` over ``ASGITransport`` against a local MongoDB
(the ``mongo_db`` fixture), mirroring ``tests/test_generation_api.py``. Covers
balance deduction per mode, the 402 insufficient-credits contract, atomicity
under concurrent requests, refund on job-creation failure, and the
``GET /users/me/credits`` balance/history surface.
"""

import asyncio
import logging

import httpx
import pytest
from fastapi.testclient import TestClient

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.models import CreditTransaction, Job, User
from acemusic.api.services import credits as credits_service, users as user_service
from acemusic.api.settings import ApiSettings

GENERATE_URL = f"{API_V1_PREFIX}/generate"
CREDITS_URL = f"{API_V1_PREFIX}/users/me/credits"


class TestAuthGate:
    """Runs in CI (no DB): the route must reject anonymous requests outright."""

    def test_missing_auth_header_returns_401(self) -> None:
        client = TestClient(create_app())
        resp = client.get(CREDITS_URL)
        assert resp.status_code == 401


class TestGetCost:
    """Runs in CI (no DB): the cost table is pure logic."""

    def test_song_costs_one_credit(self) -> None:
        assert credits_service.get_cost("song") == 1.0

    def test_sound_costs_half_credit(self) -> None:
        assert credits_service.get_cost("sound") == 0.5

    def test_unknown_mode_raises(self) -> None:
        with pytest.raises(ValueError):
            credits_service.get_cost("video")


def _async_client(app) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


@pytest.fixture
def settings(mongo_db, mongo_settings) -> ApiSettings:
    # mongo_db initialises Beanie against the isolated DB on this test's loop.
    # Disable the background processor (US-9.2) so queued jobs stay queued.
    return mongo_settings.model_copy(
        update={
            "jwt_secret_key": "test-secret-key-at-least-32-bytes-long-xx",
            "job_processor_enabled": False,
        }
    )


@pytest.fixture
async def client(settings):
    async with _async_client(create_app(settings)) as ac:
        yield ac


def _auth_headers(user, settings: ApiSettings) -> dict[str, str]:
    token = create_access_token(
        user_id=str(user.id),
        email=user.email,
        subscription_tier=user.subscription_tier,
        settings=settings,
    )
    return {"Authorization": f"Bearer {token}"}


async def _make_user(email: str, *, balance: float | None = None):
    user = await user_service.get_or_create_user(
        email=email, provider="google", oauth_id=f"g-{email}", name="Test User"
    )
    if balance is not None:
        user.credits_balance = balance
        await user.save()
    return user


async def _reload(user) -> User:
    return await User.get(user.id)


@pytest.mark.integration
class TestGenerationDeductsCredits:
    async def test_song_deducts_one_credit(self, client, settings):
        user = await _make_user("credits-song@example.com", balance=10.0)
        resp = await client.post(
            GENERATE_URL,
            json={"prompt": "a calm piano ballad"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 202
        assert (await _reload(user)).credits_balance == 9.0

    async def test_sound_deducts_half_credit(self, client, settings):
        user = await _make_user("credits-sound@example.com", balance=10.0)
        resp = await client.post(
            GENERATE_URL,
            json={"prompt": "punchy kick", "mode": "sound", "sound_type": "one-shot"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 202
        assert (await _reload(user)).credits_balance == 9.5

    async def test_deduction_recorded_as_transaction(self, client, settings):
        user = await _make_user("credits-txn@example.com", balance=10.0)
        resp = await client.post(
            GENERATE_URL,
            json={"prompt": "a calm piano ballad"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 202
        job_id = resp.json()["job_id"]
        txns = await CreditTransaction.find(CreditTransaction.user_id == user.id).to_list()
        assert len(txns) == 1
        txn = txns[0]
        assert txn.amount == -1.0
        assert txn.action_type == "song"
        assert txn.job_id == job_id
        assert txn.balance_after == 9.0


@pytest.mark.integration
class TestInsufficientCredits:
    async def test_returns_402_with_balance_payload(self, client, settings):
        user = await _make_user("credits-poor@example.com", balance=0.25)
        resp = await client.post(
            GENERATE_URL,
            json={"prompt": "a calm piano ballad"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 402
        detail = resp.json()["detail"]
        assert detail["error"] == "insufficient_credits"
        assert detail["balance"] == 0.25
        assert detail["required"] == 1.0

    async def test_balance_unchanged_and_no_job_created(self, client, settings):
        user = await _make_user("credits-nojob@example.com", balance=0.25)
        resp = await client.post(
            GENERATE_URL,
            json={"prompt": "a calm piano ballad"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 402
        assert (await _reload(user)).credits_balance == 0.25
        assert await Job.find(Job.user_id == user.id).count() == 0
        assert await CreditTransaction.find(CreditTransaction.user_id == user.id).count() == 0

    async def test_sound_allowed_when_song_is_not(self, client, settings):
        # 0.5 ≤ balance < 1.0: enough for a sound, not for a song.
        user = await _make_user("credits-half@example.com", balance=0.5)
        headers = _auth_headers(user, settings)
        song = await client.post(GENERATE_URL, json={"prompt": "ballad"}, headers=headers)
        assert song.status_code == 402
        sound = await client.post(
            GENERATE_URL,
            json={"prompt": "kick", "mode": "sound", "sound_type": "one-shot"},
            headers=headers,
        )
        assert sound.status_code == 202
        assert (await _reload(user)).credits_balance == 0.0


@pytest.mark.integration
class TestConcurrentDeduction:
    async def test_no_double_deduction_when_budget_covers_one(self, client, settings):
        # Budget for exactly one song: of two concurrent requests, exactly one
        # may win the atomic deduction; the loser gets 402 and no job.
        user = await _make_user("credits-race@example.com", balance=1.0)
        headers = _auth_headers(user, settings)
        body = {"prompt": "a calm piano ballad"}
        first, second = await asyncio.gather(
            client.post(GENERATE_URL, json=body, headers=headers),
            client.post(GENERATE_URL, json=body, headers=headers),
        )
        assert sorted([first.status_code, second.status_code]) == [202, 402]
        assert (await _reload(user)).credits_balance == 0.0
        assert await Job.find(Job.user_id == user.id).count() == 1
        assert await CreditTransaction.find(CreditTransaction.user_id == user.id).count() == 1


@pytest.mark.integration
class TestRefundOnJobCreationFailure:
    async def test_balance_restored_when_queueing_fails(self, client, settings, monkeypatch):
        async def _boom(**_kwargs):
            raise RuntimeError("queue exploded")

        monkeypatch.setattr("acemusic.api.services.generation.create_generation_job", _boom)
        user = await _make_user("credits-refund@example.com", balance=10.0)
        # ASGITransport re-raises unhandled server exceptions into the test
        # (real clients would see a 500); the contract under test is the
        # compensating refund, not the status code.
        with pytest.raises(RuntimeError):
            await client.post(
                GENERATE_URL,
                json={"prompt": "a calm piano ballad"},
                headers=_auth_headers(user, settings),
            )
        assert (await _reload(user)).credits_balance == 10.0
        assert await CreditTransaction.find(CreditTransaction.user_id == user.id).count() == 0

    async def test_no_orphaned_job_when_dispatch_fails_after_insert(self, client, settings, monkeypatch):
        # Failure AFTER the job document is persisted: the job must not be left
        # behind as QUEUED (the US-9.2 processor polls the collection and would
        # run it for free once the refund lands).
        async def _boom(_job_id):
            raise RuntimeError("dispatch exploded")

        monkeypatch.setattr("acemusic.api.services.generation.dispatch_job", _boom)
        user = await _make_user("credits-dispatch@example.com", balance=10.0)
        # ASGITransport re-raises unhandled server exceptions into the test
        # (real clients would see a 500); the contract under test is the
        # cleanup, not the status code.
        with pytest.raises(RuntimeError):
            await client.post(
                GENERATE_URL,
                json={"prompt": "a calm piano ballad"},
                headers=_auth_headers(user, settings),
            )
        assert (await _reload(user)).credits_balance == 10.0
        assert await Job.find(Job.user_id == user.id).count() == 0
        assert await CreditTransaction.find(CreditTransaction.user_id == user.id).count() == 0


@pytest.mark.integration
class TestCreditsEndpoint:
    async def test_returns_balance_and_tier(self, client, settings):
        user = await _make_user("credits-view@example.com", balance=7.5)
        resp = await client.get(CREDITS_URL, headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        body = resp.json()
        assert body["balance"] == 7.5
        assert body["tier"] == "free"
        assert body["history"] == []

    async def test_history_lists_transactions_newest_first(self, client, settings):
        user = await _make_user("credits-history@example.com", balance=10.0)
        headers = _auth_headers(user, settings)
        song = await client.post(GENERATE_URL, json={"prompt": "ballad"}, headers=headers)
        sound = await client.post(
            GENERATE_URL,
            json={"prompt": "kick", "mode": "sound", "sound_type": "one-shot"},
            headers=headers,
        )
        assert song.status_code == 202 and sound.status_code == 202

        resp = await client.get(CREDITS_URL, headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["balance"] == 8.5
        history = body["history"]
        assert len(history) == 2
        # Newest first: the sound came second.
        assert history[0]["action_type"] == "sound"
        assert history[0]["amount"] == -0.5
        assert history[0]["balance_after"] == 8.5
        assert history[0]["job_id"] == sound.json()["job_id"]
        assert history[1]["action_type"] == "song"
        assert history[1]["amount"] == -1.0
        assert history[1]["balance_after"] == 9.0
        assert "created_at" in history[0]

    async def test_history_is_capped_at_50_entries(self, client, settings):
        user = await _make_user("credits-cap@example.com", balance=100.0)
        for i in range(55):
            await credits_service.record_transaction(
                user_id=user.id,
                amount=-1.0,
                action_type="song",
                job_id=f"job-{i}",
                balance_after=float(100 - i - 1),
            )
        resp = await client.get(CREDITS_URL, headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        history = resp.json()["history"]
        assert len(history) == 50
        # Newest first: the last-recorded transaction leads.
        assert history[0]["job_id"] == "job-54"

    async def test_stale_token_for_deleted_user_returns_404(self, client, settings):
        user = await _make_user("credits-deleted@example.com")
        headers = _auth_headers(user, settings)
        await user.delete()
        resp = await client.get(CREDITS_URL, headers=headers)
        assert resp.status_code == 404


@pytest.mark.integration
class TestNewUserDefaultBalance:
    async def test_new_user_starts_with_default_credits(self, client, settings):
        user = await _make_user("credits-fresh@example.com")
        resp = await client.get(CREDITS_URL, headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        assert resp.json()["balance"] == 10.0


@pytest.mark.integration
class TestLegacyUserWithoutBalanceField:
    async def _strip_balance_field(self, user) -> None:
        # Simulate a document created before US-9.6: no credits_balance field
        # exists in MongoDB (Beanie only supplies the default at load time).
        await User.get_pymongo_collection().update_one({"_id": user.id}, {"$unset": {"credits_balance": ""}})

    async def test_generation_succeeds_and_deducts_from_default(self, client, settings):
        user = await _make_user("credits-legacy@example.com")
        await self._strip_balance_field(user)
        resp = await client.post(
            GENERATE_URL,
            json={"prompt": "a calm piano ballad"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 202
        assert (await _reload(user)).credits_balance == 9.0

    async def test_insufficient_path_still_402_after_backfill_spend(self, client, settings):
        user = await _make_user("credits-legacy-poor@example.com")
        await self._strip_balance_field(user)
        headers = _auth_headers(user, settings)
        first = await client.post(GENERATE_URL, json={"prompt": "ballad"}, headers=headers)
        assert first.status_code == 202
        # Force the balance below a song's cost, then verify the normal 402 path.
        user.credits_balance = 0.75
        await user.save()
        second = await client.post(GENERATE_URL, json={"prompt": "ballad"}, headers=headers)
        assert second.status_code == 402
        assert second.json()["detail"]["balance"] == 0.75

    async def test_backfill_race_loser_still_deducts(self, client, settings, monkeypatch):
        # A request can lose the backfill race: its own $exists backfill
        # matches nothing because a concurrent winner already materialised the
        # field. It must then retry the deduction against the now-present
        # balance instead of reporting 402 with 10 credits available. The race
        # is simulated deterministically by materialising the field just
        # before this request's backfill update runs.
        user = await _make_user("credits-legacy-race@example.com")
        await self._strip_balance_field(user)

        collection_cls = type(User.get_pymongo_collection())
        real_update_one = collection_cls.update_one

        async def race_winner_first(coll_self, filt, update, *args, **kwargs):
            is_backfill = isinstance(filt.get("credits_balance"), dict) and "$exists" in filt["credits_balance"]
            if is_backfill:
                await real_update_one(
                    coll_self,
                    {"_id": user.id, "credits_balance": {"$exists": False}},
                    {"$set": {"credits_balance": 10.0}},
                )
            return await real_update_one(coll_self, filt, update, *args, **kwargs)

        monkeypatch.setattr(collection_cls, "update_one", race_winner_first)
        resp = await client.post(
            GENERATE_URL,
            json={"prompt": "a calm piano ballad"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 202
        assert (await _reload(user)).credits_balance == 9.0


@pytest.mark.integration
class TestLedgerWriteFailure:
    async def test_202_still_returned_when_ledger_insert_fails(self, client, settings, monkeypatch, caplog):
        # The charge is taken and the job is queued (and possibly already
        # claimed by the processor) before the ledger insert. A transient
        # ledger failure must not surface as a 500 — the client would retry
        # and be charged twice for work that is already running. The row is
        # best-effort: log loudly, keep the 202 truthful.
        async def _boom(**_kwargs):
            raise RuntimeError("ledger exploded")

        monkeypatch.setattr("acemusic.api.services.credits.record_transaction", _boom)
        # The app pins acemusic logs to its own handler (propagate=False in
        # _ensure_app_logging); caplog listens on the root logger, so re-enable
        # propagation for this test only.
        monkeypatch.setattr(logging.getLogger("acemusic"), "propagate", True)
        user = await _make_user("credits-ledger-fail@example.com", balance=10.0)
        with caplog.at_level(logging.ERROR, logger="acemusic.api.routers.generation"):
            resp = await client.post(
                GENERATE_URL,
                json={"prompt": "a calm piano ballad"},
                headers=_auth_headers(user, settings),
            )
        assert resp.status_code == 202
        assert (await _reload(user)).credits_balance == 9.0
        assert await Job.find(Job.user_id == user.id).count() == 1
        assert await CreditTransaction.find(CreditTransaction.user_id == user.id).count() == 0
        assert any("ledger" in rec.getMessage().lower() for rec in caplog.records if rec.levelno >= logging.ERROR)
