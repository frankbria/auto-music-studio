"""Unit tests for the API settings layer (US-8.1).

The API uses pydantic-settings (separate from the CLI's dataclass config) with the
``ACEMUSIC_API_`` env prefix. CORS origins accept a comma-separated string for
ergonomic ``.env`` configuration.
"""

from acemusic.api.settings import ApiSettings


class TestApiSettings:
    def test_default_cors_origins_include_localhost(self, monkeypatch):
        """With no env override, CORS defaults to local dev origins."""
        monkeypatch.delenv("ACEMUSIC_API_CORS_ALLOW_ORIGINS", raising=False)
        settings = ApiSettings(_env_file=None)
        assert isinstance(settings.cors_allow_origins, list)
        assert any("localhost" in origin for origin in settings.cors_allow_origins)

    def test_cors_origins_parsed_from_comma_separated_env(self, monkeypatch):
        """A comma-separated env value is split into a list of trimmed origins."""
        monkeypatch.setenv(
            "ACEMUSIC_API_CORS_ALLOW_ORIGINS",
            "https://app.example.com, https://studio.example.com",
        )
        settings = ApiSettings(_env_file=None)
        assert settings.cors_allow_origins == [
            "https://app.example.com",
            "https://studio.example.com",
        ]

    def test_cors_origins_blank_env_falls_back_to_defaults(self, monkeypatch):
        """A blank env value falls back to defaults (not []).

        The shipped .env.example sets ACEMUSIC_API_CORS_ALLOW_ORIGINS= (empty),
        so a blank value must behave like "unset" and keep the localhost
        defaults; otherwise a copied .env would silently disable local CORS.
        """
        monkeypatch.setenv("ACEMUSIC_API_CORS_ALLOW_ORIGINS", "  ")
        settings = ApiSettings(_env_file=None)
        assert any("localhost" in origin for origin in settings.cors_allow_origins)

    def test_env_prefix_is_namespaced(self, monkeypatch):
        """An unprefixed CORS var must NOT be picked up (avoids collisions)."""
        monkeypatch.delenv("ACEMUSIC_API_CORS_ALLOW_ORIGINS", raising=False)
        monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://evil.example.com")
        settings = ApiSettings(_env_file=None)
        assert "https://evil.example.com" not in settings.cors_allow_origins
