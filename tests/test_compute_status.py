"""Tests for the compute status endpoint and aggregation service (US-11.4).

Pure-logic / no-DB: the local probe is mocked with respx, the remote probe by
monkeypatching ``RunPodClient.health_details``. The endpoint is auth-gated, so a
signed access token is minted directly (``get_current_user`` is token-only).
"""

import asyncio
import time

import httpx
import respx
from fastapi.testclient import TestClient

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import create_app
from acemusic.api.services import compute_status
from acemusic.api.services.compute_status import (
    ComputeStatusResponse,
    LocalComputeStatus,
    RemoteComputeStatus,
    get_compute_status,
    get_local_status,
    get_remote_status,
)
from acemusic.api.settings import ApiSettings

LOCAL_URL = "http://localhost:8001"
STATS_URL = f"{LOCAL_URL}/v1/stats"
JWT_SECRET = "test-secret-key-at-least-32-bytes-long-xx"


def _settings(**overrides) -> ApiSettings:
    base = {
        "_env_file": None,
        "jwt_secret_key": JWT_SECRET,
        "local_url": LOCAL_URL,
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


def _client(settings: ApiSettings) -> TestClient:
    # No `with`: TestClient skips lifespan (no DB / job processor) — the status
    # endpoint only reads settings off app state, like /health.
    return TestClient(create_app(settings))


def _auth(settings: ApiSettings) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(settings)}"}


# --------------------------------------------------------------------------- #
# Endpoint structure + auth
# --------------------------------------------------------------------------- #
class TestEndpointStructure:
    @respx.mock
    def test_returns_200_with_expected_top_level_keys(self):
        respx.get(STATS_URL).mock(return_value=httpx.Response(200, json={}))
        settings = _settings()
        resp = _client(settings).get("/api/v1/compute/status", headers=_auth(settings))
        assert resp.status_code == 200
        body = resp.json()
        assert set(body) >= {"local", "remote", "routing_preference"}
        assert body["routing_preference"] == "local_first"

    def test_requires_authentication(self):
        resp = _client(_settings()).get("/api/v1/compute/status")
        assert resp.status_code == 401

    def test_openapi_lists_typed_response_schema(self):
        client = _client(_settings())
        schema = client.get("/openapi.json").json()
        assert "/api/v1/compute/status" in schema["paths"]
        ref = schema["paths"]["/api/v1/compute/status"]["get"]["responses"]["200"]["content"]["application/json"][
            "schema"
        ]["$ref"]
        model_name = ref.rsplit("/", 1)[-1]
        props = schema["components"]["schemas"][model_name]["properties"]
        assert {"local", "remote", "routing_preference"} <= set(props)


