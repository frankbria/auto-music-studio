"""Tests for the public models-list endpoint (US-16.4).

The endpoint is a pure read over :data:`acemusic.constants.MODELS` enriched with
display metadata, so these tests need no database — they drive the app directly.
"""

import httpx
import pytest

from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.settings import ApiSettings
from acemusic.constants import MODELS


def _async_client(app) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


@pytest.fixture
def app():
    # No Mongo needed; minimal settings with a valid-length JWT secret.
    settings = ApiSettings(jwt_secret_key="test-secret-key-at-least-32-bytes-long-xx")
    return create_app(settings)


@pytest.fixture
async def client(app):
    async with _async_client(app) as ac:
        yield ac


class TestListModels:
    async def test_public_no_auth_required(self, client):
        resp = await client.get(f"{API_V1_PREFIX}/models")
        assert resp.status_code == 200

    async def test_returns_all_registry_models(self, client):
        resp = await client.get(f"{API_V1_PREFIX}/models")
        body = resp.json()
        keys = {m["key"] for m in body["models"]}
        assert keys == set(MODELS.keys())

    async def test_each_model_has_display_and_technical_metadata(self, client):
        resp = await client.get(f"{API_V1_PREFIX}/models")
        for m in resp.json()["models"]:
            for field in ("key", "display_name", "category", "description", "pro_only", "vram", "steps", "dit_size"):
                assert field in m, f"{m['key']} missing {field}"
            # Technical fields mirror the constants registry exactly.
            assert m["description"] == MODELS[m["key"]]["description"]
            assert m["vram"] == MODELS[m["key"]]["vram"]
            assert m["dit_size"] == MODELS[m["key"]]["dit_size"]

    async def test_xl_variants_marked_pro_only(self, client):
        resp = await client.get(f"{API_V1_PREFIX}/models")
        by_key = {m["key"]: m for m in resp.json()["models"]}
        assert by_key["xl-base"]["pro_only"] is True
        assert by_key["xl-sft"]["pro_only"] is True
        assert by_key["xl-turbo"]["pro_only"] is True
        # Non-XL variants are available to all tiers.
        assert by_key["base"]["pro_only"] is False
        assert by_key["turbo"]["pro_only"] is False
        assert by_key["sft"]["pro_only"] is False
