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
from pymongo import DESCENDING

from ..models import RefreshToken


def _hash_token(raw_token: str) -> str:
    """Return the hex SHA-256 digest used as the stored lookup key."""
    return hashlib.sha256(raw_token.encode()).hexdigest()


async def store_refresh_token(
    user_id: PydanticObjectId,
    raw_token: str,
    expires_at: datetime,
    kind: str = "web",
) -> RefreshToken:
    """Persist the hash of ``raw_token`` bound to ``user_id`` and return it."""
    token = RefreshToken(
        token_hash=_hash_token(raw_token),
        user_id=user_id,
        expires_at=expires_at,
        kind=kind,
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


async def rotate_refresh_token(
    old_raw: str,
    new_raw: str,
    expires_at: datetime,
) -> PydanticObjectId | None:
    """Atomically swap a valid token's hash for ``new_raw``. Return its owner, else ``None``.

    The swap is a single ``find_one_and_update`` filtered on the *old* hash, so
    two concurrent refreshes of the same token cannot both succeed — the first
    replaces the hash and gets the document; every loser matches nothing and gets
    ``None``. That is the same single-use guarantee a revoke-and-reissue gives,
    and it is why this cannot be a separate validate-then-update.

    Rotating **in place** rather than revoking the old document and inserting a
    new one is what lets a plugin token keep one identity across refreshes: it is
    listed and revoked by document id (#515), and a fresh document each refresh
    would hand the same credential a new id every time. Replaying the old token
    still finds nothing, so it is rejected exactly as before.

    Revoked and expired tokens are excluded by the filter, so neither is
    rewritten on its way to being rejected — an expired document keeps its own
    hash and is left for the TTL index.
    """
    collection = RefreshToken.get_pymongo_collection()
    doc = await collection.find_one_and_update(
        {
            "token_hash": _hash_token(old_raw),
            "revoked": False,
            "expires_at": {"$gt": datetime.now(timezone.utc)},
        },
        {"$set": {"token_hash": _hash_token(new_raw), "expires_at": expires_at}},
    )
    return None if doc is None else doc["user_id"]


async def revoke_refresh_token(raw_token: str) -> bool:
    """Revoke a single token. Return ``True`` if a token was revoked."""
    token = await RefreshToken.find_one(RefreshToken.token_hash == _hash_token(raw_token))
    if token is None or token.revoked:
        return False
    token.revoked = True
    await token.save()
    return True


async def list_plugin_tokens(user_id: PydanticObjectId) -> list[RefreshToken]:
    """Return ``user_id``'s live plugin tokens, newest first (#515).

    Live means un-revoked and unexpired: a token the musician can still act on.
    Web sessions are excluded by ``kind`` — Settings lists DAW credentials, not
    the browser session the musician is reading the page in.
    """
    return (
        await RefreshToken.find(
            RefreshToken.user_id == user_id,
            RefreshToken.kind == "plugin",
            RefreshToken.revoked == False,  # noqa: E712 — Beanie needs == for the query
            RefreshToken.expires_at > datetime.now(timezone.utc),
        )
        # ``_id`` breaks the tie: two tokens minted in the same millisecond share a
        # ``created_at``, and an undefined order there would make the listing (and
        # its test) flap.
        .sort([("created_at", DESCENDING), ("_id", DESCENDING)]).to_list()
    )


async def revoke_plugin_token(user_id: PydanticObjectId, token_id: PydanticObjectId) -> bool:
    """Revoke one of ``user_id``'s plugin tokens. Return ``False`` if there is no such token.

    Scoping the update to the owner *and* to ``kind == "plugin"`` in one query is
    what stops this endpoint from being used to sign another account — or this
    account's own browser — out. Revoking twice still returns ``True``: the
    caller asked for a token of theirs to be dead, and it is.
    """
    result = await RefreshToken.get_pymongo_collection().update_one(
        {"_id": token_id, "user_id": user_id, "kind": "plugin"},
        {"$set": {"revoked": True}},
    )
    return result.matched_count == 1


async def revoke_all_user_tokens(user_id: PydanticObjectId) -> int:
    """Revoke every non-revoked token for ``user_id``. Return the count revoked."""
    result = await RefreshToken.find(
        RefreshToken.user_id == user_id,
        RefreshToken.revoked == False,  # noqa: E712 — Beanie needs == for the query
    ).update({"$set": {"revoked": True}})
    return result.modified_count
