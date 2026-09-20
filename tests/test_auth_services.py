"""Integration tests for the refresh-token service layer (US-8.3).

Run against a real local MongoDB via the ``mongo_db`` fixture (no mocking).
"""

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from beanie import PydanticObjectId

from acemusic.api.auth.services import (
    list_plugin_tokens,
    revoke_all_user_tokens,
    revoke_plugin_token,
    revoke_refresh_token,
    rotate_refresh_token,
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


class TestRotate:
    """Rotation swaps the stored hash **in place** so the document survives.

    A plugin token is listed and revoked by its document id (#515), so rotation
    must not replace the document — a consume-then-insert would hand the same
    credential a new id on every refresh.
    """

    async def test_rotate_keeps_the_document_and_swaps_the_hash(self, mongo_db):
        user_id = PydanticObjectId()
        old, new = create_refresh_token(), create_refresh_token()
        stored = await store_refresh_token(user_id, old, _future(1))
        # Read back before rotating: MongoDB returns naive, millisecond-truncated
        # datetimes, so the only sound comparison is stored-value to stored-value.
        before = await RefreshToken.get(stored.id)

        assert await rotate_refresh_token(old, new, _future(7)) == user_id

        after = await RefreshToken.get(stored.id)
        assert after is not None, "rotation must reuse the document, not replace it"
        assert after.token_hash == hashlib.sha256(new.encode()).hexdigest()
        assert after.created_at == before.created_at
        assert after.expires_at > before.expires_at
        assert await validate_refresh_token(new) == user_id
        assert await validate_refresh_token(old) is None

    async def test_rotate_carries_the_kind_across(self, mongo_db):
        user_id = PydanticObjectId()
        old, new = create_refresh_token(), create_refresh_token()
        stored = await store_refresh_token(user_id, old, _future(), kind="plugin")
        await rotate_refresh_token(old, new, _future())
        assert (await RefreshToken.get(stored.id)).kind == "plugin"

    async def test_rotate_is_single_use(self, mongo_db):
        user_id = PydanticObjectId()
        old, new = create_refresh_token(), create_refresh_token()
        await store_refresh_token(user_id, old, _future())
        assert await rotate_refresh_token(old, new, _future()) == user_id
        assert await rotate_refresh_token(old, create_refresh_token(), _future()) is None

    async def test_rotate_is_single_use_under_concurrency(self, mongo_db):
        """Exactly one of N concurrent rotations of the same token may win.

        Dispatching with ``asyncio.gather`` (rather than awaiting serially)
        exercises the atomicity contract: the ``find_one_and_update`` filtered on
        the *old* hash can match at most once, so a duplicated or racing refresh
        cannot mint two live credentials from one single-use token.
        """
        user_id = PydanticObjectId()
        old = create_refresh_token()
        stored = await store_refresh_token(user_id, old, _future())
        news = [create_refresh_token() for _ in range(5)]

        results = await asyncio.gather(*(rotate_refresh_token(old, new, _future()) for new in news))

        assert results.count(user_id) == 1
        assert results.count(None) == 4
        # Exactly one of the new tokens is live, and it is on the original document.
        live = [new for new in news if await validate_refresh_token(new) == user_id]
        assert len(live) == 1
        assert (await RefreshToken.get(stored.id)).token_hash == hashlib.sha256(live[0].encode()).hexdigest()

    async def test_rotate_unknown_returns_none(self, mongo_db):
        assert await rotate_refresh_token("never-stored", create_refresh_token(), _future()) is None

    async def test_rotate_revoked_returns_none(self, mongo_db):
        user_id = PydanticObjectId()
        old = create_refresh_token()
        await store_refresh_token(user_id, old, _future())
        await revoke_refresh_token(old)
        assert await rotate_refresh_token(old, create_refresh_token(), _future()) is None

    async def test_rotate_expired_leaves_the_document_alone(self, mongo_db):
        """An expired token is not rotated, and its hash is not overwritten.

        Overwriting it would leave a document keyed to a token the caller is
        about to throw away, live until the TTL index reaps it.
        """
        user_id = PydanticObjectId()
        old, new = create_refresh_token(), create_refresh_token()
        stored = await store_refresh_token(user_id, old, _past())

        assert await rotate_refresh_token(old, new, _future()) is None

        after = await RefreshToken.get(stored.id)
        assert after.token_hash == stored.token_hash
        assert await validate_refresh_token(new) is None


class TestPluginTokens:
    """Listing and revoking plugin tokens by document id (#515)."""

    async def test_lists_only_live_plugin_tokens_newest_first(self, mongo_db):
        user_id = PydanticObjectId()
        web = await store_refresh_token(user_id, create_refresh_token(), _future())
        older = await store_refresh_token(user_id, create_refresh_token(), _future(6), kind="plugin")
        newer = await store_refresh_token(user_id, create_refresh_token(), _future(7), kind="plugin")
        revoked_raw = create_refresh_token()
        revoked = await store_refresh_token(user_id, revoked_raw, _future(), kind="plugin")
        await revoke_refresh_token(revoked_raw)
        expired = await store_refresh_token(user_id, create_refresh_token(), _past(), kind="plugin")
        other = await store_refresh_token(PydanticObjectId(), create_refresh_token(), _future(), kind="plugin")

        listed = await list_plugin_tokens(user_id)

        ids = [token.id for token in listed]
        assert ids == [newer.id, older.id], "newest first, live plugin tokens only"
        for excluded in (web, revoked, expired, other):
            assert excluded.id not in ids

    async def test_revoke_plugin_token_kills_the_credential(self, mongo_db):
        user_id = PydanticObjectId()
        raw = create_refresh_token()
        stored = await store_refresh_token(user_id, raw, _future(), kind="plugin")

        assert await revoke_plugin_token(user_id, stored.id) is True
        assert await validate_refresh_token(raw) is None
        assert await list_plugin_tokens(user_id) == []
        # Idempotent: revoking it again still reports the token as this user's.
        assert await revoke_plugin_token(user_id, stored.id) is True

    async def test_revoke_plugin_token_refuses_another_users_token(self, mongo_db):
        owner = PydanticObjectId()
        raw = create_refresh_token()
        stored = await store_refresh_token(owner, raw, _future(), kind="plugin")

        assert await revoke_plugin_token(PydanticObjectId(), stored.id) is False
        assert await validate_refresh_token(raw) == owner

    async def test_revoke_plugin_token_refuses_a_web_session(self, mongo_db):
        user_id = PydanticObjectId()
        raw = create_refresh_token()
        stored = await store_refresh_token(user_id, raw, _future())

        assert await revoke_plugin_token(user_id, stored.id) is False
        assert await validate_refresh_token(raw) == user_id

    async def test_revoke_plugin_token_unknown_id_returns_false(self, mongo_db):
        assert await revoke_plugin_token(PydanticObjectId(), PydanticObjectId()) is False


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
