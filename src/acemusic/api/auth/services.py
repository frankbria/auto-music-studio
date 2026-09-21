"""Refresh-token persistence service (US-8.3).

All functions operate on the SHA-256 hash of the raw token: the raw value is
hashed before it is ever written to or looked up in MongoDB, so a database
compromise never yields usable refresh tokens.

A TTL index reaps expired tokens, but ``validate_refresh_token`` re-checks expiry
and revocation on every lookup (defense in depth — TTL reaping is best-effort and
lags the actual expiry time).
"""

import hashlib
import logging
from datetime import datetime, timedelta, timezone

from beanie import PydanticObjectId
from pymongo import DESCENDING

from ..models import RefreshToken

logger = logging.getLogger(__name__)

#: How long after a rotation the spent token is still forgiven rather than treated
#: as a replay (#525). A client that fires two refreshes at once presents exactly
#: what a thief does — the same spent token — and only elapsed time separates them.
#: Inside this window the second attempt is still refused; it just does not kill the
#: family. Three seconds is Auth0's default for the same trade-off.
REUSE_LEEWAY_SECONDS = 3

#: How many spent hashes a lineage remembers (#525). A thief typically sits on a
#: stolen token while the real client keeps refreshing, so remembering only the
#: last rotation would miss the ordinary case. It is capped rather than complete
#: because rotation pushes ``expires_at`` out: a session used daily never expires,
#: and an unbounded list would grow for the life of the account. At the usual
#: refresh cadence this covers days of rotations — a replay older than that is
#: still refused, it just is not attributed to a theft.
REUSE_HISTORY_DEPTH = 100


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

    The swap also records the hash it just spent on the same document, so the
    rejection above can tell a *replay* from a random string — see
    ``_detect_refresh_token_reuse``.
    """
    collection = RefreshToken.get_pymongo_collection()
    now = datetime.now(timezone.utc)
    old_hash = _hash_token(old_raw)
    doc = await collection.find_one_and_update(
        {
            "token_hash": old_hash,
            "revoked": False,
            "expires_at": {"$gt": now},
        },
        {
            "$set": {
                "token_hash": _hash_token(new_raw),
                "expires_at": expires_at,
                "rotated_at": now,
            },
            # ``$slice`` keeps the newest ``REUSE_HISTORY_DEPTH`` and drops the rest
            # in the same atomic update, so the history can never outgrow its cap.
            "$push": {"previous_token_hashes": {"$each": [old_hash], "$slice": -REUSE_HISTORY_DEPTH}},
        },
    )
    if doc is None:
        await _detect_refresh_token_reuse(old_hash)
        return None
    return doc["user_id"]


async def _detect_refresh_token_reuse(spent_hash: str) -> bool:
    """Kill the lineage that already spent ``spent_hash``. Return ``True`` if one was killed.

    A refresh token is single-use, so the only way to present one the server has
    already consumed is to have held a copy of it — the classic OAuth signal that a
    token was stolen. The thief's copy is dead on arrival; what has to die with it is
    the *successor* the real client is holding, because whoever replayed the old token
    may hold that one too.

    The kill is the document, which under in-place rotation is the whole token family:
    one lineage per document (#515 AC2). It deliberately stops there rather than
    revoking every token of the user — signing the musician's DAW plugin out because a
    browser session was replayed is a worse default than the attack it prevents, and
    the plugin's own lineage is unaffected by the theft.

    Revoke, rather than delete: the TTL index reaps the document on schedule, and until
    then the spent history keeps answering this question for any further replays.

    Bounded by ``REUSE_HISTORY_DEPTH``: a replay older than that many rotations is
    refused like any other dead token, it simply is not recognised as a theft.
    """
    result = await RefreshToken.get_pymongo_collection().find_one_and_update(
        {
            # Matches any element of the array — every hash this lineage has spent.
            "previous_token_hashes": spent_hash,
            "revoked": False,
            # Outside the leeway only. A document missing ``rotated_at`` cannot match
            # here, which is correct: its spent history is empty too, so it never
            # reaches this filter in the first place.
            "rotated_at": {"$lt": datetime.now(timezone.utc) - timedelta(seconds=REUSE_LEEWAY_SECONDS)},
        },
        {"$set": {"revoked": True}},
    )
    if result is None:
        return False
    logger.warning(
        "Refresh-token reuse detected for user %s; revoked token lineage %s",
        result["user_id"],
        result["_id"],
    )
    return True


async def revoke_refresh_token(raw_token: str) -> bool:
    """Revoke a single token. Return ``True`` if a token was revoked.

    One atomic update rather than a read-modify-``save()``: ``save()`` writes the
    whole document back, so a logout that read the document just before a rotation
    landed would silently undo that rotation's hash swap and spent history (#525),
    handing a spent token back its validity.
    """
    result = await RefreshToken.get_pymongo_collection().update_one(
        {"token_hash": _hash_token(raw_token), "revoked": False},
        {"$set": {"revoked": True}},
    )
    return result.modified_count == 1


async def retire_untagged_refresh_tokens() -> int:
    """Revoke every refresh token stored before ``kind`` existed. Return the count.

    A document written before #515 has no ``kind`` key at all, and nothing in it
    says whether it was a browser session or a DAW plugin token minted by #445 —
    both were written identically. Guessing "web" would produce the worst possible
    outcome for the issue this feature exists to close: a leaked plugin token would
    stay absent from the Settings list *and* keep refreshing itself indefinitely,
    because rotation pushes ``expires_at`` out on every use, so the TTL never
    reaps a token that is being used.

    They are therefore retired rather than guessed at. Everyone signs in once more
    and re-pastes a plugin token, and every credential from then on is tagged and
    revocable.

    Idempotent but not one-shot: once no document lacks ``kind`` this matches
    nothing, yet it still scans the collection on every boot, because ``kind`` is
    not indexed. In-place rotation keeps one document per session lineage rather
    than one per refresh, so that scan is bounded by live sessions — add a ``kind``
    index if it ever shows up in profiling.
    """
    result = await RefreshToken.get_pymongo_collection().update_many(
        {"kind": {"$exists": False}},
        {"$set": {"kind": "web", "revoked": True}},
    )
    return result.modified_count


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
    account's own browser — out. Revoking twice still returns ``True``: the caller
    asked for a token of theirs to be dead, and it is.

    Expiry is deliberately not in the filter, so an already-expired plugin token of
    the caller's own still reports success rather than "not found". The cost is a
    narrow oracle — ``True`` here and ``False`` for an id that was never theirs
    distinguishes the two — which needs a valid ObjectId of the caller's own to
    ask, so it tells an attacker nothing they did not already have.
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
