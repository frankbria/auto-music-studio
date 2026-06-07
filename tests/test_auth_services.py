"""Integration tests for the refresh-token service layer (US-8.3).

Run against a real local MongoDB via the ``mongo_db`` fixture (no mocking).
"""

import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from beanie import PydanticObjectId

from acemusic.api.auth.services import (
    consume_refresh_token,
    revoke_all_user_tokens,
    revoke_refresh_token,
    store_refresh_token,
    validate_refresh_token,
)
from acemusic.api.auth.tokens import create_refresh_token
from acemusic.api.models import RefreshToken

pytestmark = pytest.mark.integration


def _future(days: int = 7) -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=days)


def _past(days: int = 1) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


class TestStoreAndValidate:
    async def test_store_then_validate_returns_user_id(self, mongo_db):
        user_id = PydanticObjectId()
        raw = create_refresh_token()
        await store_refresh_token(user_id, raw, _future())
        assert await validate_refresh_token(raw) == user_id

    async def test_raw_token_is_never_stored(self, mongo_db):
        user_id = PydanticObjectId()
        raw = create_refresh_token()
        stored = await store_refresh_token(user_id, raw, _future())
        assert stored.token_hash != raw
        assert stored.token_hash == hashlib.sha256(raw.encode()).hexdigest()
        # And nothing in the collection holds the raw value.
        assert await RefreshToken.find_one(RefreshToken.token_hash == raw) is None

    async def test_unknown_token_returns_none(self, mongo_db):
        assert await validate_refresh_token("never-stored") is None

    async def test_expired_token_returns_none(self, mongo_db):
        """Defense in depth: a not-yet-reaped expired token still fails validation."""
        user_id = PydanticObjectId()
        raw = create_refresh_token()
        await store_refresh_token(user_id, raw, _past())
        assert await validate_refresh_token(raw) is None

    async def test_revoked_token_returns_none(self, mongo_db):
        user_id = PydanticObjectId()
        raw = create_refresh_token()
        await store_refresh_token(user_id, raw, _future())
        assert await revoke_refresh_token(raw) is True
        assert await validate_refresh_token(raw) is None


class TestConsume:
    async def test_consume_returns_user_id_then_revokes(self, mongo_db):
        user_id = PydanticObjectId()
        raw = create_refresh_token()
        await store_refresh_token(user_id, raw, _future())
        assert await consume_refresh_token(raw) == user_id
        # The token is now revoked — a second consume yields nothing.
        assert await consume_refresh_token(raw) is None
        assert await validate_refresh_token(raw) is None

    async def test_consume_is_single_use_under_repeat(self, mongo_db):
        """Single-use rotation: only the first consume of a token wins."""
        user_id = PydanticObjectId()
        raw = create_refresh_token()
        await store_refresh_token(user_id, raw, _future())
        results = [await consume_refresh_token(raw) for _ in range(5)]
        assert results.count(user_id) == 1
        assert results.count(None) == 4

    async def test_consume_unknown_returns_none(self, mongo_db):
        assert await consume_refresh_token("never-stored") is None

    async def test_consume_expired_returns_none(self, mongo_db):
        user_id = PydanticObjectId()
        raw = create_refresh_token()
        await store_refresh_token(user_id, raw, _past())
        assert await consume_refresh_token(raw) is None


class TestRevoke:
    async def test_revoke_unknown_returns_false(self, mongo_db):
        assert await revoke_refresh_token("never-stored") is False

    async def test_revoke_all_user_tokens(self, mongo_db):
        user_id = PydanticObjectId()
        other_id = PydanticObjectId()
        raws = [create_refresh_token() for _ in range(3)]
        for raw in raws:
            await store_refresh_token(user_id, raw, _future())
        other_raw = create_refresh_token()
        await store_refresh_token(other_id, other_raw, _future())

        count = await revoke_all_user_tokens(user_id)
        assert count == 3
        for raw in raws:
            assert await validate_refresh_token(raw) is None
        # Another user's token is untouched.
        assert await validate_refresh_token(other_raw) == other_id
