"""User profile service layer (US-8.4).

Module-level async functions (mirroring :mod:`acemusic.api.auth.services`) that
encapsulate user profile operations so routers — and US-8.3's OAuth callback —
share one implementation. The layer raises domain exceptions
(:mod:`acemusic.api.exceptions`), never ``HTTPException``, so it stays
transport-agnostic.
"""

import re

from beanie import PydanticObjectId
from bson.errors import InvalidId
from pymongo.errors import DuplicateKeyError

from ..exceptions import EmailAlreadyRegisteredError, HandleConflictError
from ..models import OAuthIdentity, User
from ..models.common import utcnow

HANDLE_MIN_LENGTH = 3
HANDLE_MAX_LENGTH = 30
# Letters/digits/hyphens, but must start and end with an alphanumeric — so
# "-foo", "foo-" and "---" are rejected as the entry errors they look like.
_HANDLE_PATTERN = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?$")

# Only these fields are writable through the profile-update path. Everything else
# on the User document (email, subscription_tier, oauth_*) is off-limits here so a
# PATCH body cannot escalate privileges or hijack an OAuth identity.
_UPDATABLE_FIELDS = ("display_name", "handle", "bio", "style_tags", "default_model")


class HandleValidationError(ValueError):
    """A handle failed format validation. The message is safe to show the user."""


def validate_handle(handle: str) -> str:
    """Return ``handle`` unchanged if it is well-formed, else raise.

    Rules: 3–30 characters, letters/digits/hyphens only. Each failure mode gets a
    distinct message so the API can tell the user exactly what to fix.
    """
    if len(handle) < HANDLE_MIN_LENGTH:
        raise HandleValidationError(f"Handle must be at least {HANDLE_MIN_LENGTH} characters.")
    if len(handle) > HANDLE_MAX_LENGTH:
        raise HandleValidationError(f"Handle must be at most {HANDLE_MAX_LENGTH} characters.")
    if not _HANDLE_PATTERN.match(handle):
        raise HandleValidationError(
            "Handle may contain only letters, numbers, and hyphens, " "and must start and end with a letter or number."
        )
    return handle


def _to_object_id(user_id: str | PydanticObjectId) -> PydanticObjectId | None:
    if isinstance(user_id, PydanticObjectId):
        return user_id
    try:
        return PydanticObjectId(user_id)
    except (InvalidId, ValueError, TypeError):
        return None


async def get_user_by_id(user_id: str | PydanticObjectId) -> User | None:
    """Fetch a user by id. Returns ``None`` for unknown or malformed ids."""
    oid = _to_object_id(user_id)
    if oid is None:
        return None
    return await User.get(oid)


async def _find_by_identity(provider: str, oauth_id: str) -> User | None:
    """The account this OAuth identity signs into, linked or primary.

    The ``$or`` is what keeps accounts written before #111 reachable: they have only the
    legacy pair and no ``identities`` array, so a query against the new shape alone would
    lock every existing user out of their own account.
    """
    return await User.find_one(
        {
            "$or": [
                {"identities": {"$elemMatch": {"provider": provider, "oauth_id": oauth_id}}},
                {"oauth_provider": provider, "oauth_id": oauth_id},
            ]
        }
    )


async def _persist_identities(user: User) -> None:
    """Write a materialised ``identities`` list back for a pre-#111 document.

    The validator derives it on read, but the linking lookup and the unique index both
    query the *stored* array — so without this the new shape would never reach the
    database. Conditional on the field still being absent and touching only that field:
    the ``credits_reset_at`` backfill idiom, for the same reason. A full ``save()`` would
    push a whole stale document back and could revert a concurrent write.
    """
    if not user.identities:
        return

    await User.get_pymongo_collection().update_one(
        {"_id": user.id, "identities": {"$exists": False}},
        {"$set": {"identities": [i.model_dump() for i in user.identities]}},
    )


async def _refresh_profile(user: User, *, email: str, name: str) -> None:
    """Apply the provider's current email and display name to ``user``.

    A targeted ``$set``, not ``save()``. Beanie replaces the whole document from the
    in-memory model (no state management on ``User``), so this — which runs on *every*
    login, not only when something changed — would write back whatever ``identities`` the
    request happened to load and silently delete a link another request pushed in the
    meantime. The user would just stop being able to sign in with that provider.

    Raised in review on this PR. The principle was already written down two functions up
    and simply not applied here.
    """
    now = utcnow()
    await User.get_pymongo_collection().update_one(
        {"_id": user.id}, {"$set": {"email": email, "name": name, "updated_at": now}}
    )
    # Keep the instance the caller is about to use consistent with what was stored.
    user.email = email
    user.name = name
    user.updated_at = now


