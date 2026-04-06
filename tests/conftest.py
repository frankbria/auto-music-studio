"""Root pytest configuration and shared fixtures for the acemusic test suite."""

import pytest


@pytest.fixture
def app_config():
    """Minimal application configuration fixture.

    Returns a dict with default config values. Extend this fixture in
    sub-conftest.py files or override per-test as the project grows.
    """
    return {}
