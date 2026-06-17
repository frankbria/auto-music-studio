#!/usr/bin/env python3
"""One-time RunPod Network Volume setup for ACE-Step-1.5 model weights (US-11.5).

WHAT THIS DOES
==============
The platform's serverless workers (US-11.2/11.3) keep model weights *off* the
Docker image and load them at runtime from a shared RunPod Network Volume mounted
at ``/workspace`` (``HF_HOME=/workspace/models/.cache`` — see ``docker/Dockerfile``
and ``model-deployment.md`` §5.3). This script provisions that volume once and
populates it with weights so every future worker downloads nothing on cold start:

  1. Find-or-create the Network Volume (idempotent — safe to re-run).
  2. Spin up a *temporary* GPU pod from the US-11.3 image with the volume mounted,
     running a one-shot command that downloads the ACE-Step-1.5 weights into the
     volume, then exits.
  3. Poll the pod until that command finishes, then stop and terminate the pod.
  4. Print the volume id to configure as ``ACEMUSIC_API_RUNPOD_NETWORK_VOLUME_ID``.

The volume PERSISTS after the temporary pod is gone (that is the whole point); the
script never deletes a volume. Re-running it detects the existing volume by name
and reuses it instead of creating a duplicate.

PREREQUISITES
=============
- A RunPod account and API key, exported as ``RUNPOD_API_KEY`` in the environment.
  (This is the Layer-1 / ops credential, read directly here — the API layer's
  ``ACEMUSIC_API_RUNPOD_*`` settings are separate.)
- The US-11.3 worker image published and pullable (default
  ``frankbria/ace-step:latest``; override with ``--image``).

USAGE
=====
    export RUNPOD_API_KEY=...                      # required
    python scripts/runpod-setup.py --dry-run       # preview cost + plan, no changes
    python scripts/runpod-setup.py                 # provision (prompts to confirm)
    python scripts/runpod-setup.py --region US-OR-1 --size 150 --yes

After a successful run the script prints the volume id; set it in your API
environment:

    ACEMUSIC_API_RUNPOD_NETWORK_VOLUME_ID=<printed id>

and verify it via ``GET /api/v1/compute/remote/volume``.

NOTE ON THE WEIGHT-DOWNLOAD COMMAND
===================================
The default ``--download-cmd`` warms the Hugging Face cache on the volume by
starting the ACE-Step API server (which downloads weights into ``HF_HOME`` on
first load) and exiting once it reports healthy. Depending on how the published
image fetches weights you may need to override ``--download-cmd`` with the exact
download invocation for your image. The live download requires a paid GPU pod and
cannot be exercised in CI; ``--dry-run`` prints the full plan without spending.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import httpx

DEFAULT_REST_BASE_URL = "https://rest.runpod.io/v1"
DEFAULT_IMAGE = "frankbria/ace-step:latest"
DEFAULT_VOLUME_NAME = "ace-step-models"
DEFAULT_REGION = "EU-RO-1"
DEFAULT_SIZE_GB = 100
DEFAULT_GPU_TYPE = "NVIDIA GeForce RTX 4090"
# Where the image expects the weights volume (HF_HOME lives under here).
VOLUME_MOUNT_PATH = "/workspace"
# Container scratch disk for the temporary download pod (weights land on the
# volume, not here, so this only needs to fit the image + runtime).
CONTAINER_DISK_GB = 50

# Approximate RunPod network-volume storage rate (USD per GB per month). Published
# pricing changes; this is a planning estimate shown before any spend, not a quote.
# Last verified: 2026-06-16.
STORAGE_RATE_USD_PER_GB_MONTH = 0.07

# Pod statuses that mean the one-shot download command has finished.
_TERMINAL_POD_STATUSES = {"EXITED", "TERMINATED", "STOPPED"}

# Default one-shot download: start the ACE-Step API (which pulls weights into
# HF_HOME on the mounted volume), wait until it is healthy, then exit so the pod
# stops. Override with --download-cmd if your image downloads weights differently.
#
# Crucially, this FAILS LOUDLY: if the server never becomes healthy (bad image,
# crash, OOM, or a failed weight download) the loop falls through with ``ready=0``
# and the script exits non-zero *without* printing the success marker — so a pod
# that never populated the volume is not mistaken for a successful run.
_DEFAULT_DOWNLOAD_SCRIPT = (
    "set -e; "
    "export HF_HOME=/workspace/models/.cache; "
    'mkdir -p "$HF_HOME"; '
    "cd /app/ACE-Step-1.5; "
    "uv run acestep-api & SERVER_PID=$!; "
    "ready=0; "
    "for i in $(seq 1 180); do "
    "if curl -sf http://localhost:8001/v1/stats; then ready=1; break; fi; "
    "sleep 10; "
    "done; "
    'kill "$SERVER_PID" 2>/dev/null || true; '
    'if [ "$ready" -ne 1 ]; then echo "ACE_STEP_WEIGHTS_FAILED: server never became healthy" >&2; exit 1; fi; '
    "echo ACE_STEP_WEIGHTS_READY"
)
DEFAULT_DOWNLOAD_CMD = ["bash", "-lc", _DEFAULT_DOWNLOAD_SCRIPT]


class RunPodRestError(RuntimeError):
    """A RunPod management REST API call failed (transport error or non-2xx)."""


class RunPodRestClient:
    """Thin synchronous wrapper over RunPod's management REST API.

    Uses ``httpx`` (the platform's HTTP client) with Bearer auth, mirroring
    ``acemusic.runpod_client.RunPodClient`` rather than pulling in the RunPod SDK.
    """

    def __init__(self, api_key: str, base_url: str = DEFAULT_REST_BASE_URL, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._timeout = timeout

    def _request(self, method: str, path: str, json_body: dict | None = None) -> object:
        url = f"{self.base_url}{path}"
        try:
            response = httpx.request(method, url, headers=self._headers, json=json_body, timeout=self._timeout)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RunPodRestError(f"RunPod API {method} {path} failed: {exc}") from exc
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise RunPodRestError(f"RunPod API {method} {path} returned non-JSON body") from exc

    def list_network_volumes(self) -> list[dict]:
        payload = self._request("GET", "/networkvolumes")
        if isinstance(payload, list):
            return [v for v in payload if isinstance(v, dict)]
        if isinstance(payload, dict):
            for key in ("networkVolumes", "data", "volumes"):
                value = payload.get(key)
                if isinstance(value, list):
                    return [v for v in value if isinstance(v, dict)]
        return []

    def create_network_volume(self, name: str, size_gb: int, data_center_id: str) -> dict:
        result = self._request(
            "POST", "/networkvolumes", json_body={"name": name, "size": size_gb, "dataCenterId": data_center_id}
        )
        return result if isinstance(result, dict) else {}

    def create_pod(self, payload: dict) -> dict:
        result = self._request("POST", "/pods", json_body=payload)
        return result if isinstance(result, dict) else {}

    def get_pod(self, pod_id: str) -> dict:
        result = self._request("GET", f"/pods/{pod_id}")
        return result if isinstance(result, dict) else {}

    def stop_pod(self, pod_id: str) -> None:
        self._request("POST", f"/pods/{pod_id}/stop")

    def terminate_pod(self, pod_id: str) -> None:
        self._request("DELETE", f"/pods/{pod_id}")


def estimate_storage_cost_usd_per_month(size_gb: int) -> float:
    """Approximate monthly storage cost for a network volume of ``size_gb``."""
    return size_gb * STORAGE_RATE_USD_PER_GB_MONTH


def find_volume_by_name(client: RunPodRestClient, name: str) -> dict | None:
    """Return the first existing volume with ``name``, or ``None`` (idempotency check)."""
    for volume in client.list_network_volumes():
        if volume.get("name") == name:
            return volume
    return None


def ensure_volume(client: RunPodRestClient, name: str, size_gb: int, data_center_id: str) -> tuple[dict, bool]:
    """Find-or-create the named volume. Returns ``(volume, created)``.

    Idempotent: an existing volume with the same name is reused (never duplicated),
    so re-running the setup script is safe.
    """
    existing = find_volume_by_name(client, name)
    if existing is not None:
        return existing, False
    created = client.create_network_volume(name=name, size_gb=size_gb, data_center_id=data_center_id)
    return created, True


def build_download_pod_payload(
    volume_id: str,
    image: str,
    gpu_type: str,
    download_cmd: list[str],
    name: str,
    data_center_id: str,
    container_disk_gb: int = CONTAINER_DISK_GB,
) -> dict:
    """Build the POST /pods body for the temporary weight-download pod.

    The pod is pinned to ``data_center_id`` — a network volume lives in exactly one
    data center, and a pod can only attach a volume in the same one, so placing the
    pod elsewhere would fail to mount it.
    """
    return {
        "name": name,
        "imageName": image,
        "gpuTypeIds": [gpu_type],
        "gpuCount": 1,
        "dataCenterIds": [data_center_id],
        "networkVolumeId": volume_id,
        "volumeMountPath": VOLUME_MOUNT_PATH,
        "containerDiskInGb": container_disk_gb,
        "dockerStartCmd": download_cmd,
    }


def pod_is_finished(pod: dict) -> bool:
    """True once the pod's one-shot download command has exited.

    RunPod reports status under a few keys depending on API version; treat any
    terminal status as "download done".
    """
    for key in ("desiredStatus", "currentStatus", "status", "lastStatus"):
        value = pod.get(key)
        if isinstance(value, str) and value.upper() in _TERMINAL_POD_STATUSES:
            return True
    return False


def wait_for_pod_finish(
    client: RunPodRestClient,
    pod_id: str,
    timeout: float,
    poll_interval: float,
    sleep=time.sleep,
    on_poll=None,
) -> bool:
    """Poll the pod until its download command finishes or ``timeout`` elapses.

    Returns True if the pod reached a terminal status, False on timeout. ``sleep``
    is injectable so tests can drive the loop without real delays; ``on_poll`` (if
    given) is called with the elapsed seconds after each non-terminal poll so a
    long download (20-40 min) shows progress instead of hanging silently.
    """
    start = time.monotonic()
    deadline = start + timeout
    while time.monotonic() < deadline:
        if pod_is_finished(client.get_pod(pod_id)):
            return True
        if on_poll is not None:
            on_poll(time.monotonic() - start)
        sleep(poll_interval)
    return False


def _confirm(assume_yes: bool, prompt: str = "Proceed and create RunPod resources? [y/N] ") -> bool:
    if assume_yes:
        return True
    answer = input(prompt).strip().lower()
    return answer in ("y", "yes")


def run_setup(
    client: RunPodRestClient,
    *,
    volume_name: str,
    size_gb: int,
    region: str,
    image: str,
    gpu_type: str,
    download_cmd: list[str],
    timeout: float,
    poll_interval: float,
    dry_run: bool,
    assume_yes: bool,
    container_disk_gb: int = CONTAINER_DISK_GB,
) -> int:
    """Orchestrate the one-time setup. Returns a process exit code (0 = success)."""
    monthly = estimate_storage_cost_usd_per_month(size_gb)
    print("RunPod Network Volume setup (ACE-Step-1.5 weights)")
    print(f"  Volume name : {volume_name}")
    print(f"  Size        : {size_gb} GB")
    print(f"  Region      : {region}")
    print(f"  Worker image: {image}")
    print(f"  Download GPU: {gpu_type} (temporary pod, billed only while downloading)")
    print(
        f"  Estimated cost: ~${monthly:.2f}/month storage "
        f"(~${STORAGE_RATE_USD_PER_GB_MONTH:.2f}/GB/mo) + temporary GPU pod time during download."
    )

    if dry_run:
        print("\n[dry-run] No resources created. Planned actions:")
        print(f"  1. Find-or-create volume {volume_name!r} ({size_gb} GB) in {region}.")
        print(f"  2. Launch temporary {gpu_type} pod from {image} with the volume mounted at {VOLUME_MOUNT_PATH}.")
        print(f"  3. Run download command: {download_cmd}")
        print("  4. Wait for completion, then stop and terminate the pod (volume persists).")
        return 0

    if not _confirm(assume_yes):
        print("Aborted; no resources created.")
        return 1

    volume, created = ensure_volume(client, name=volume_name, size_gb=size_gb, data_center_id=region)
    volume_id = volume.get("id")
    if not volume_id:
        print("ERROR: RunPod did not return a volume id.", file=sys.stderr)
        return 1
    print(f"{'Created' if created else 'Reusing existing'} volume: {volume_id}")

    pod_id = None
    try:
        payload = build_download_pod_payload(
            volume_id=volume_id,
            image=image,
            gpu_type=gpu_type,
            download_cmd=download_cmd,
            name=f"{volume_name}-weights-download",
            data_center_id=region,
            container_disk_gb=container_disk_gb,
        )
        pod = client.create_pod(payload)
        pod_id = pod.get("id")
        if not pod_id:
            print("ERROR: RunPod did not return a pod id.", file=sys.stderr)
            return 1
        print(f"Launched temporary download pod: {pod_id}. Waiting for weights to download...")
        finished = wait_for_pod_finish(
            client,
            pod_id,
            timeout=timeout,
            poll_interval=poll_interval,
            on_poll=lambda elapsed: print(f"  ...still downloading ({elapsed:.0f}s elapsed)"),
        )
        if not finished:
            print(
                f"ERROR: download pod {pod_id} did not finish within {timeout:.0f}s. "
                "The pod is being terminated; re-run after checking RunPod logs.",
                file=sys.stderr,
            )
            return 1
        print("Download pod finished.")
    finally:
        # Always clean up the temporary pod; the VOLUME is intentionally left intact.
        if pod_id:
            _cleanup_pod(client, pod_id)

    # Completion is detected from the pod reaching a terminal state; RunPod's REST
    # API does not reliably surface the container exit code, so confirm the pod log
    # shows the success marker before trusting the volume (the default command
    # prints ACE_STEP_WEIGHTS_READY on success and exits non-zero on failure).
    print("\nDone. Verify the pod log shows 'ACE_STEP_WEIGHTS_READY', then configure your API environment with:")
    print(f"  ACEMUSIC_API_RUNPOD_NETWORK_VOLUME_ID={volume_id}")
    return 0


def _cleanup_pod(client: RunPodRestClient, pod_id: str) -> None:
    """Stop then terminate the temporary pod, tolerating partial failure."""
    for action, fn in (("stop", client.stop_pod), ("terminate", client.terminate_pod)):
        try:
            fn(pod_id)
        except RunPodRestError as exc:
            print(f"WARNING: failed to {action} pod {pod_id}: {exc}", file=sys.stderr)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Provision the RunPod Network Volume with ACE-Step-1.5 weights (idempotent).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--region", default=DEFAULT_REGION, help="RunPod data center id for the volume.")
    parser.add_argument("--size", type=int, default=DEFAULT_SIZE_GB, help="Volume size in GB.")
    parser.add_argument("--volume-name", default=DEFAULT_VOLUME_NAME, help="Volume name (used for idempotency).")
    parser.add_argument(
        "--image",
        default=DEFAULT_IMAGE,
        help="Worker image to run in the temporary pod. Pin to a digest/tag (not ':latest') for reproducible runs.",
    )
    parser.add_argument("--gpu-type", default=DEFAULT_GPU_TYPE, help="GPU type id for the temporary download pod.")
    parser.add_argument(
        "--container-disk",
        type=int,
        default=CONTAINER_DISK_GB,
        help="Container scratch disk (GB) for the temporary pod; raise for heavier custom images.",
    )
    parser.add_argument(
        "--download-cmd",
        default=None,
        help="Override the weight-download command (run via 'bash -lc'). Defaults to warming the HF cache.",
    )
    parser.add_argument("--timeout", type=float, default=3600.0, help="Max seconds to wait for the download to finish.")
    parser.add_argument("--poll-interval", type=float, default=15.0, help="Seconds between pod-status polls.")
    parser.add_argument("--dry-run", action="store_true", help="Print the plan and cost estimate; make no changes.")
    parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    api_key = os.environ.get("RUNPOD_API_KEY")
    if not api_key and not args.dry_run:
        print("ERROR: RUNPOD_API_KEY is not set in the environment.", file=sys.stderr)
        return 2

    download_cmd = ["bash", "-lc", args.download_cmd] if args.download_cmd else DEFAULT_DOWNLOAD_CMD
    client = RunPodRestClient(api_key=api_key or "")
    return run_setup(
        client,
        volume_name=args.volume_name,
        size_gb=args.size,
        region=args.region,
        image=args.image,
        gpu_type=args.gpu_type,
        download_cmd=download_cmd,
        timeout=args.timeout,
        poll_interval=args.poll_interval,
        dry_run=args.dry_run,
        assume_yes=args.yes,
        container_disk_gb=args.container_disk,
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
