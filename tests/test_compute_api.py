"""Tests for the remote RunPod Network Volume endpoint and service (US-11.5).

Pure-logic / no-DB: RunPod's management REST API is mocked with respx. The
endpoint is auth-gated (router-level ``get_current_user``), so a signed access
token is minted directly like the sibling ``test_compute_status`` suite.

RunPod's ``GET /v1/networkvolumes`` returns a bare JSON array of
``{"id", "name", "size", "dataCenterId"}`` objects (size in GB; no usage field
is exposed by the API).
"""

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import create_app
from acemusic.api.services.volume import (
    VolumeInfoResponse,
    VolumeNotConfiguredError,
    VolumeNotFoundError,
    VolumeUpstreamError,
    get_remote_volume,
)
from acemusic.api.settings import ApiSettings

JWT_SECRET = "test-secret-key-at-least-32-bytes-long-xx"
REST_BASE = "https://rest.runpod.io/v1"
VOLUMES_URL = f"{REST_BASE}/networkvolumes"
VOLUME_ENDPOINT = "/api/v1/compute/remote/volume"

# A representative RunPod network-volumes payload (the API returns a bare array).
SAMPLE_VOLUMES = [
    {"id": "vol-abc123", "name": "ace-step-models", "size": 100, "dataCenterId": "EU-RO-1"},
    {"id": "vol-other", "name": "scratch", "size": 20, "dataCenterId": "US-OR-1"},
]


def _settings(**overrides) -> ApiSettings:
    base = {
        "_env_file": None,
        "jwt_secret_key": JWT_SECRET,
        "runpod_api_key": "rp-key",
        "runpod_endpoint_id": "ep-1",
        "runpod_network_volume_id": "vol-abc123",
        "job_processor_enabled": False,
    }
    base.update(overrides)
    return ApiSettings(**base)


def _token(settings: ApiSettings) -> str:
    return create_access_token(
        user_id="507f1f77bcf86cd799439011",
        email="user@example.com",
        subscription_tier="free",
        settings=settings,
    )


def _auth(settings: ApiSettings) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(settings)}"}


def _client(settings: ApiSettings) -> TestClient:
    # No `with`: the endpoint only reads settings off app state (like /health and
    # /compute/status), so TestClient can skip the DB/job-processor lifespan.
    return TestClient(create_app(settings))


class TestGetRemoteVolumeService:
    """Direct unit tests of the transport-agnostic service function."""

    async def test_raises_when_api_key_missing(self):
        with pytest.raises(VolumeNotConfiguredError):
            await get_remote_volume(_settings(runpod_api_key=None))

    async def test_raises_when_volume_id_missing(self):
        with pytest.raises(VolumeNotConfiguredError):
            await get_remote_volume(_settings(runpod_network_volume_id=None))

    @respx.mock
    async def test_returns_mapped_volume_when_found(self):
        respx.get(VOLUMES_URL).mock(return_value=httpx.Response(200, json=SAMPLE_VOLUMES))
        result = await get_remote_volume(_settings())
        assert isinstance(result, VolumeInfoResponse)
        assert result.id == "vol-abc123"
        assert result.name == "ace-step-models"
        assert result.size_gb == 100
        assert result.region == "EU-RO-1"
        assert result.available is True
        # The REST API does not report usage, so used_gb stays None.
        assert result.used_gb is None

    @respx.mock
    async def test_sends_bearer_auth(self):
        route = respx.get(VOLUMES_URL).mock(return_value=httpx.Response(200, json=SAMPLE_VOLUMES))
        await get_remote_volume(_settings())
        assert route.calls.last.request.headers["Authorization"] == "Bearer rp-key"

    @respx.mock
    async def test_raises_not_found_when_id_absent(self):
        respx.get(VOLUMES_URL).mock(return_value=httpx.Response(200, json=[SAMPLE_VOLUMES[1]]))
        with pytest.raises(VolumeNotFoundError):
            await get_remote_volume(_settings())

    @respx.mock
    async def test_raises_upstream_on_5xx(self):
        respx.get(VOLUMES_URL).mock(return_value=httpx.Response(500, text="boom"))
        with pytest.raises(VolumeUpstreamError):
            await get_remote_volume(_settings())

    @respx.mock
    async def test_raises_upstream_on_connection_error(self):
        respx.get(VOLUMES_URL).mock(side_effect=httpx.ConnectError("down"))
        with pytest.raises(VolumeUpstreamError):
            await get_remote_volume(_settings())

    @respx.mock
    async def test_uses_configured_rest_base_url(self):
        staging = "https://staging.runpod.io/v1"
        route = respx.get(f"{staging}/networkvolumes").mock(return_value=httpx.Response(200, json=SAMPLE_VOLUMES))
        await get_remote_volume(_settings(runpod_rest_base_url=staging))
        assert route.called

    @respx.mock
    async def test_tolerates_dict_wrapped_volume_list(self):
        # Defensive: if RunPod ever wraps the array in a pagination envelope, the
        # configured volume is still found rather than silently 404ing.
        respx.get(VOLUMES_URL).mock(return_value=httpx.Response(200, json={"networkVolumes": SAMPLE_VOLUMES}))
        result = await get_remote_volume(_settings())
        assert result.id == "vol-abc123"


class TestVolumeEndpoint:
    """End-to-end through the auth-gated compute router."""

    def test_requires_auth(self):
        settings = _settings()
        resp = _client(settings).get(VOLUME_ENDPOINT)
        assert resp.status_code == 401

    def test_503_when_not_configured(self):
        # No volume id configured → the deployment never ran the setup script.
        settings = _settings(runpod_network_volume_id=None)
        resp = _client(settings).get(VOLUME_ENDPOINT, headers=_auth(settings))
        assert resp.status_code == 503

    @respx.mock
    def test_200_with_volume_info(self):
        respx.get(VOLUMES_URL).mock(return_value=httpx.Response(200, json=SAMPLE_VOLUMES))
        settings = _settings()
        resp = _client(settings).get(VOLUME_ENDPOINT, headers=_auth(settings))
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == "vol-abc123"
        assert body["name"] == "ace-step-models"
        assert body["size_gb"] == 100
        assert body["region"] == "EU-RO-1"
        assert body["available"] is True

    @respx.mock
    def test_404_when_volume_absent(self):
        respx.get(VOLUMES_URL).mock(return_value=httpx.Response(200, json=[SAMPLE_VOLUMES[1]]))
        settings = _settings()
        resp = _client(settings).get(VOLUME_ENDPOINT, headers=_auth(settings))
        assert resp.status_code == 404

    @respx.mock
    def test_502_when_runpod_unreachable(self):
        respx.get(VOLUMES_URL).mock(return_value=httpx.Response(500, text="boom"))
        settings = _settings()
        resp = _client(settings).get(VOLUME_ENDPOINT, headers=_auth(settings))
        assert resp.status_code == 502
