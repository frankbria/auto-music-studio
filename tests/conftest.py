"""Root pytest configuration and shared fixtures for the acemusic test suite."""

import os
import subprocess
import time
from pathlib import Path

import httpx
import pytest
from dotenv import load_dotenv

# Load .env.local for integration tests (ACEMUSIC_BASE_URL, ACESTEP_LOCAL_URL, etc.)
load_dotenv(Path(__file__).parent.parent / ".env.local", override=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _server_healthy(url: str, timeout: float = 3.0) -> bool:
    """Return True if the ACE-Step server is responding at /health."""
    try:
        resp = httpx.get(f"{url}/health", timeout=timeout)
        return resp.status_code == 200
    except Exception:
        return False


def _server_auth_ok(url: str, api_key: str, timeout: float = 3.0) -> bool:
    """Return True if /v1/stats accepts the given API key (or no key if empty)."""
    try:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        resp = httpx.get(f"{url}/v1/stats", headers=headers, timeout=timeout)
        return resp.status_code == 200
    except Exception:
        return False


def _queue_size(url: str, api_key: str, timeout: float = 3.0) -> int:
    """Return the number of queued jobs on the server, or -1 on failure."""
    try:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        resp = httpx.get(f"{url}/v1/stats", headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp.json().get("data", {}).get("queue_size", 0)
    except Exception:
        return -1


# ---------------------------------------------------------------------------
# Session-scoped server lifecycle
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def ace_server():
    """Ensure an ACE-Step server is running for integration tests.

    Resolution order:
    1. If already healthy on ACESTEP_LOCAL_URL → use as-is, don't stop on teardown.
    2. If ACESTEP_API_CMD is set → start the server, wait until healthy, stop on teardown.
    3. Otherwise → skip the test.

    Environment variables (loaded from .env.local):
        ACESTEP_LOCAL_URL      Server URL (default: http://localhost:8001)
        ACESTEP_API_CMD        Path to the acestep-api binary
        ACESTEP_START_TIMEOUT  Seconds to wait for healthy (default: 300)
    """
    url = os.environ.get("ACESTEP_LOCAL_URL", "http://localhost:8001")

    api_key = os.environ.get("ACEMUSIC_API_KEY", "")

    # Case 1: already running and our key works
    if _server_healthy(url):
        if not _server_auth_ok(url, api_key):
            pytest.skip(
                f"ACE-Step server at {url} is running but rejects ACEMUSIC_API_KEY. "
                "Update ACEMUSIC_API_KEY in .env.local to match the server's key, "
                "or stop the server so the fixture can start a fresh one."
            )
        queued = _queue_size(url, api_key)
        if queued > 0:
            pytest.skip(
                f"ACE-Step server at {url} has {queued} queued job(s) from a previous run. "
                "Stop the server to let the fixture start a clean one: "
                f"kill $(lsof -ti:{url.split(':')[-1]})"
            )
        yield url
        return

    # Case 2: start it
    cmd = os.environ.get("ACESTEP_API_CMD")
    if not cmd:
        pytest.skip(
            f"ACE-Step server not running at {url} and ACESTEP_API_CMD is not set. "
            "Set ACESTEP_API_CMD in .env.local to enable auto-start."
        )

    timeout = int(os.environ.get("ACESTEP_START_TIMEOUT", "300"))
    # Start with the same key acemusic uses so auth aligns.
    # Do NOT pass --api-key: ACE-Step reads ACESTEP_API_KEY at module import
    # (before main() runs), so the --api-key flag has no effect on _api_key.
    # Instead, set ACESTEP_API_KEY in the subprocess env directly.
    # If api_key is empty we strip it entirely so _api_key stays None (auth disabled).
    server_env = os.environ.copy()
    if api_key:
        server_env["ACESTEP_API_KEY"] = api_key
    else:
        server_env.pop("ACESTEP_API_KEY", None)
    cmd_args = [cmd]
    proc = subprocess.Popen(
        cmd_args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=server_env,
    )
    print(f"\n[ace_server] Starting ACE-Step server (pid={proc.pid}), waiting up to {timeout}s…")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            pytest.fail(f"ACE-Step server process exited unexpectedly (rc={proc.returncode})")
        if _server_healthy(url):
            print(f"[ace_server] Server healthy at {url}")
            break
        time.sleep(3)
    else:
        proc.terminate()
        proc.wait(timeout=10)
        pytest.fail(f"ACE-Step server did not become healthy within {timeout}s at {url}")

    yield url

    print(f"\n[ace_server] Stopping ACE-Step server (pid {proc.pid})")
    proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()


# ---------------------------------------------------------------------------
# Per-test integration URL (depends on the session server)
# ---------------------------------------------------------------------------


@pytest.fixture
def integration_url(ace_server, monkeypatch) -> str:
    """Return the ACE-Step server URL, guaranteed healthy.

    Sets ACEMUSIC_BASE_URL via monkeypatch so load_config() routes requests to
    the local server. Tests should also pass env={"ACEMUSIC_BASE_URL": integration_url}
    to runner.invoke() as a second layer of isolation.
    """
    monkeypatch.setenv("ACEMUSIC_BASE_URL", ace_server)
    return ace_server


# ---------------------------------------------------------------------------
# General fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app_config():
    """Minimal application configuration fixture."""
    return {}
