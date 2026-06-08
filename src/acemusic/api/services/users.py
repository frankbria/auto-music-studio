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
from ..models import User
from ..models.common import utcnow

HANDLE_MIN_LENGTH = 3
HANDLE_MAX_LENGTH = 30
# Letters/digits/hyphens, but must start and end with an alphanumeric — so
# "-foo", "foo-" and "---" are rejected as the entry errors they look like.
_HANDLE_PATTERN = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?$")

# Only these fields are writable through the profile-update path. Everything else
# on the User document (email, subscription_tier, oauth_*) is off-limits here so a
# PATCH body cannot escalate privileges or hijack an OAuth identity.
_UPDATABLE_FIELDS = ("display_name", "handle", "bio", "style_tags")


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


async def get_or_create_user(*, email: str, provider: str, oauth_id: str, name: str) -> User:
    """Find the user for an OAuth identity, creating one on first login.

    This is the canonical upsert US-8.3's callback invokes. On creation the
    profile ``display_name`` is seeded from the provider-reported ``name``.

    Raises :class:`EmailAlreadyRegisteredError` when the verified email already
    belongs to a *different* OAuth identity (single-identity model; linking is
    future work).
    """
    user = await User.find_one(User.oauth_provider == provider, User.oauth_id == oauth_id)
    if user is not None:
        # Known identity. The provider may report a changed email; only apply it
        # when the address is free (or already ours), otherwise keep our current
        # email so the user still logs into their own account without violating
        # the unique index.
        email_owner = await User.find_one(User.email == email)
        if email_owner is None or email_owner.id == user.id:
            user.email = email
            user.name = name
            user.updated_at = utcnow()
            await user.save()
        return user

    if await User.find_one(User.email == email) is not None:
        raise EmailAlreadyRegisteredError(email)

    user = User(
        email=email,
        name=name,
        display_name=name,
        oauth_provider=provider,
        oauth_id=oauth_id,
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
        existing = await User.find_one(User.oauth_provider == provider, User.oauth_id == oauth_id)
        if existing is not None:
            return existing
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
        await user.save()
    except DuplicateKeyError as exc:
        # ``handle`` is the only writable field (see _UPDATABLE_FIELDS) that
        # carries a unique index, so a duplicate-key error on this path can only
        # be a handle collision. If a future writable field gains a unique index,
        # narrow this catch (inspect exc.details) so it isn't misreported as 409.
        raise HandleConflictError(fields.get("handle")) from exc
    return user
