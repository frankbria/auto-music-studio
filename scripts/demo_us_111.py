"""Demo for #111: multiple OAuth identities per account, against a real MongoDB."""

import asyncio
import os

from acemusic.api import database
from acemusic.api.exceptions import EmailAlreadyRegisteredError
from acemusic.api.models import User
from acemusic.api.services import users as user_service
from acemusic.api.settings import ApiSettings

#: A throwaway database — this demo drops it on every run.
MONGO_URL = os.environ.get("ACEMUSIC_DEMO_MONGODB_URL", "mongodb://127.0.0.1:27017")
DB_NAME = "acemusic_demo_111"


def show(user: User) -> str:
    ids = ", ".join(f"{i.provider}:{i.oauth_id}" for i in user.identities)
    return f"id={str(user.id)[-6:]} email={user.email} primary={user.oauth_provider} identities=[{ids}]"


async def main() -> None:
    settings = ApiSettings(_env_file=None, mongodb_url=MONGO_URL, mongodb_db_name=DB_NAME)
    client = await database.init_db(settings)
    await client.drop_database(DB_NAME)
    client = await database.init_db(settings)

    print("=" * 78)
    print("1. A NEW ACCOUNT records the identity it was created with")
    print("=" * 78)
    google = await user_service.get_or_create_user(
        email="musician@example.com", provider="google", oauth_id="g-123", name="Musician", email_verified=True
    )
    print(f"   sign in with Google -> {show(google)}")

    print()
    print("=" * 78)
    print("2. THE SAME EMAIL VIA DISCORD links instead of being refused (was: 409)")
    print("=" * 78)
    discord = await user_service.get_or_create_user(
        email="musician@example.com", provider="discord", oauth_id="d-456", name="Musician", email_verified=True
    )
    print(f"   sign in with Discord -> {show(discord)}")
    print(f"   same account?           {discord.id == google.id}")
    print(f"   accounts for that email: {len(await User.find(User.email == 'musician@example.com').to_list())}")

    print()
    print("   ...and either provider now signs into it:")
    for provider, oauth_id in (("google", "g-123"), ("discord", "d-456")):
        u = await user_service.get_or_create_user(
            email="musician@example.com", provider=provider, oauth_id=oauth_id, name="Musician", email_verified=True
        )
        print(f"     {provider:8} -> id={str(u.id)[-6:]}  (same: {u.id == google.id})")

    print()
    print("=" * 78)
    print("3. AN UNVERIFIED COLLISION IS STILL REFUSED — linking transfers account control")
    print("=" * 78)
    try:
        await user_service.get_or_create_user(
            email="musician@example.com", provider="discord", oauth_id="d-imposter", name="X", email_verified=False
        )
        print("   !! linked — this should not happen")
    except EmailAlreadyRegisteredError as exc:
        print(f"   EmailAlreadyRegisteredError: {exc}  -> the route maps this to 409")

    print()
    print("=" * 78)
    print("4. AN ACCOUNT WRITTEN BEFORE THIS CHANGE — no `identities` key on disk at all")
    print("=" * 78)
    legacy_raw = {
        "email": "legacy@example.com",
        "name": "Legacy",
        "oauth_provider": "google",
        "oauth_id": "g-legacy",
        "subscription_tier": "free",
        "credits_balance": 10.0,
    }
    await User.get_pymongo_collection().insert_one(legacy_raw)
    stored = await User.get_pymongo_collection().find_one({"email": "legacy@example.com"})
    print(f"   on disk before login: identities key present = {'identities' in stored}")

    legacy = await user_service.get_or_create_user(
        email="legacy@example.com", provider="google", oauth_id="g-legacy", name="Legacy", email_verified=True
    )
    print(f"   signs in fine       -> {show(legacy)}")
    stored = await User.get_pymongo_collection().find_one({"email": "legacy@example.com"})
    print(f"   on disk after login : identities = {stored.get('identities')}")

    linked = await user_service.get_or_create_user(
        email="legacy@example.com", provider="discord", oauth_id="d-legacy", name="Legacy", email_verified=True
    )
    print(f"   and links a second  -> {show(linked)}")

    print()
    print("=" * 78)
    print("5. CONCURRENT LOGINS with the same new identity converge on one entry")
    print("=" * 78)
    await user_service.get_or_create_user(
        email="race@example.com", provider="google", oauth_id="g-race", name="Race", email_verified=True
    )
    results = await asyncio.gather(
        *(
            user_service.get_or_create_user(
                email="race@example.com", provider="discord", oauth_id="d-race", name="Race", email_verified=True
            )
            for _ in range(6)
        )
    )
    refreshed = await User.get(results[0].id)
    print(f"   6 concurrent Discord logins -> distinct accounts: {len({u.id for u in results})}")
    print(f"   identities recorded         -> {len(refreshed.identities)} (no duplicate entries)")

    print()
    print("=" * 78)
    print("6. AN IDENTITY CANNOT BE CLAIMED BY TWO ACCOUNTS — the index is the guard")
    print("=" * 78)
    indexes = await User.get_pymongo_collection().index_information()
    for name, spec in indexes.items():
        if "identities" in name or "oauth" in name:
            print(f"   {name}: key={spec['key']} unique={spec.get('unique')}")
    try:
        thief = User(email="thief@example.com", name="T", oauth_provider="google", oauth_id="g-123")
        await thief.insert()
        print("   !! inserted — this should not happen")
    except Exception as exc:  # noqa: BLE001 - the demo prints whatever guard fired
        print(f"   rejected: {type(exc).__name__}")

    await database.close_db(client)


asyncio.run(main())
