"""FastAPI application factory and ASGI entrypoint (US-8.1).

Run for development with::

    uv run uvicorn acemusic.api.main:app --reload

Routes are versioned under ``/api/v1``. OpenAPI docs are served at ``/docs``
(Swagger UI) and ``/redoc``.
"""

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from acemusic import __version__
from acemusic.runpod_client import RunPodClient

from . import database
from .exceptions import HandleConflictError
from .routers import (
    auth,
    batch,
    clips,
    compute,
    editing,
    extraction,
    generation,
    health,
    iterative,
    jobs,
    mastering,
    presets,
    users,
    workspaces,
)
from .settings import ApiSettings
from .tasks.processor import JobProcessor

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
        # Start the background job processor (US-9.2) once the DB is up. It polls
        # for queued jobs and runs them in-process; disable it (or run a
        # processor-less API) via ACEMUSIC_API_JOB_PROCESSOR_ENABLED=false. The
        # try/finally wraps processor start too, so a start() failure still closes
        # the DB client rather than leaking it.
        processor: JobProcessor | None = None
        try:
            if settings.job_processor_enabled:
                # Wire the RunPod backend (US-11.2) only when configured, so a
                # local-only deployment runs unchanged; routing already reports
                # remote unavailable when runpod_enabled is False.
                runpod_factory = None
                if settings.runpod_enabled:
                    runpod_factory = lambda: RunPodClient(  # noqa: E731 - small closure over settings
                        endpoint_id=settings.runpod_endpoint_id,
                        api_key=settings.runpod_api_key,
                        base_url=settings.runpod_base_url,
                    )
                processor = JobProcessor(
                    concurrency=settings.job_concurrency,
                    poll_interval=settings.job_poll_interval,
                    poll_timeout=settings.job_poll_timeout,
                    runpod_client_factory=runpod_factory,
                    runpod_timeout=settings.runpod_timeout,
                    runpod_poll_interval=settings.runpod_poll_interval,
                )
                await processor.start()
            app_.state.job_processor = processor
            yield
        finally:
            if processor is not None:
                await processor.stop()
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

    # Public routers: health is a liveness probe and auth is the login surface,
    # so neither is gated. Every FUTURE router that exposes user data (workspaces,
    # clips, jobs, …) MUST protect itself with
    # ``APIRouter(..., dependencies=[Depends(get_current_user)])`` (see
    # acemusic.api.auth.dependencies) so all /api/v1 routes except health and auth
    # require a valid Bearer access token.
    app.include_router(health.router, prefix=API_V1_PREFIX)
    app.include_router(auth.router, prefix=API_V1_PREFIX)
    app.include_router(users.router, prefix=API_V1_PREFIX)
    app.include_router(generation.router, prefix=API_V1_PREFIX)
    app.include_router(jobs.router, prefix=API_V1_PREFIX)
    app.include_router(clips.router, prefix=API_V1_PREFIX)
    app.include_router(editing.router, prefix=API_V1_PREFIX)
    app.include_router(extraction.router, prefix=API_V1_PREFIX)
    app.include_router(iterative.router, prefix=API_V1_PREFIX)
    app.include_router(batch.router, prefix=API_V1_PREFIX)
    app.include_router(workspaces.router, prefix=API_V1_PREFIX)
    app.include_router(presets.router, prefix=API_V1_PREFIX)
    app.include_router(compute.router, prefix=API_V1_PREFIX)
    app.include_router(mastering.router, prefix=API_V1_PREFIX)

    # A handle collision surfaces from the service layer as a domain exception;
    # translate it to 409 Conflict here so the router stays free of HTTP plumbing.
    @app.exception_handler(HandleConflictError)
    async def _handle_conflict(_request: Request, _exc: HandleConflictError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": "Handle already taken"})

    return app


app = create_app()