# --------------------------------------------------------------------------- #
# Local status (AC1 / AC2)
# --------------------------------------------------------------------------- #
class TestLocalStatus:
    @respx.mock
    async def test_available_with_details_when_server_responds(self):
        respx.get(STATS_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "gpu": {"name": "NVIDIA A40", "vram_total_mb": 49140, "vram_used_mb": 8200},
                        "jobs": {"running": 2},
                        "models": [{"name": "ace-step-v1"}, {"name": "ace-step-turbo"}],
                    }
                },
            )
        )
        status = await get_local_status(LOCAL_URL, timeout=3.0)
        assert status.available is True
        assert status.gpu_name == "NVIDIA A40"
        assert status.vram_total_mb == 49140
        assert status.vram_used_mb == 8200
        assert status.active_jobs == 2
        assert status.loaded_models == ["ace-step-v1", "ace-step-turbo"]

    @respx.mock
    async def test_available_with_sparse_stats_leaves_detail_none(self):
        respx.get(STATS_URL).mock(return_value=httpx.Response(200, json={"data": {}}))
        status = await get_local_status(LOCAL_URL, timeout=3.0)
        assert status.available is True
        assert status.gpu_name is None
        assert status.vram_total_mb is None
        assert status.loaded_models is None

    @respx.mock
    async def test_flat_gpu_string_and_fields_are_parsed(self):
        respx.get(STATS_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "gpu": "RTX 4090",
                    "vram_total_mb": 24564,
                    "active_jobs": 1,
                    "models": ["base"],
                },
            )
        )
        status = await get_local_status(LOCAL_URL, timeout=3.0)
        assert status.available is True
        assert status.gpu_name == "RTX 4090"
        assert status.vram_total_mb == 24564
        assert status.active_jobs == 1
        assert status.loaded_models == ["base"]

    @respx.mock
    async def test_zero_valued_vram_is_preserved_not_dropped(self):
        # An idle GPU reports vram_used_mb: 0 — a valid zero, not "missing".
        respx.get(STATS_URL).mock(
            return_value=httpx.Response(
                200,
                json={"data": {"vram_total_mb": 24564, "vram_used_mb": 0, "jobs": {"running": 0}}},
            )
        )
        status = await get_local_status(LOCAL_URL, timeout=3.0)
        assert status.available is True
        assert status.vram_used_mb == 0
        assert status.vram_total_mb == 24564
        assert status.active_jobs == 0

    @respx.mock
    async def test_unavailable_on_connection_error(self):
        respx.get(STATS_URL).mock(side_effect=httpx.ConnectError("refused"))
        status = await get_local_status(LOCAL_URL, timeout=3.0)
        assert status.available is False
        assert status.gpu_name is None
        assert status.active_jobs is None

    @respx.mock
    async def test_unavailable_on_timeout(self):
        respx.get(STATS_URL).mock(side_effect=httpx.ReadTimeout("slow"))
        status = await get_local_status(LOCAL_URL, timeout=0.01)
        assert status.available is False

    @respx.mock
    async def test_non_2xx_is_unavailable(self):
        respx.get(STATS_URL).mock(return_value=httpx.Response(503))
        status = await get_local_status(LOCAL_URL, timeout=3.0)
        assert status.available is False


# --------------------------------------------------------------------------- #
# Remote status (AC3 / AC4)
# --------------------------------------------------------------------------- #
class TestRemoteStatus:
    async def test_unavailable_and_no_http_when_not_configured(self, monkeypatch):
        called = False

        def _boom(self, timeout=5.0):
            nonlocal called
            called = True
            return {}

        monkeypatch.setattr(compute_status.RunPodClient, "health_details", _boom)
        status = await get_remote_status(_settings(), timeout=3.0)
        assert status.available is False
        assert status.provider is None
        assert called is False

    async def test_available_with_worker_detail_when_reachable(self, monkeypatch):
        monkeypatch.setattr(
            compute_status.RunPodClient,
            "health_details",
            lambda self, timeout=5.0: {
                "workers": {"idle": 1, "running": 3, "ready": 2, "initializing": 0, "throttled": 0}
            },
        )
        settings = _settings(runpod_api_key="rp-key", runpod_endpoint_id="ep-1")
        status = await get_remote_status(settings, timeout=3.0)
        assert status.available is True
        assert status.provider == "runpod"
        assert status.endpoint_id == "ep-1"
        assert status.active_workers == 3
        assert status.scaling_status == "ready"

    async def test_initializing_workers_report_scaling(self, monkeypatch):
        monkeypatch.setattr(
            compute_status.RunPodClient,
            "health_details",
            lambda self, timeout=5.0: {"workers": {"initializing": 2, "running": 0}},
        )
        settings = _settings(runpod_api_key="rp-key", runpod_endpoint_id="ep-1")
        status = await get_remote_status(settings, timeout=3.0)
        assert status.available is True
        assert status.scaling_status == "initializing"

    async def test_throttled_then_idle_scaling_status(self, monkeypatch):
        settings = _settings(runpod_api_key="rp-key", runpod_endpoint_id="ep-1")

        monkeypatch.setattr(
            compute_status.RunPodClient,
            "health_details",
            lambda self, timeout=5.0: {"workers": {"throttled": 1, "running": 0, "ready": 0, "idle": 0}},
        )
        throttled = await get_remote_status(settings, timeout=3.0)
        assert throttled.scaling_status == "throttled"

        # No workers in any state → scaled to zero (serverless cold), still reachable.
        monkeypatch.setattr(compute_status.RunPodClient, "health_details", lambda self, timeout=5.0: {"workers": {}})
        idle = await get_remote_status(settings, timeout=3.0)
        assert idle.available is True
        assert idle.scaling_status == "idle"
        assert idle.active_workers is None
        assert idle.max_workers is None

    async def test_unreachable_keeps_provider_and_endpoint(self, monkeypatch):
        monkeypatch.setattr(compute_status.RunPodClient, "health_details", lambda self, timeout=5.0: None)
        settings = _settings(runpod_api_key="rp-key", runpod_endpoint_id="ep-1")
        status = await get_remote_status(settings, timeout=3.0)
        assert status.available is False
        assert status.provider == "runpod"
        assert status.endpoint_id == "ep-1"
        assert status.active_workers is None

    async def test_probe_error_is_unavailable_not_500(self, monkeypatch):
        def _raise(self, timeout=5.0):
            raise RuntimeError("boom")

        monkeypatch.setattr(compute_status.RunPodClient, "health_details", _raise)
        settings = _settings(runpod_api_key="rp-key", runpod_endpoint_id="ep-1")
        status = await get_remote_status(settings, timeout=3.0)
        assert status.available is False
        assert status.provider == "runpod"


