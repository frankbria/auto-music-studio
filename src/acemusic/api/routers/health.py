"""Health check route (US-8.1).

Reports the API server's own liveness — distinct from the CLI ``health`` command,
which probes the upstream ACE-Step inference server.
"""

import time

from fastapi import APIRouter, Request

from acemusic import __version__

router = APIRouter(tags=["health"])


@router.get("/health")
def health(request: Request) -> dict:
    """Return server status, version, and uptime in seconds."""
    start_time = request.app.state.start_time
    return {
        "status": "ok",
        "version": __version__,
        "uptime_seconds": round(time.monotonic() - start_time, 3),
    }
