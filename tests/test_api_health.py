"""Unit tests for the FastAPI app foundation and versioned health route (US-8.1)."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from acemusic import __version__
from acemusic.api.main import app as module_app
from acemusic.api.main import create_app
from acemusic.api.settings import ApiSettings


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


class TestAppFactory:
    def test_module_app_is_fastapi_instance(self):
        """`acemusic.api.main:app` must be a FastAPI app (target for uvicorn)."""
        assert isinstance(module_app, FastAPI)

    def test_app_version_matches_package(self):
        """The OpenAPI/app version is sourced from the package version."""
        assert create_app().version == __version__


class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        """GET /api/v1/health returns 200 with status ok and version."""
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["version"] == __version__

    def test_health_reports_uptime(self, client):
        """Health payload includes a non-negative numeric uptime."""
        body = client.get("/api/v1/health").json()
        assert "uptime_seconds" in body
        assert isinstance(body["uptime_seconds"], (int, float))
        assert body["uptime_seconds"] >= 0

    def test_unversioned_health_is_not_exposed(self, client):
        """Health is only mounted under the v1 prefix."""
        assert client.get("/health").status_code == 404

    def test_api_v2_returns_404(self, client):
        """No version leak: /api/v2/ is not served."""
        assert client.get("/api/v2/health").status_code == 404


class TestOpenApiDocs:
    def test_swagger_docs_render(self, client):
        """/docs renders the Swagger UI."""
        resp = client.get("/docs")
        assert resp.status_code == 200
        assert "swagger" in resp.text.lower()

    def test_redoc_renders(self, client):
        """/redoc renders the ReDoc UI."""
        assert client.get("/redoc").status_code == 200

    def test_openapi_schema_lists_health_route(self, client):
        """The versioned health path appears in the OpenAPI schema."""
        schema = client.get("/openapi.json").json()
        assert "/api/v1/health" in schema["paths"]


class TestCors:
    def test_cors_header_present_for_configured_origin(self):
        """A request from a configured origin gets an Access-Control-Allow-Origin header."""
        origin = "https://studio.example.com"
        app = create_app(settings=ApiSettings(cors_allow_origins=[origin], _env_file=None))
        client = TestClient(app)
        resp = client.get("/api/v1/health", headers={"Origin": origin})
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == origin

    def test_cors_preflight_allowed(self):
        """A CORS preflight OPTIONS request from a configured origin is permitted."""
        origin = "https://studio.example.com"
        app = create_app(settings=ApiSettings(cors_allow_origins=[origin], _env_file=None))
        client = TestClient(app)
        resp = client.options(
            "/api/v1/health",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == origin
