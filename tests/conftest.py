"""Root pytest configuration and shared fixtures for the acemusic test suite."""

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

# Load .env.local for integration tests (e.g. ACEMUSIC_BASE_URL, ACESTEP_LOCAL_URL)
load_dotenv(Path(__file__).parent.parent / ".env.local", override=False)


@pytest.fixture
def integration_url() -> str:
    """Return the best available ACE-Step server URL for integration tests.

    Prefers ACESTEP_LOCAL_URL (local server) over ACEMUSIC_BASE_URL (remote).
    Skips the test if neither is configured.
    """
    url = os.environ.get("ACESTEP_LOCAL_URL") or os.environ.get("ACEMUSIC_BASE_URL")
    if not url:
        pytest.skip("No ACE-Step server configured (set ACESTEP_LOCAL_URL or ACEMUSIC_BASE_URL)")
    return url


@pytest.fixture
def app_config():
    """Minimal application configuration fixture.

    Returns a dict with default config values. Extend this fixture in
    sub-conftest.py files or override per-test as the project grows.
    """
    return {}
