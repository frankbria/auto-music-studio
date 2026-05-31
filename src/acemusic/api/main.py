"""FastAPI application factory and ASGI entrypoint (US-8.1).

Run for development with::

    uv run uvicorn acemusic.api.main:app --reload

Routes are versioned under ``/api/v1``. OpenAPI docs are served at ``/docs``
(Swagger UI) and ``/redoc``.
"""

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from acemusic import __version__

from . import database
from .routers import health
from .settings import ApiSettings

API_V1_PREFIX = "/api/v1"


def _ensure_app_logging() -> None:
    """Make ``acemusic`` INFO logs visible when served (e.g. via uvicorn).

    uvicorn configures only its own loggers, so application logs (the MongoDB
    connection success/failure) would otherwise be silent. Attach a stream
    handler to the ``acemusic`` logger once, without touching the root logger.
    """
    app_logger = logging.getLogger("acemusic")
    if not app_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s - %(message)s"))
        app_logger.addHandler(handler)
        app_logger.setLevel(logging.INFO)
        app_logger.propagate = False


def create_app(settings: ApiSettings | None = None) -> FastAPI:
    """Build and configure the FastAPI application.

    Accepts an optional ``settings`` instance for testing; defaults to
    environment-derived :class:`ApiSettings`.

    The app connects to MongoDB on startup (and closes on shutdown) via the
    lifespan handler. A failed connection aborts startup (fail-fast). Note that
    Starlette only runs the lifespan when the app is actually served (uvicorn) or
    when a test uses ``TestClient`` as a context manager — plain ``TestClient``
    instantiation does not, so HTTP-surface unit tests need no live database.
    """
    settings = settings or ApiSettings()
    _ensure_app_logging()

    @asynccontextmanager
    async def lifespan(app_: FastAPI):
        client = await database.init_db(settings)
        app_.state.mongo_client = client
        try:
            yield
        finally:
            await database.close_db(client)

    app = FastAPI(
        title="Auto Music Studio API",
        version=__version__,
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.start_time = time.monotonic()

    # allow_credentials=True is incompatible with a wildcard allow_origins=["*"]
    # (browsers reject the combination). _split_origins in settings.py never
    # produces "*", so explicit origins are always used here.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router, prefix=API_V1_PREFIX)

    return app


app = create_app()
