"""Refresh-token persistence service (US-8.3).

All functions operate on the SHA-256 hash of the raw token: the raw value is
hashed before it is ever written to or looked up in MongoDB, so a database
compromise never yields usable refresh tokens.

A TTL index reaps expired tokens, but ``validate_refresh_token`` re-checks expiry
and revocation on every lookup (defense in depth — TTL reaping is best-effort and
lags the actual expiry time).
"""

import hashlib
from datetime import datetime, timezone

from beanie import PydanticObjectId

from ..models import RefreshToken


def _hash_token(raw_token: str) -> str:
    """Return the hex SHA-256 digest used as the stored lookup key."""
    return hashlib.sha256(raw_token.encode()).hexdigest()


async def store_refresh_token(
    user_id: PydanticObjectId,
    raw_token: str,
    expires_at: datetime,
) -> RefreshToken:
    """Persist the hash of ``raw_token`` bound to ``user_id`` and return it."""
    token = RefreshToken(
        token_hash=_hash_token(raw_token),
        user_id=user_id,
        expires_at=expires_at,
    )
    return await token.insert()


async def validate_refresh_token(raw_token: str) -> PydanticObjectId | None:
    """Return the owning ``user_id`` if the token is valid, else ``None``.

    A token is invalid when it is unknown, revoked, or already expired.
    """
    token = await RefreshToken.find_one(RefreshToken.token_hash == _hash_token(raw_token))
    if token is None or token.revoked:
        return None

    expires_at = token.expires_at
    if expires_at.tzinfo is None:
        # MongoDB returns naive UTC datetimes; compare in UTC.
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        return None
    return token.user_id


async def consume_refresh_token(raw_token: str) -> PydanticObjectId | None:
    """Atomically revoke a valid token and return its owner, else ``None``.

    The revoke-and-return is a single ``find_one_and_update`` filtered on
    ``revoked: False``, so two concurrent refreshes on the same token cannot both
    succeed — only the first flips ``revoked`` and gets the document; the loser
    matches nothing and gets ``None``. This preserves single-use rotation even
    under duplicate/concurrent requests, which a separate validate-then-revoke
    cannot guarantee. An expired (but still un-revoked) token is consumed and
    rejected as ``None``.
    """
    collection = RefreshToken.get_pymongo_collection()
    doc = await collection.find_one_and_update(
        {"token_hash": _hash_token(raw_token), "revoked": False},
        {"$set": {"revoked": True}},
    )
    if doc is None:
        return None

    expires_at = doc["expires_at"]
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        return None
    return doc["user_id"]


async def revoke_refresh_token(raw_token: str) -> bool:
    """Revoke a single token. Return ``True`` if a token was revoked."""
    token = await RefreshToken.find_one(RefreshToken.token_hash == _hash_token(raw_token))
    if token is None or token.revoked:
        return False
    token.revoked = True
    await token.save()
    return True


async def revoke_all_user_tokens(user_id: PydanticObjectId) -> int:
    """Revoke every non-revoked token for ``user_id``. Return the count revoked."""
    result = await RefreshToken.find(
        RefreshToken.user_id == user_id,
        RefreshToken.revoked == False,  # noqa: E712 — Beanie needs == for the query
    ).update({"$set": {"revoked": True}})
    return result.modified_count
