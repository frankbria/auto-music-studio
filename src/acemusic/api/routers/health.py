"""Health check route (US-8.1).

Reports the API server's own liveness — distinct from the CLI ``health`` command,
which probes the upstream ACE-Step inference server.
"""

import os
import time

from fastapi import APIRouter, Request
from pydantic import BaseModel

from acemusic import __version__

router = APIRouter(tags=["health"])

#: Baked into the image at build time from the commit it was built from (#429). Read from
#: the environment rather than a generated file so a plain `docker run -e` can override it
#: and a dev checkout needs nothing.
BUILD_SHA_ENV = "ACEMUSIC_BUILD_SHA"


class HealthResponse(BaseModel):
    """Health payload — typed so it appears in the OpenAPI schema."""

    status: str
    version: str
    uptime_seconds: float
    #: The commit this process was built from, or "unknown" outside a built image.
    #: Distinct from ``version``, which is the static package version nobody bumps —
    #: this is what makes "did the deploy actually land?" answerable without trusting
    #: the workflow that claimed it did.
    build_sha: str = "unknown"


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    """Return server status, version, build commit, and uptime in seconds."""
    start_time = request.app.state.start_time
    return HealthResponse(
        status="ok",
        version=__version__,
        uptime_seconds=round(time.monotonic() - start_time, 3),
        build_sha=os.environ.get(BUILD_SHA_ENV) or "unknown",
    )
