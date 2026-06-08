"""Tests for the user profile service layer (US-8.4).

Handle-validation tests are pure (no DB). Service-function tests run against a
real local MongoDB via the ``mongo_db`` fixture (same pattern as the auth
service/route tests) — no mocking of the database.
"""

import pytest

from acemusic.api.exceptions import EmailAlreadyRegisteredError, HandleConflictError
from acemusic.api.services import users as user_service
from acemusic.api.services.users import HandleValidationError, validate_handle


class TestHandleValidation:
    @pytest.mark.parametrize("handle", ["abc", "a-b-c", "User123", "x" * 30, "a1-b2-c3"])
    def test_accepts_valid_handles(self, handle):
        assert validate_handle(handle) == handle

    def test_rejects_too_short(self):
        with pytest.raises(HandleValidationError) as exc:
            validate_handle("ab")
        assert "at least" in str(exc.value).lower()

    def test_rejects_too_long(self):
        with pytest.raises(HandleValidationError) as exc:
            validate_handle("x" * 31)
        assert "at most" in str(exc.value).lower()

    @pytest.mark.parametrize(
        "handle",
        ["bad handle", "no_underscores", "emoji😀", "dot.dot", "slash/x", "-lead", "trail-", "---"],
    )
    def test_rejects_invalid_characters(self, handle):
        with pytest.raises(HandleValidationError) as exc:
            validate_handle(handle)
        msg = str(exc.value).lower()
        assert "letters" in msg or "hyphen" in msg


@pytest.mark.integration
class TestGetOrCreateUser:
    async def test_creates_new_user_with_oauth_defaults(self, mongo_db):
        from acemusic.api.models import User

        user = await user_service.get_or_create_user(
            email="newbie@example.com", provider="google", oauth_id="g-new", name="Newbie"
        )
        assert user.email == "newbie@example.com"
        assert user.name == "Newbie"
        # Display name defaults to the OAuth-provided name on first login.
        assert user.display_name == "Newbie"
        assert user.oauth_provider == "google"
        # Persisted, not just constructed.
        assert await User.get(user.id) is not None

    async def test_returns_existing_user_for_known_identity(self, mongo_db):
        first = await user_service.get_or_create_user(
            email="repeat@example.com", provider="google", oauth_id="g-repeat", name="Repeat"
        )
        again = await user_service.get_or_create_user(
            email="repeat@example.com", provider="google", oauth_id="g-repeat", name="Repeat"
        )
        assert again.id == first.id

    async def test_raises_when_email_owned_by_different_provider(self, mongo_db):
        await user_service.get_or_create_user(
            email="shared@example.com", provider="google", oauth_id="g-1", name="Shared"
        )
        with pytest.raises(EmailAlreadyRegisteredError):
            await user_service.get_or_create_user(
                email="shared@example.com", provider="discord", oauth_id="d-1", name="Shared"
            )

    async def test_concurrent_first_login_is_idempotent(self, mongo_db):
        """Concurrent first-logins for one identity stay idempotent against the
        real DB: whatever the interleaving, they resolve to one user and one row."""
        import asyncio

        from acemusic.api.models import User

        results = await asyncio.gather(
            *[
                user_service.get_or_create_user(
                    email="race@example.com", provider="google", oauth_id="g-race", name="Racer"
                )
                for _ in range(6)
            ]
        )
        assert len({str(u.id) for u in results}) == 1
        assert await User.find(User.email == "race@example.com").count() == 1

    async def test_insert_race_recovers_to_winning_identity(self, mongo_db, monkeypatch):
        """If a concurrent worker commits our identity first, the losing insert's
        DuplicateKeyError is recovered to that winner row (idempotent first-login).

        The DB is real; we only *inject* the race that ``asyncio.gather`` cannot
        trigger deterministically — the fake insert commits the winner via the raw
        collection, then raises the duplicate-key error our code must handle.
        """
        from pymongo.errors import DuplicateKeyError

        from acemusic.api.models import User
        from acemusic.api.models.common import utcnow

        coll = User.get_pymongo_collection()

        async def winner_then_collide(self):
            await coll.insert_one(
                {
                    "email": "win@example.com",
                    "name": "Winner",
                    "display_name": "Winner",
                    "oauth_provider": "google",
                    "oauth_id": "g-win",
                    "subscription_tier": "free",
                    "handle": None,
                    "bio": None,
                    "style_tags": [],
                    "avatar_url": None,
                    "created_at": utcnow(),
                    "updated_at": None,
                }
            )
            raise DuplicateKeyError("E11000 duplicate key (simulated race)")

        monkeypatch.setattr(User, "insert", winner_then_collide)
        result = await user_service.get_or_create_user(
            email="win@example.com", provider="google", oauth_id="g-win", name="Winner"
        )
        assert result.oauth_id == "g-win"
        assert await User.find(User.email == "win@example.com").count() == 1

    async def test_insert_race_on_foreign_email_raises_conflict(self, mongo_db, monkeypatch):
        """If the insert collides but no row exists for our identity (a different
        identity grabbed the email mid-flight), we surface the same 409 signal."""
        from pymongo.errors import DuplicateKeyError

        from acemusic.api.models import User

        async def always_collide(self):
            raise DuplicateKeyError("E11000 duplicate key (simulated race)")

        monkeypatch.setattr(User, "insert", always_collide)
        with pytest.raises(EmailAlreadyRegisteredError):
            await user_service.get_or_create_user(
                email="foreign@example.com", provider="google", oauth_id="g-foreign", name="Foreign"
            )


