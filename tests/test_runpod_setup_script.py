"""Tests for the standalone RunPod Network Volume setup script (US-11.5).

The script lives at ``scripts/runpod-setup.py`` (outside the ``acemusic`` package,
and the hyphen makes it non-importable by name), so it is loaded here via
``importlib`` from its file path. RunPod's management REST API is mocked with
respx — no real RunPod account, pod, or GPU is ever touched.
"""

import importlib.util
from pathlib import Path

import httpx
import pytest
import respx

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "runpod-setup.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("runpod_setup", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rp = _load_script()

REST_BASE = "https://rest.runpod.io/v1"
VOLUMES_URL = f"{REST_BASE}/networkvolumes"
PODS_URL = f"{REST_BASE}/pods"

EXISTING_VOLUMES = [
    {"id": "vol-existing", "name": "ace-step-models", "size": 100, "dataCenterId": "EU-RO-1"},
]


def _client() -> "rp.RunPodRestClient":
    return rp.RunPodRestClient(api_key="rp-key", base_url=REST_BASE)


class TestCostEstimate:
    def test_scales_with_size(self):
        small = rp.estimate_storage_cost_usd_per_month(50)
        large = rp.estimate_storage_cost_usd_per_month(100)
        assert large > small > 0
        # Linear in size at the published per-GB rate.
        assert large == pytest.approx(small * 2)


class TestEnsureVolumeIdempotency:
    @respx.mock
    def test_reuses_existing_volume_without_creating(self):
        list_route = respx.get(VOLUMES_URL).mock(return_value=httpx.Response(200, json=EXISTING_VOLUMES))
        create_route = respx.post(VOLUMES_URL).mock(return_value=httpx.Response(200, json={}))

        volume, created = rp.ensure_volume(
            _client(), name="ace-step-models", size_gb=100, data_center_id="EU-RO-1"
        )

        assert created is False
        assert volume["id"] == "vol-existing"
        assert list_route.called
        # Idempotency: re-running must NOT POST a duplicate volume.
        assert not create_route.called

    @respx.mock
    def test_creates_volume_when_absent(self):
        respx.get(VOLUMES_URL).mock(return_value=httpx.Response(200, json=[]))
        created_volume = {"id": "vol-new", "name": "ace-step-models", "size": 100, "dataCenterId": "EU-RO-1"}
        create_route = respx.post(VOLUMES_URL).mock(return_value=httpx.Response(200, json=created_volume))

        volume, created = rp.ensure_volume(
            _client(), name="ace-step-models", size_gb=100, data_center_id="EU-RO-1"
        )

        assert created is True
        assert volume["id"] == "vol-new"
        assert create_route.called
        sent = create_route.calls.last.request
        assert sent.headers["Authorization"] == "Bearer rp-key"
        import json

        body = json.loads(sent.content)
        assert body == {"name": "ace-step-models", "size": 100, "dataCenterId": "EU-RO-1"}


class TestPodPayload:
    def test_includes_volume_image_and_download_command(self):
        payload = rp.build_download_pod_payload(
            volume_id="vol-1",
            image="frankbria/ace-step:latest",
            gpu_type="NVIDIA GeForce RTX 4090",
            download_cmd=["bash", "-lc", "echo hi"],
            name="ace-step-weights-download",
        )
        assert payload["networkVolumeId"] == "vol-1"
        assert payload["imageName"] == "frankbria/ace-step:latest"
        assert payload["gpuTypeIds"] == ["NVIDIA GeForce RTX 4090"]
        assert payload["dockerStartCmd"] == ["bash", "-lc", "echo hi"]
        # Volume must mount where the image expects model weights (HF_HOME lives here).
        assert payload["volumeMountPath"] == "/workspace"


class TestPodFinishedDetection:
    @pytest.mark.parametrize("status", ["EXITED", "TERMINATED", "STOPPED"])
    def test_terminal_statuses_are_finished(self, status):
        assert rp.pod_is_finished({"desiredStatus": status}) is True

    @pytest.mark.parametrize("status", ["RUNNING", "CREATED", "PENDING"])
    def test_non_terminal_statuses_are_not_finished(self, status):
        assert rp.pod_is_finished({"desiredStatus": status}) is False


