"""Refresh token document model (US-8.3).

Only the SHA-256 hash of a refresh token is ever persisted (``token_hash``), so a
database leak does not expose usable credentials. A TTL index on ``expires_at``
lets MongoDB reap expired tokens automatically; the service layer also checks
expiry/revocation on lookup for defense in depth.
"""

from datetime import datetime

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import ASCENDING, IndexModel

from .common import utcnow


class RefreshToken(Document):
    """A stored refresh token (hashed) bound to a user."""

    token_hash: str
    user_id: PydanticObjectId
    expires_at: datetime
    revoked: bool = False
    created_at: datetime = Field(default_factory=utcnow)
    #: ``"web"`` for a browser session, ``"plugin"`` for a DAW-plugin credential
    #: minted by ``/auth/plugin-token``. Plugin tokens are the only ones the
    #: musician can list and revoke from Settings (#515).
    #:
    #: The default applies to *reads* only. A document written before this field
    #: existed has no ``kind`` key at all, so it matches neither ``"web"`` nor
    #: ``"plugin"`` in a query — and because #445 wrote plugin tokens and browser
    #: sessions identically, nothing in such a document says which it was. Those
    #: are retired at startup by ``retire_untagged_refresh_tokens`` rather than
    #: guessed at, so an untaggable plugin token cannot linger unlistable.
    kind: str = "web"
    #: The hash this document held before its last rotation, and when that
    #: rotation happened (#525). Rotating in place erases the spent hash, which
    #: is the only thing that tells a replayed token apart from a random string —
    #: keeping it here restores OAuth refresh-token reuse detection without
    #: handing the lineage a new document id on every refresh (#515 AC2).
    #:
    #: ``None`` on a token that has never rotated, and absent entirely from a
    #: document written before this field existed. Neither is a replay candidate:
    #: nothing has been spent yet.
    previous_token_hash: str | None = None
    rotated_at: datetime | None = None

    class Settings:
        name = "refresh_tokens"
        indexes = [
            IndexModel([("token_hash", ASCENDING)], unique=True),
            IndexModel([("user_id", ASCENDING)]),
            # Not unique: every un-rotated document carries a null here, and a
            # unique index would let the first one block every later insert.
            IndexModel([("previous_token_hash", ASCENDING)]),
            # TTL index: MongoDB deletes documents once ``expires_at`` is in the
            # past (expireAfterSeconds=0 means "expire at the stored time").
            IndexModel([("expires_at", ASCENDING)], expireAfterSeconds=0),
        ]
