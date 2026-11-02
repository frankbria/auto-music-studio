"""Per-user, per-kind request limits, tiered by plan (US-28.4, #341)."""

import pytest
from beanie import PydanticObjectId
from fastapi.testclient import TestClient

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.models import Job, User
from acemusic.api.services import credits
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
            with pytest.raises(Exception) as refused:
                await credits.charge_and_create(user_id=user.id, cost=1, action_type="song", create=create)
        finally:
            user_rate_limit._current.reset(token)

        assert refused.value.status_code == 429
        assert created == 1
        assert (await User.get(user.id)).credits_balance == 9.0

    async def test_admins_see_the_limits_and_who_was_turned_away(self, settings) -> None:
        admin = await make_user("limits-admin@example.com", is_admin=True)
        client = TestClient(create_app(settings.model_copy(update={"rate_limit_reads_per_minute": 2})))
        noisy = _auth(str(PydanticObjectId()), FREE, settings)
        _statuses(client, 3, noisy)

        with client:
            body = client.get(f"{API_V1_PREFIX}/admin/rate-limits", headers=_auth(str(admin.id), FREE, settings)).json()

        assert body["limits"]["read"] == {FREE: 2, PRO: 6, ENTERPRISE: 20}
        assert [(r["kind"], r["tier"]) for r in body["recent_rejections"]] == [("read", FREE)]
