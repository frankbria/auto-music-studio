"""Multiple OAuth identities per account (#111).

Before this, a second provider reporting an already-registered email was rejected with a
409: correct, but it meant someone with the same address on Google and Discord could only
ever use whichever they signed up with.

Two things these tests pin that are easy to get wrong:

* **Accounts written before this change must still be found.** They have
  ``oauth_provider``/``oauth_id`` and no ``identities`` array, so a lookup that only reads
  the new shape locks every existing user out of their account.
* **Linking is a trust transfer, so it is gated on the provider having verified the
  address.** An unverified collision is still a 409.
"""

import asyncio

import pytest
from pymongo.errors import DuplicateKeyError

from acemusic.api.exceptions import EmailAlreadyRegisteredError
from acemusic.api.models import User
from acemusic.api.services import users as user_service


@pytest.fixture(autouse=True)
def _db(mongo_db):
    return mongo_db


async def _login(email: str, provider: str, oauth_id: str, *, verified: bool = True) -> User:
    return await user_service.get_or_create_user(
        email=email, provider=provider, oauth_id=oauth_id, name="Test User", email_verified=verified
    )


@pytest.mark.integration
class TestLinking:
    async def test_a_second_provider_links_onto_the_existing_account(self) -> None:
        first = await _login("shared@example.com", "google", "g-1")

        second = await _login("shared@example.com", "discord", "d-1")

        assert second.id == first.id
        assert {(i.provider, i.oauth_id) for i in second.identities} == {("google", "g-1"), ("discord", "d-1")}
        # Still one account for the address — linking, not duplicating.
        assert len(await User.find(User.email == "shared@example.com").to_list()) == 1

    async def test_either_identity_then_signs_in_to_the_same_account(self) -> None:
        first = await _login("both@example.com", "google", "g-2")
        await _login("both@example.com", "discord", "d-2")

        via_google = await _login("both@example.com", "google", "g-2")
        via_discord = await _login("both@example.com", "discord", "d-2")

        assert via_google.id == first.id
        assert via_discord.id == first.id

    async def test_linking_is_idempotent(self) -> None:
        await _login("idem@example.com", "google", "g-3")
        await _login("idem@example.com", "discord", "d-3")

        again = await _login("idem@example.com", "discord", "d-3")

        assert len(again.identities) == 2

    async def test_the_primary_identity_does_not_move_when_a_second_links(self) -> None:
        # oauth_provider/oauth_id stay pointed at identities[0] — they are the legacy
        # denormalisation the existing partial-unique index is built on, so a link must
        # not repoint them at the newcomer.
        await _login("primary@example.com", "google", "g-4")

        linked = await _login("primary@example.com", "discord", "d-4")

        assert linked.oauth_provider == "google"
        assert linked.oauth_id == "g-4"
        assert linked.identities[0].provider == "google"

    async def test_an_unverified_email_collision_is_still_a_conflict(self) -> None:
        # Linking transfers control of an account, so an unverified assertion must not do
        # it. The callback gates on verification before it ever gets here; this keeps the
        # service honest for every other caller.
        await _login("guard@example.com", "google", "g-5")

        with pytest.raises(EmailAlreadyRegisteredError):
            await _login("guard@example.com", "discord", "d-5", verified=False)

    async def test_concurrent_links_of_the_same_identity_converge(self) -> None:
        await _login("race@example.com", "google", "g-6")

        results = await asyncio.gather(*(_login("race@example.com", "discord", "d-6") for _ in range(6)))

        assert len({u.id for u in results}) == 1
        refreshed = await User.get(results[0].id)
        assert len(refreshed.identities) == 2


@pytest.mark.integration
class TestLegacyAccounts:
    async def test_an_account_written_before_identities_existed_still_signs_in(self) -> None:
        # Exactly the on-disk shape of a pre-#111 document: no `identities` key at all.
        raw = {
            "email": "legacy@example.com",
            "name": "Legacy",
            "oauth_provider": "google",
            "oauth_id": "g-legacy",
            "subscription_tier": "free",
            "credits_balance": 10.0,
        }
        await User.get_pymongo_collection().insert_one(raw)

        found = await _login("legacy@example.com", "google", "g-legacy")

        assert found.email == "legacy@example.com"
        assert [(i.provider, i.oauth_id) for i in found.identities] == [("google", "g-legacy")]

    async def test_a_legacy_account_gets_its_identities_persisted_not_just_materialised(self) -> None:
        # Materialising on read is not enough: the new index and the linking lookup both
        # query the stored array, so it has to reach the database.
        await User.get_pymongo_collection().insert_one(
            {"email": "backfill@example.com", "name": "B", "oauth_provider": "discord", "oauth_id": "d-legacy"}
        )

        await _login("backfill@example.com", "discord", "d-legacy")

        stored = await User.get_pymongo_collection().find_one({"email": "backfill@example.com"})
        assert stored["identities"] == [{"provider": "discord", "oauth_id": "d-legacy"}] or [
            (i["provider"], i["oauth_id"]) for i in stored["identities"]
        ] == [("discord", "d-legacy")]

    async def test_a_legacy_account_can_be_linked_to_a_second_provider(self) -> None:
        await User.get_pymongo_collection().insert_one(
            {"email": "legacylink@example.com", "name": "L", "oauth_provider": "google", "oauth_id": "g-ll"}
        )

        linked = await _login("legacylink@example.com", "discord", "d-ll")

        assert {(i.provider, i.oauth_id) for i in linked.identities} == {("google", "g-ll"), ("discord", "d-ll")}


@pytest.mark.integration
class TestIdentityUniqueness:
    async def test_one_identity_cannot_be_claimed_by_two_accounts(self) -> None:
        await _login("owner@example.com", "google", "g-unique")

        # A different email arriving with an identity that is already linked elsewhere.
        # The index is the real guard; this asserts it exists and bites.
        with pytest.raises((DuplicateKeyError, EmailAlreadyRegisteredError)):
            other = User(email="thief@example.com", name="T", oauth_provider="google", oauth_id="g-unique")
            await other.insert()
