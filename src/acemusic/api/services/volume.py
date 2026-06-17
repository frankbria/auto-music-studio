"""Remote RunPod Network Volume info (US-11.5).

Backs ``GET /api/v1/compute/remote/volume``: looks up the configured persisted
weights volume via RunPod's *management* REST API (``rest.runpod.io/v1``) — a
different host from the serverless API the routing/status code talks to. The
volume is provisioned once by ``scripts/runpod-setup.py`` and mounted by every
serverless worker, so this endpoint lets an operator confirm it exists and
inspect its size/region before relying on remote generation.

Kept transport-agnostic like the sibling ``compute_status`` module: it returns a
model on success and raises typed domain errors otherwise, so the router stays
thin and owns the HTTP-status mapping (503 unconfigured / 404 missing / 502
upstream failure).

RunPod's ``GET /v1/networkvolumes`` returns a bare JSON array of
``{"id", "name", "size", "dataCenterId"}`` objects (``size`` in GB). The API does
not expose live usage, so ``used_gb`` is always ``None`` for now.
"""

import httpx
from pydantic import BaseModel

from ..settings import ApiSettings

NETWORK_VOLUMES_PATH = "/networkvolumes"

# A volume listing is a quick management call; bound it so a hung RunPod API
# surfaces as a 502 rather than holding the request open. Separate from the
# status endpoint's probe budget — this is a resource fetch, not a health probe.
VOLUME_REQUEST_TIMEOUT = 10.0


class VolumeInfoResponse(BaseModel):
    """Metadata for the configured RunPod Network Volume.

    ``used_gb`` is optional because RunPod's REST API reports allocated ``size``
    but not live usage; it stays ``None`` until/unless the API exposes it.
    """

    id: str
    name: str
    size_gb: int
    used_gb: int | None = None
    region: str
    available: bool


class VolumeNotConfiguredError(Exception):
    """RunPod credentials or the network volume id are not configured (→ 503)."""


class VolumeNotFoundError(Exception):
    """The configured volume id was not returned by RunPod's API (→ 404)."""


class VolumeUpstreamError(Exception):
    """RunPod's API was unreachable or returned an error response (→ 502)."""


def _extract_volumes(payload: object) -> list[dict]:
    """Return the list of volume objects from a (defensively-typed) response body.

    The documented shape is a bare array; tolerate a dict wrapper under common
    keys so a future pagination envelope does not silently break the lookup.
    """
    if isinstance(payload, list):
        return [v for v in payload if isinstance(v, dict)]
    if isinstance(payload, dict):
        for key in ("networkVolumes", "data", "volumes"):
            value = payload.get(key)
            if isinstance(value, list):
                return [v for v in value if isinstance(v, dict)]
    return []


async def get_remote_volume(settings: ApiSettings) -> VolumeInfoResponse:
    """Fetch the configured Network Volume's metadata from RunPod.

    Raises :class:`VolumeNotConfiguredError` when the API key or volume id is
    unset (no HTTP call is made), :class:`VolumeUpstreamError` when RunPod is
    unreachable or returns a non-2xx, and :class:`VolumeNotFoundError` when the
    configured id is absent from the returned list.
    """
    api_key = settings.runpod_api_key
    volume_id = settings.runpod_network_volume_id
    if not api_key or not volume_id:
        raise VolumeNotConfiguredError(
            "RunPod is not configured: set ACEMUSIC_API_RUNPOD_API_KEY and "
            "ACEMUSIC_API_RUNPOD_NETWORK_VOLUME_ID (run scripts/runpod-setup.py)."
        )

    url = f"{settings.runpod_rest_base_url.rstrip('/')}{NETWORK_VOLUMES_PATH}"
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        async with httpx.AsyncClient(timeout=VOLUME_REQUEST_TIMEOUT) as client:
            response = await client.get(url, headers=headers)
        response.raise_for_status()
        volumes = _extract_volumes(response.json())
    except (httpx.HTTPError, ValueError) as exc:
        raise VolumeUpstreamError(f"RunPod volume lookup failed: {exc}") from exc

    volume = next((v for v in volumes if v.get("id") == volume_id), None)
    if volume is None:
        raise VolumeNotFoundError(f"Network volume {volume_id!r} not found on RunPod.")

    return VolumeInfoResponse(
        id=str(volume.get("id")),
        name=str(volume.get("name", "")),
        size_gb=int(volume.get("size", 0)),
        used_gb=None,
        region=str(volume.get("dataCenterId", "")),
        available=True,
    )