@pytest.mark.integration
class TestUpdateUserProfile:
    async def test_updates_allowed_fields(self, mongo_db):
        user = await user_service.get_or_create_user(
            email="editor@example.com", provider="google", oauth_id="g-edit", name="Editor"
        )
        updated = await user_service.update_user_profile(
            str(user.id),
            {"display_name": "Edited", "handle": "editor-1", "bio": "hi", "style_tags": ["lofi"]},
        )
        assert updated.display_name == "Edited"
        assert updated.handle == "editor-1"
        assert updated.bio == "hi"
        assert updated.style_tags == ["lofi"]
        assert updated.updated_at is not None

    async def test_ignores_unknown_fields(self, mongo_db):
        user = await user_service.get_or_create_user(
            email="safe@example.com", provider="google", oauth_id="g-safe", name="Safe"
        )
        updated = await user_service.update_user_profile(
            str(user.id), {"subscription_tier": "pro", "email": "hacked@example.com"}
        )
        # Non-profile fields are not writable through this path.
        assert updated.subscription_tier == "free"
        assert updated.email == "safe@example.com"

    async def test_duplicate_handle_raises_conflict(self, mongo_db):
        a = await user_service.get_or_create_user(email="a@example.com", provider="google", oauth_id="g-a", name="A")
        b = await user_service.get_or_create_user(email="b@example.com", provider="google", oauth_id="g-b", name="B")
        await user_service.update_user_profile(str(a.id), {"handle": "taken"})
        with pytest.raises(HandleConflictError):
            await user_service.update_user_profile(str(b.id), {"handle": "taken"})

    async def test_returns_none_for_unknown_user(self, mongo_db):
        from bson import ObjectId

        result = await user_service.update_user_profile(str(ObjectId()), {"bio": "x"})
        assert result is None


@pytest.mark.integration
class TestGetUserById:
    async def test_returns_user(self, mongo_db):
        user = await user_service.get_or_create_user(
            email="byid@example.com", provider="google", oauth_id="g-byid", name="ById"
        )
        found = await user_service.get_user_by_id(str(user.id))
        assert found is not None
        assert found.id == user.id

    async def test_returns_none_for_malformed_id(self, mongo_db):
        assert await user_service.get_user_by_id("not-an-object-id") is None

    async def test_accepts_object_id_instance(self, mongo_db):
        user = await user_service.get_or_create_user(
            email="oid@example.com", provider="google", oauth_id="g-oid", name="Oid"
        )
        found = await user_service.get_user_by_id(user.id)  # pass the ObjectId directly
        assert found is not None and found.id == user.id
