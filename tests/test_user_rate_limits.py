"""Per-user, per-kind request limits, tiered by plan (US-28.4, #341)."""

import pytest
from beanie import PydanticObjectId
from fastapi import HTTPException
from fastapi.testclient import TestClient

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.models import Clip, Job, User, Workspace
from acemusic.api.services import credits, mastering
from acemusic.api.services.tiers import ENTERPRISE, FREE, PRO
from acemusic.api.settings import ApiSettings
from acemusic.api.utils import user_rate_limit
from acemusic.api.utils.user_rate_limit import UserRateLimits
from tests.users import make_user

SECRET = "test-secret-key-at-least-32-bytes-long-xx"
NOWHERE = f"{API_V1_PREFIX}/no-such-route"


def _settings(**limits: int) -> ApiSettings:
    return ApiSettings(_env_file=None, jwt_secret_key=SECRET, job_processor_enabled=False, **limits)


def _auth(user_id: str, tier: str, settings: ApiSettings) -> dict[str, str]:
    token = create_access_token(user_id=user_id, email="u@example.com", subscription_tier=tier, settings=settings)
    return {"Authorization": f"Bearer {token}"}


def _client(settings: ApiSettings) -> TestClient:
    app = create_app(settings)

    async def start_creation() -> dict:
        user_rate_limit.check_generation()
        return {}

    app.add_api_route("/test/create", start_creation, methods=["POST"])
    return TestClient(app)


def _statuses(client: TestClient, n: int, headers: dict, method: str = "GET", url: str = NOWHERE) -> list[int]:
    return [client.request(method, url, headers=headers).status_code for _ in range(n)]


def test_over_the_read_limit_is_a_coded_429_with_retry_after() -> None:
    settings = _settings(rate_limit_reads_per_minute=3)
    client = _client(settings)
    headers = _auth("u1", FREE, settings)

    assert _statuses(client, 3, headers) == [404, 404, 404]
    resp = client.get(NOWHERE, headers=headers)

    assert resp.status_code == 429
    assert resp.json()["code"] == "rate_limited"
    assert 1 <= int(resp.headers["retry-after"]) <= 60


@pytest.mark.parametrize(("tier", "allowed"), [(FREE, 2), (PRO, 6), (ENTERPRISE, 20)])
def test_paid_plans_get_more(tier: str, allowed: int) -> None:
    settings = _settings(rate_limit_reads_per_minute=2)
    client = _client(settings)
    headers = _auth("u1", tier, settings)

    statuses = _statuses(client, allowed + 1, headers)

    assert statuses[:allowed] == [404] * allowed
    assert statuses[allowed] == 429


def test_reads_writes_and_users_are_counted_apart() -> None:
    settings = _settings(rate_limit_reads_per_minute=1, rate_limit_writes_per_minute=1)
    client = _client(settings)
    first, second = _auth("u1", FREE, settings), _auth("u2", FREE, settings)

    assert _statuses(client, 1, first) == [404]
    assert _statuses(client, 1, first, "POST") == [404]
    assert _statuses(client, 1, second) == [404]
    assert _statuses(client, 1, first) == [429]
    assert _statuses(client, 1, first, "POST") == [429]


def test_an_expired_token_is_not_counted() -> None:
    settings = _settings(rate_limit_reads_per_minute=1)
    client = _client(settings)
    expired = settings.model_copy(update={"access_token_expire_minutes": -1})
    headers = _auth("u1", FREE, expired)

    assert _statuses(client, 3, headers) == [404, 404, 404]


def test_requests_without_a_valid_token_are_left_to_the_route() -> None:
    settings = _settings(rate_limit_reads_per_minute=1)
    client = _client(settings)

    assert _statuses(client, 3, {}) == [404, 404, 404]
    assert _statuses(client, 3, {"Authorization": "Bearer not-a-token"}) == [404, 404, 404]


def test_starting_creations_has_its_own_limit() -> None:
    settings = _settings(rate_limit_generations_per_minute=2)
    client = _client(settings)
    headers = _auth("u1", FREE, settings)

    statuses = _statuses(client, 3, headers, "POST", "/test/create")

    assert statuses == [200, 200, 429]


def test_the_limits_scale_by_plan() -> None:
    limits = UserRateLimits(_settings(rate_limit_generations_per_minute=10))

    assert limits.limits["generation"] == {FREE: 10, PRO: 30, ENTERPRISE: 100}