async def _link_identity(user: User, provider: str, oauth_id: str) -> User:
    """Attach a new OAuth identity to an existing account.

    A single conditioned ``$push``: the filter excludes accounts that already carry the
    identity, so concurrent logins converge on one entry instead of appending duplicates.
    """
    identity = OAuthIdentity(provider=provider, oauth_id=oauth_id, linked_at=utcnow())

    await User.get_pymongo_collection().update_one(
        {"_id": user.id, "identities": {"$not": {"$elemMatch": {"provider": provider, "oauth_id": oauth_id}}}},
        {
            # The caller persists a legacy document's materialised array first, so this
            # only ever appends to an array that already carries the primary identity.
            "$set": {"updated_at": utcnow()},
            "$push": {"identities": identity.model_dump()},
        },
    )
    return await User.get(user.id) or user


async def get_or_create_user(
    *, email: str, provider: str, oauth_id: str, name: str, email_verified: bool = False
) -> User:
    """Find the user for an OAuth identity, creating or linking one as needed.

    This is the canonical upsert US-8.3's callback invokes. On creation the
    profile ``display_name`` is seeded from the provider-reported ``name``.

    ``email_verified`` says the provider vouched for the address, and it is what permits
    a second provider to be **linked** onto an existing account (#111). It defaults to
    False because linking transfers control of an account: every caller that has not
    thought about verification keeps the old, safe behaviour of refusing the collision.
    The OAuth callback opts in, having already rejected unverified emails with a 403.

    Raises :class:`EmailAlreadyRegisteredError` when the email belongs to a different
    identity and the caller cannot vouch for it.
    """
    user = await _find_by_identity(provider, oauth_id)
    if user is not None:
        await _persist_identities(user)
        # Known identity. The provider may report a changed email; only apply it
        # when the address is free (or already ours), otherwise keep our current
        # email so the user still logs into their own account without violating
        # the unique index.
        email_owner = await User.find_one(User.email == email)
        if email_owner is None or email_owner.id == user.id:
            await _refresh_profile(user, email=email, name=name)
        return user

    email_owner = await User.find_one(User.email == email)
    if email_owner is not None:
        # A concurrent first-login for the *same* identity may have inserted
        # this row between the identity lookup above and here — that's the
        # idempotent case, not a conflict (mirrors the DuplicateKeyError
        # recovery below).
        if any(i.provider == provider and i.oauth_id == oauth_id for i in email_owner.identities):
            return email_owner

        # #111: a different identity owns the address. When the provider has verified it,
        # that is the same person arriving by another door — link rather than refuse.
        if not email_verified:
            raise EmailAlreadyRegisteredError(email)

        await _persist_identities(email_owner)
        return await _link_identity(email_owner, provider, oauth_id)

    user = User(
        email=email,
        name=name,
        display_name=name,
        identities=[OAuthIdentity(provider=provider, oauth_id=oauth_id)],
    )
    try:
        await user.insert()
    except DuplicateKeyError:
        # A concurrent first-login for the same identity (or email) raced us
        # between the checks above and this insert. The unique indexes are the
        # real guard, so re-resolve rather than 500: if our identity won
        # elsewhere, return that row (first-login is idempotent); if a different
        # identity claimed the email first, surface the same 409 as the non-race
        # path.
        existing = await _find_by_identity(provider, oauth_id)
        if existing is not None:
            return existing

        # A different identity claimed the email first. Same fork as above: link when the
        # provider vouched for the address, refuse when it did not.
        loser_to = await User.find_one(User.email == email)
        if loser_to is not None and email_verified:
            await _persist_identities(loser_to)
            return await _link_identity(loser_to, provider, oauth_id)
        raise EmailAlreadyRegisteredError(email) from None
    return user


async def update_user_profile(user_id: str | PydanticObjectId, updates: dict) -> User | None:
    """Apply profile ``updates`` to the user, returning the saved document.

    Only :data:`_UPDATABLE_FIELDS` are written; unknown keys are ignored. Returns
    ``None`` if the user does not exist. Raises :class:`HandleConflictError` if the
    requested handle is already taken, and :class:`HandleValidationError` if a
    provided handle is malformed (defense in depth — the API schema validates first).
    """
    user = await get_user_by_id(user_id)
    if user is None:
        return None

    fields = {k: v for k, v in updates.items() if k in _UPDATABLE_FIELDS}
    if "handle" in fields and fields["handle"] is not None:
        validate_handle(fields["handle"])

    for field, value in fields.items():
        setattr(user, field, value)
    user.updated_at = utcnow()

    try:
        # A targeted $set of the writable fields, for the same reason as
        # _refresh_profile: Beanie's save() replaces the whole document, so a profile
        # edit racing an OAuth login would write back a pre-link `identities` array and
        # silently drop the linked provider. Narrower window than the login path, same
        # silent loss.
        await User.get_pymongo_collection().update_one(
            {"_id": user.id}, {"$set": {**fields, "updated_at": user.updated_at}}
        )
    except DuplicateKeyError as exc:
        # ``handle`` is the only writable field (see _UPDATABLE_FIELDS) that
        # carries a unique index, so a duplicate-key error on this path can only
        # be a handle collision. If a future writable field gains a unique index,
        # narrow this catch (inspect exc.details) so it isn't misreported as 409.
        raise HandleConflictError(fields.get("handle")) from exc
    return user
