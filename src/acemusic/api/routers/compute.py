"""Compute status endpoint (US-11.4).

Exposes ``GET /api/v1/compute/status`` so a client can check, before generating,
whether the local GPU is busy and whether the remote RunPod endpoint is available.
Auth-gated like the rest of the API (only ``/health`` and ``/auth`` are public):
worker counts and the RunPod endpoint id are operational detail for signed-in users.
"""

from fastapi import APIRouter, Depends

from ..auth.dependencies import get_current_user, get_settings
from ..services.compute_status import ComputeStatusResponse, get_compute_status
from ..settings import ApiSettings

router = APIRouter(tags=["compute"], dependencies=[Depends(get_current_user)])


@router.get("/compute/status", response_model=ComputeStatusResponse)
async def compute_status(settings: ApiSettings = Depends(get_settings)) -> ComputeStatusResponse:
    """Return combined local + remote compute status (both probed in parallel)."""
    return await get_compute_status(settings)