class TestDryRun:
    @respx.mock
    def test_dry_run_makes_no_api_calls_and_does_not_prompt(self, capsys, monkeypatch):
        # Any prompt or network call in dry-run is a bug; make them fail loudly.
        monkeypatch.setattr("builtins.input", lambda *a, **k: pytest.fail("dry-run must not prompt"))
        list_route = respx.get(VOLUMES_URL).mock(return_value=httpx.Response(200, json=EXISTING_VOLUMES))
        create_route = respx.post(VOLUMES_URL).mock(return_value=httpx.Response(200, json={}))
        pod_route = respx.post(PODS_URL).mock(return_value=httpx.Response(200, json={}))

        rc = rp.run_setup(
            _client(),
            volume_name="ace-step-models",
            size_gb=100,
            region="EU-RO-1",
            image="frankbria/ace-step:latest",
            gpu_type="NVIDIA GeForce RTX 4090",
            download_cmd=["bash", "-lc", "echo hi"],
            timeout=60.0,
            poll_interval=5.0,
            dry_run=True,
            assume_yes=True,
        )

        assert rc == 0
        assert not list_route.called
        assert not create_route.called
        assert not pod_route.called
        out = capsys.readouterr().out
        # The cost estimate is shown before any resource creation.
        assert "cost" in out.lower()


class TestFullLifecycle:
    @respx.mock
    def test_provisions_volume_then_terminates_pod_without_deleting_volume(self, capsys):
        # Volume absent → created; pod runs then exits; pod is stopped+terminated.
        respx.get(VOLUMES_URL).mock(return_value=httpx.Response(200, json=[]))
        respx.post(VOLUMES_URL).mock(
            return_value=httpx.Response(200, json={"id": "vol-new", "name": "ace-step-models"})
        )
        respx.post(PODS_URL).mock(return_value=httpx.Response(200, json={"id": "pod-1"}))
        get_pod_route = respx.get(f"{PODS_URL}/pod-1").mock(
            return_value=httpx.Response(200, json={"desiredStatus": "EXITED"})
        )
        stop_route = respx.post(f"{PODS_URL}/pod-1/stop").mock(return_value=httpx.Response(200))
        terminate_route = respx.delete(f"{PODS_URL}/pod-1").mock(return_value=httpx.Response(200))
        # A volume-DELETE would violate "volume persists after the pod stops".
        volume_delete = respx.delete(f"{VOLUMES_URL}/vol-new").mock(return_value=httpx.Response(200))

        rc = rp.run_setup(
            _client(),
            volume_name="ace-step-models",
            size_gb=100,
            region="EU-RO-1",
            image="frankbria/ace-step:latest",
            gpu_type="NVIDIA GeForce RTX 4090",
            download_cmd=["bash", "-lc", "echo hi"],
            timeout=60.0,
            poll_interval=0.0,
            dry_run=False,
            assume_yes=True,
        )

        assert rc == 0
        assert get_pod_route.called
        assert stop_route.called
        assert terminate_route.called
        # AC2: the volume is never deleted.
        assert not volume_delete.called
        out = capsys.readouterr().out
        assert "ACEMUSIC_API_RUNPOD_NETWORK_VOLUME_ID=vol-new" in out

    @respx.mock
    def test_timeout_terminates_pod_and_fails(self):
        respx.get(VOLUMES_URL).mock(return_value=httpx.Response(200, json=EXISTING_VOLUMES))
        respx.post(PODS_URL).mock(return_value=httpx.Response(200, json={"id": "pod-1"}))
        # Pod never reaches a terminal status → wait times out.
        respx.get(f"{PODS_URL}/pod-1").mock(return_value=httpx.Response(200, json={"desiredStatus": "RUNNING"}))
        stop_route = respx.post(f"{PODS_URL}/pod-1/stop").mock(return_value=httpx.Response(200))
        terminate_route = respx.delete(f"{PODS_URL}/pod-1").mock(return_value=httpx.Response(200))

        rc = rp.run_setup(
            _client(),
            volume_name="ace-step-models",
            size_gb=100,
            region="EU-RO-1",
            image="frankbria/ace-step:latest",
            gpu_type="NVIDIA GeForce RTX 4090",
            download_cmd=["bash", "-lc", "echo hi"],
            timeout=0.0,  # immediate timeout
            poll_interval=0.0,
            dry_run=False,
            assume_yes=True,
        )

        assert rc == 1
        # Even on timeout the temporary pod is cleaned up.
        assert stop_route.called
        assert terminate_route.called


class TestCliParsing:
    def test_defaults(self):
        args = rp.parse_args([])
        assert args.size == 100
        assert args.volume_name == "ace-step-models"
        assert args.dry_run is False

    def test_overrides(self):
        args = rp.parse_args(["--size", "250", "--region", "US-OR-1", "--volume-name", "weights", "--dry-run"])
        assert args.size == 250
        assert args.region == "US-OR-1"
        assert args.volume_name == "weights"
        assert args.dry_run is True
