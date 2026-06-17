"""Compute status + remote volume endpoints (US-11.4, US-11.5).

``GET /api/v1/compute/status`` lets a client check, before generating, whether the
local GPU is busy and whether the remote RunPod endpoint is available.
``GET /api/v1/compute/remote/volume`` reports the persisted RunPod Network Volume
that holds the model weights (provisioned by ``scripts/runpod-setup.py``).

Both are auth-gated like the rest of the API (only ``/health`` and ``/auth`` are
public): worker counts, the RunPod endpoint id, and volume metadata are
operational detail for signed-in users.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from ..auth.dependencies import get_current_user, get_settings
from ..services.compute_status import ComputeStatusResponse, get_compute_status
from ..services.volume import (
    VolumeInfoResponse,
    VolumeNotConfiguredError,
    VolumeNotFoundError,
    VolumeUpstreamError,
    get_remote_volume,
)
from ..settings import ApiSettings

router = APIRouter(tags=["compute"], dependencies=[Depends(get_current_user)])


@router.get("/compute/status", response_model=ComputeStatusResponse)
async def compute_status(settings: ApiSettings = Depends(get_settings)) -> ComputeStatusResponse:
    """Return combined local + remote compute status (both probed in parallel)."""
    return await get_compute_status(settings)


@router.get("/compute/remote/volume", response_model=VolumeInfoResponse)
async def remote_volume(settings: ApiSettings = Depends(get_settings)) -> VolumeInfoResponse:
    """Return the configured RunPod Network Volume's metadata.

    503 when RunPod / the volume id is not configured, 404 when the configured
    volume is absent from RunPod, 502 when RunPod's API is unreachable.
    """
    try:
        return await get_remote_volume(settings)
    except VolumeNotConfiguredError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except VolumeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except VolumeUpstreamError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
