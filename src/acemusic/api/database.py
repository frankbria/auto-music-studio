"""MongoDB connection lifecycle for the platform API (US-8.2).

Uses pymongo's native async client (``AsyncMongoClient``) with Beanie as the ODM.
``init_db`` verifies connectivity with a ping and fails fast (``ConnectionError``)
if the server is unreachable, rather than letting requests hang later.

Connection ownership: ``init_db`` returns the client so each caller owns its
handle — the app lifespan stores it on ``app.state.mongo_client`` and closes that
specific client on shutdown. The module-level accessors below track the most
recent connection as a convenience for the single-app/test case. Note that
running two app instances against different databases in one process is bounded
by Beanie itself: ``init_beanie`` binds the Document classes to one database
process-wide, so there is effectively one active ODM connection per process.
"""

import logging
from urllib.parse import urlsplit, urlunsplit

from beanie import init_beanie
from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import PyMongoError

from .models import ALL_MODELS
from .settings import ApiSettings

logger = logging.getLogger(__name__)

_client: AsyncMongoClient | None = None
_db_name: str | None = None


def redact_mongodb_url(url: str) -> str:
    """Return ``url`` with any credentials and query string removed.

    Connection strings (e.g. Atlas ``mongodb+srv://user:password@host/?...``)
    must never reach logs or error messages verbatim.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return "<mongodb-url>"
    netloc = parts.netloc
    if "@" in netloc:
        netloc = "***@" + netloc.rsplit("@", 1)[1]
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


async def init_db(settings: ApiSettings) -> AsyncMongoClient:
    """Connect to MongoDB, verify with a ping, and initialize Beanie.

    Returns the connected client. Raises ``ConnectionError`` with an actionable
    message if the server cannot be reached (fail-fast).
    """
    global _client, _db_name

    client: AsyncMongoClient = AsyncMongoClient(
        settings.mongodb_url,
        minPoolSize=settings.mongodb_min_pool_size,
        maxPoolSize=settings.mongodb_max_pool_size,
        serverSelectionTimeoutMS=settings.mongodb_server_selection_timeout_ms,
    )

    safe_url = redact_mongodb_url(settings.mongodb_url)
    try:
        await client.admin.command("ping")
    except PyMongoError as exc:
        await client.close()
        raise ConnectionError(
            f"Could not connect to MongoDB at {safe_url}: {exc}. "
            "Verify the server is running and ACEMUSIC_API_MONGODB_URL is correct."
        ) from exc

    # If Beanie init fails after a good ping (e.g. invalid index/model, or the
    # user lacks index-creation rights), close the client so a failed startup
    # doesn't leak sockets/monitor tasks.
    try:
        await init_beanie(database=client[settings.mongodb_db_name], document_models=ALL_MODELS)
    except Exception:
        await client.close()
        raise

    _client = client
    _db_name = settings.mongodb_db_name
    logger.info("Connected to MongoDB database %r at %s", settings.mongodb_db_name, safe_url)
    return client


async def close_db(client: AsyncMongoClient | None = None) -> None:
    """Close a MongoDB client.

    Closes the given ``client`` (so a lifespan tears down exactly the connection
    it opened); when called with no argument, closes the module-level client.
    The module globals are cleared only when they refer to the closed client.
    """
    global _client, _db_name
    target = client if client is not None else _client
    if target is not None:
        await target.close()
        logger.info("Closed MongoDB connection")
    if client is None or client is _client:
        _client = None
        _db_name = None


def get_client() -> AsyncMongoClient:
    """Return the active client. Raises if the database is not initialized."""
    if _client is None:
        raise RuntimeError("Database not initialized — call init_db() first.")
    return _client


def get_database() -> AsyncDatabase:
    """Return the active database handle. Raises if not initialized."""
    client = get_client()
    if _db_name is None:
        raise RuntimeError("Database not initialized — call init_db() first.")
    return client[_db_name]
