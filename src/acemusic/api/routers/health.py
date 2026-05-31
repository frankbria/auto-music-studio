"""Health check route (US-8.1).

Reports the API server's own liveness — distinct from the CLI ``health`` command,
which probes the upstream ACE-Step inference server.
"""

import time

from fastapi import APIRouter, Request
from pydantic import BaseModel

from acemusic import __version__

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Health payload — typed so it appears in the OpenAPI schema."""

    status: str
    version: str
    uptime_seconds: float


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    """Return server status, version, and uptime in seconds."""
    start_time = request.app.state.start_time
    return HealthResponse(
        status="ok",
        version=__version__,
        uptime_seconds=round(time.monotonic() - start_time, 3),
    )
