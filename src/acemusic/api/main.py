"""FastAPI application factory and ASGI entrypoint (US-8.1).

Run for development with::

    uv run uvicorn acemusic.api.main:app --reload

Routes are versioned under ``/api/v1``. OpenAPI docs are served at ``/docs``
(Swagger UI) and ``/redoc``.
"""

import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from acemusic import __version__

from .routers import health
from .settings import ApiSettings

API_V1_PREFIX = "/api/v1"


def create_app(settings: ApiSettings | None = None) -> FastAPI:
    """Build and configure the FastAPI application.

    Accepts an optional ``settings`` instance for testing; defaults to
    environment-derived :class:`ApiSettings`.
    """
    settings = settings or ApiSettings()

    app = FastAPI(
        title="Auto Music Studio API",
        version=__version__,
        docs_url="/docs",
        redoc_url="/redoc",
    )
    app.state.settings = settings
    app.state.start_time = time.monotonic()

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
