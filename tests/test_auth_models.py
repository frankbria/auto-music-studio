"""Integration tests for the auth data models (US-8.3).

Run against a real local MongoDB via the ``mongo_db`` fixture (no mocking).
Marked ``integration`` so the default unit run deselects them.
"""

from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.integration


class TestUserOAuthIndex:
    async def test_subscription_tier_defaults_to_free(self, mongo_db):
        from acemusic.api.models import User

        user = await User(email="tier@example.com", name="Tier").insert()
        assert user.subscription_tier == "free"

    async def test_duplicate_oauth_identity_rejected(self, mongo_db):
        """Two users sharing the same (oauth_provider, oauth_id) collide."""
        from pymongo.errors import DuplicateKeyError

        from acemusic.api.models import User

        await User(email="g1@example.com", name="G One", oauth_provider="google", oauth_id="123").insert()
        with pytest.raises(DuplicateKeyError):
            await User(email="g2@example.com", name="G Two", oauth_provider="google", oauth_id="123").insert()

    async def test_null_oauth_fields_do_not_collide(self, mongo_db):
        """The partial index lets multiple users keep null oauth fields."""
        from acemusic.api.models import User

        a = await User(email="null1@example.com", name="Null One").insert()
        b = await User(email="null2@example.com", name="Null Two").insert()
        assert a.id != b.id
        assert a.oauth_provider is None and b.oauth_provider is None


class TestRefreshTokenModel:
    async def test_crud_roundtrip(self, mongo_db):
        from beanie import PydanticObjectId

        from acemusic.api.models import RefreshToken

        user_id = PydanticObjectId()
        expires = datetime.now(timezone.utc) + timedelta(days=7)
        token = await RefreshToken(
            token_hash="abc123hash",
            user_id=user_id,
            expires_at=expires,
        ).insert()
        assert token.id is not None
        assert token.revoked is False
        assert token.created_at is not None

        found = await RefreshToken.find_one(RefreshToken.token_hash == "abc123hash")
        assert found is not None and found.user_id == user_id

        found.revoked = True
        await found.save()
        assert (await RefreshToken.get(found.id)).revoked is True

        await found.delete()
        assert await RefreshToken.find_one(RefreshToken.token_hash == "abc123hash") is None

    async def test_token_hash_unique(self, mongo_db):
        from beanie import PydanticObjectId
        from pymongo.errors import DuplicateKeyError

        from acemusic.api.models import RefreshToken

        await RefreshToken(
            token_hash="dup-hash",
            user_id=PydanticObjectId(),
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        ).insert()
        with pytest.raises(DuplicateKeyError):
            await RefreshToken(
                token_hash="dup-hash",
                user_id=PydanticObjectId(),
                expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            ).insert()

    async def test_ttl_index_present(self, mongo_db):
        """A TTL index on expires_at (expireAfterSeconds=0) is created."""
        from acemusic.api.models import RefreshToken

        info = await RefreshToken.get_pymongo_collection().index_information()
        ttl = [meta for meta in info.values() if meta.get("key", [(None, None)])[0][0] == "expires_at"]
        assert ttl, "expected an index on expires_at"
        assert any(meta.get("expireAfterSeconds") == 0 for meta in ttl)