# --------------------------------------------------------------------------- #
# Aggregation + timeout behaviour (AC5)
# --------------------------------------------------------------------------- #
class TestAggregation:
    async def test_combines_both_targets_and_preference(self, monkeypatch):
        async def _local(url, timeout):
            return LocalComputeStatus(available=True, gpu_name="A40")

        async def _remote(settings, timeout):
            return RemoteComputeStatus(available=False, provider=None)

        monkeypatch.setattr(compute_status, "get_local_status", _local)
        monkeypatch.setattr(compute_status, "get_remote_status", _remote)
        result = await get_compute_status(_settings(compute_preference="remote_first"))
        assert isinstance(result, ComputeStatusResponse)
        assert result.local.available is True
        assert result.remote.available is False
        assert result.routing_preference == "remote_first"

    async def test_probes_run_concurrently(self, monkeypatch):
        async def _slow_local(url, timeout):
            await asyncio.sleep(0.3)
            return LocalComputeStatus(available=False)

        async def _slow_remote(settings, timeout):
            await asyncio.sleep(0.3)
            return RemoteComputeStatus(available=False)

        monkeypatch.setattr(compute_status, "get_local_status", _slow_local)
        monkeypatch.setattr(compute_status, "get_remote_status", _slow_remote)
        start = time.monotonic()
        await get_compute_status(_settings())
        elapsed = time.monotonic() - start
        # Concurrent: ~0.3s, not ~0.6s if serialised.
        assert elapsed < 0.5

    @respx.mock
    async def test_responds_quickly_when_targets_unreachable(self):
        respx.get(STATS_URL).mock(side_effect=httpx.ConnectError("refused"))
        settings = _settings(runpod_api_key="rp-key", runpod_endpoint_id="ep-1")
        start = time.monotonic()
        result = await get_compute_status(settings)
        elapsed = time.monotonic() - start
        assert elapsed < 5.0
        assert result.local.available is False
        assert result.remote.available is False

    @respx.mock
    async def test_responds_quickly_when_runpod_configured_and_hanging(self, monkeypatch):
        # The 5s-ceiling guarantee is only fully exercised when RunPod IS configured
        # and its /health hangs: the bounded asyncio.wait_for must cut the probe off.
        respx.get(STATS_URL).mock(side_effect=httpx.ConnectError("refused"))

        def _hang(self, timeout=5.0):
            time.sleep(1.0)  # outlives the 0.2s probe budget below
            return {"workers": {"running": 1}}

        monkeypatch.setattr(compute_status.RunPodClient, "health_details", _hang)
        settings = _settings(runpod_api_key="rp-key", runpod_endpoint_id="ep-1", compute_status_timeout=0.2)
        start = time.monotonic()
        result = await get_compute_status(settings)
        elapsed = time.monotonic() - start
        # wait_for(0.2) cuts the hanging probe off well before its 1s sleep.
        assert elapsed < 1.0
        assert result.remote.available is False
        assert result.remote.provider == "runpod"
