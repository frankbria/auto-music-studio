"""Root pytest configuration and shared fixtures for the acemusic test suite."""

from pathlib import Path

import pytest
from dotenv import load_dotenv

# Load .env.local for integration tests (e.g. ACEMUSIC_BASE_URL)
load_dotenv(Path(__file__).parent.parent / ".env.local", override=False)


@pytest.fixture
def app_config():
    """Minimal application configuration fixture.

    Returns a dict with default config values. Extend this fixture in
    sub-conftest.py files or override per-test as the project grows.
    """
    return {}
