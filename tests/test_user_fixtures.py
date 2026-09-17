"""The shared test-user convention (#423).

Every API test creates its users through ``tests.users.make_user`` or the ``free_user`` /
``pro_user`` fixtures, so the tier a test needs is stated rather than inherited from a
per-file helper. These tests pin the two properties the convention exists for: the default
is **free** (what a real signup gets, so gating regressions cannot hide behind a Pro
default), and nothing bypasses the shared path.
"""

import re
from pathlib import Path

import pytest

from acemusic.api.models import User
from acemusic.api.services.tiers import FREE, PRO
from tests.users import make_user

TESTS_DIR = Path(__file__).parent


def test_api_tests_do_not_create_users_directly() -> None:
    """Any ``tests/test_*_api.py`` reaching for the service is a per-file helper coming back."""
    offenders = sorted(
        p.name for p in TESTS_DIR.glob("test_*_api.py") if re.search(r"\bget_or_create_user\(", p.read_text())
    )
    assert offenders == [], f"create users via tests.users.make_user, not directly: {offenders}"


@pytest.mark.integration
class TestFixtures:
    async def test_free_user_is_free(self, free_user: User) -> None:
        assert free_user.subscription_tier == FREE
        assert (await User.get(free_user.id)).subscription_tier == FREE

    async def test_pro_user_is_pro(self, pro_user: User) -> None:
        assert pro_user.subscription_tier == PRO
        assert (await User.get(pro_user.id)).subscription_tier == PRO

    async def test_fixtures_are_distinct_accounts(self, free_user: User, pro_user: User) -> None:
        assert free_user.id != pro_user.id


@pytest.mark.integration
class TestMakeUser:
    async def test_default_tier_is_free(self, mongo_db) -> None:
        user = await make_user("default@example.com")
        assert user.subscription_tier == FREE

    async def test_tier_and_fields_are_persisted(self, mongo_db) -> None:
        user = await make_user("pro@example.com", tier=PRO, credits_balance=7.5, purchased_credits=2.0)
        stored = await User.get(user.id)
        assert stored.subscription_tier == PRO
        assert stored.credits_balance == 7.5
        assert stored.purchased_credits == 2.0

    async def test_none_leaves_the_model_default(self, mongo_db) -> None:
        """Callers pass through optional kwargs like ``balance=None``; that must not null the field."""
        user = await make_user("none@example.com", credits_balance=None)
        assert (await User.get(user.id)).credits_balance == User.model_fields["credits_balance"].default

    async def test_unknown_field_is_rejected(self, mongo_db) -> None:
        with pytest.raises(AttributeError):
            await make_user("typo@example.com", subscription_teir=PRO)