@pytest.mark.integration
class TestGenerationIsLimitedBeforeCharging:
    @pytest.fixture
    def settings(self, mongo_db, mongo_settings) -> ApiSettings:
        return mongo_settings.model_copy(
            update={"jwt_secret_key": SECRET, "job_processor_enabled": False, "rate_limit_generations_per_minute": 1}
        )

    async def test_a_creation_over_the_limit_charges_nothing(self, settings) -> None:
        user = await make_user("limited@example.com", credits_balance=10.0)
        limits = UserRateLimits(settings)
        created = 0

        async def create() -> Job:
            nonlocal created
            created += 1
            return await Job(
                user_id=user.id, workspace_id=PydanticObjectId(), job_type="generate", input_params={}
            ).insert()

        token = user_rate_limit._current.set((limits, str(user.id), FREE))
        try:
            await credits.charge_and_create(user_id=user.id, cost=1, action_type="song", create=create)
            with pytest.raises(HTTPException) as refused:
                await credits.charge_and_create(user_id=user.id, cost=1, action_type="song", create=create)
        finally:
            user_rate_limit._current.reset(token)

        assert refused.value.status_code == 429
        assert created == 1
        assert (await User.get(user.id)).credits_balance == 9.0

    async def test_a_free_action_is_not_a_billed_creation(self, settings) -> None:
        user = await make_user("free-edits@example.com", credits_balance=10.0)
        limits = UserRateLimits(settings)

        async def create() -> Job:
            return await Job(
                user_id=user.id, workspace_id=PydanticObjectId(), job_type="crop", input_params={}
            ).insert()

        token = user_rate_limit._current.set((limits, str(user.id), FREE))
        try:
            for _ in range(3):
                await credits.charge_and_create(user_id=user.id, cost=0, action_type="crop", create=create)
            await credits.charge_and_create(user_id=user.id, cost=1, action_type="song", create=create)
        finally:
            user_rate_limit._current.reset(token)

        assert await Job.count() == 4

    async def _batch_user(self, email: str, clips: int):
        user = await make_user(email, tier=PRO, credits_balance=1_000.0)
        workspace = await Workspace(name="WS", user_id=user.id).insert()
        owned = [
            await Clip(
                user_id=user.id, workspace_id=workspace.id, file_path=f"c{i}.wav", format="wav", title="Song"
            ).insert()
            for i in range(clips)
        ]
        return user, [str(clip.id) for clip in owned]

    @staticmethod
    async def _master(user, clip_ids: list[str]):
        return await mastering.create_mastering_batch(
            user_id=str(user.id),
            clip_ids=clip_ids,
            profile="balanced",
            service="bakuage",
            format="wav",
            target_lufs=-14.0,
        )

    async def test_a_refused_batch_charges_nothing_and_spends_none_of_the_allowance(self, settings) -> None:
        user, clip_ids = await self._batch_user("batch-refused@example.com", 4)
        limits = UserRateLimits(settings)  # one generation a minute on Free, three on Pro

        token = user_rate_limit._current.set((limits, str(user.id), PRO))
        try:
            limits.check("generation", str(user.id), PRO)  # one of three spent
            with pytest.raises(HTTPException) as refused:
                await self._master(user, clip_ids)
            limits.check("generation", str(user.id), PRO)
            limits.check("generation", str(user.id), PRO)  # both remaining slots are still there
        finally:
            user_rate_limit._current.reset(token)

        assert refused.value.status_code == 429
        assert (await User.get(user.id)).credits_balance == 1_000.0
        assert await Job.count() == 0

    async def test_a_batch_larger_than_the_limit_takes_the_whole_minute_rather_than_never_running(
        self, settings
    ) -> None:
        user, clip_ids = await self._batch_user("batch-large@example.com", 4)
        limits = UserRateLimits(settings)

        token = user_rate_limit._current.set((limits, str(user.id), PRO))
        try:
            batch = await self._master(user, clip_ids)
            with pytest.raises(HTTPException):
                limits.check("generation", str(user.id), PRO)
        finally:
            user_rate_limit._current.reset(token)

        assert len(batch.entries) == 4

    async def test_admins_see_the_limits_and_who_was_turned_away(self, settings) -> None:
        admin = await make_user("limits-admin@example.com", is_admin=True)
        client = TestClient(create_app(settings.model_copy(update={"rate_limit_reads_per_minute": 2})))
        noisy = _auth(str(PydanticObjectId()), FREE, settings)
        _statuses(client, 3, noisy)

        with client:
            body = client.get(f"{API_V1_PREFIX}/admin/rate-limits", headers=_auth(str(admin.id), FREE, settings)).json()

        assert body["limits"]["read"] == {FREE: 2, PRO: 6, ENTERPRISE: 20}
        assert [(r["kind"], r["tier"]) for r in body["recent_rejections"]] == [("read", FREE)]
