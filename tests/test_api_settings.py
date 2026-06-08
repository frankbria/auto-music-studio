"""Unit tests for the API settings layer (US-8.1).

The API uses pydantic-settings (separate from the CLI's dataclass config) with the
``ACEMUSIC_API_`` env prefix. CORS origins accept a comma-separated string for
ergonomic ``.env`` configuration.
"""

import pytest

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


class TestAuthSettings:
    """OAuth2 / JWT configuration (US-8.3)."""

    _AUTH_ENV_VARS = (
        "ACEMUSIC_API_GOOGLE_CLIENT_ID",
        "ACEMUSIC_API_GOOGLE_CLIENT_SECRET",
        "ACEMUSIC_API_GOOGLE_REDIRECT_URI",
        "ACEMUSIC_API_DISCORD_CLIENT_ID",
        "ACEMUSIC_API_DISCORD_CLIENT_SECRET",
        "ACEMUSIC_API_DISCORD_REDIRECT_URI",
        "ACEMUSIC_API_JWT_SECRET_KEY",
        "ACEMUSIC_API_JWT_ALGORITHM",
        "ACEMUSIC_API_ACCESS_TOKEN_EXPIRE_MINUTES",
        "ACEMUSIC_API_REFRESH_TOKEN_EXPIRE_DAYS",
        "ACEMUSIC_API_OAUTH_COOKIE_SECURE",
    )

    @pytest.fixture(autouse=True)
    def _clear_auth_env(self, monkeypatch):
        """Default-value assertions must not depend on the host's exported env."""
        for key in self._AUTH_ENV_VARS:
            monkeypatch.delenv(key, raising=False)

    def test_oauth_credentials_default_to_none(self):
        """Provider credentials are unset until configured via the environment."""
        settings = ApiSettings(_env_file=None)
        assert settings.google_client_id is None
        assert settings.google_client_secret is None
        assert settings.google_redirect_uri is None
        assert settings.discord_client_id is None
        assert settings.discord_client_secret is None
        assert settings.discord_redirect_uri is None

    def test_jwt_defaults(self):
        """JWT secret is unset by default; algorithm and lifetimes have sane defaults."""
        settings = ApiSettings(_env_file=None)
        assert settings.jwt_secret_key is None
        assert settings.jwt_algorithm == "HS256"
        assert settings.access_token_expire_minutes == 15
        assert settings.refresh_token_expire_days == 7

    def test_oauth_credentials_from_env(self, monkeypatch):
        """Provider credentials are read from prefixed env vars."""
        monkeypatch.setenv("ACEMUSIC_API_GOOGLE_CLIENT_ID", "g-id")
        monkeypatch.setenv("ACEMUSIC_API_GOOGLE_CLIENT_SECRET", "g-secret")
        monkeypatch.setenv("ACEMUSIC_API_GOOGLE_REDIRECT_URI", "https://app/cb/google")
        monkeypatch.setenv("ACEMUSIC_API_DISCORD_CLIENT_ID", "d-id")
        monkeypatch.setenv("ACEMUSIC_API_DISCORD_CLIENT_SECRET", "d-secret")
        monkeypatch.setenv("ACEMUSIC_API_DISCORD_REDIRECT_URI", "https://app/cb/discord")
        settings = ApiSettings(_env_file=None)
        assert settings.google_client_id == "g-id"
        assert settings.google_client_secret == "g-secret"
        assert settings.google_redirect_uri == "https://app/cb/google"
        assert settings.discord_client_id == "d-id"
        assert settings.discord_client_secret == "d-secret"
        assert settings.discord_redirect_uri == "https://app/cb/discord"

    def test_jwt_settings_from_env(self, monkeypatch):
        """JWT settings are overridable via prefixed env vars."""
        monkeypatch.setenv("ACEMUSIC_API_JWT_SECRET_KEY", "super-secret")
        monkeypatch.setenv("ACEMUSIC_API_JWT_ALGORITHM", "HS512")
        monkeypatch.setenv("ACEMUSIC_API_ACCESS_TOKEN_EXPIRE_MINUTES", "30")
        monkeypatch.setenv("ACEMUSIC_API_REFRESH_TOKEN_EXPIRE_DAYS", "14")
        settings = ApiSettings(_env_file=None)
        assert settings.jwt_secret_key == "super-secret"
        assert settings.jwt_algorithm == "HS512"
        assert settings.access_token_expire_minutes == 30
        assert settings.refresh_token_expire_days == 14

    def test_oauth_cookie_secure_defaults_true(self):
        """The OAuth state cookie (issue #110) is Secure by default for production."""
        assert ApiSettings(_env_file=None).oauth_cookie_secure is True

    def test_oauth_cookie_secure_overridable_for_http_dev(self, monkeypatch):
        """Local/dev over plain HTTP can disable Secure so the cookie is returned."""
        monkeypatch.setenv("ACEMUSIC_API_OAUTH_COOKIE_SECURE", "false")
        assert ApiSettings(_env_file=None).oauth_cookie_secure is False

    @pytest.mark.parametrize("algorithm", ["HS256", "HS384", "HS512"])
    def test_jwt_algorithm_allows_hmac_family(self, monkeypatch, algorithm):
        """The supported HMAC algorithms are accepted."""
        monkeypatch.setenv("ACEMUSIC_API_JWT_ALGORITHM", algorithm)
        assert ApiSettings(_env_file=None).jwt_algorithm == algorithm

    @pytest.mark.parametrize("algorithm", ["RS256", "none", "ES256", "hs256"])
    def test_jwt_algorithm_rejects_non_hmac(self, monkeypatch, algorithm):
        """Asymmetric/unknown algorithms are rejected at parse time, not mint time."""
        monkeypatch.setenv("ACEMUSIC_API_JWT_ALGORITHM", algorithm)
        with pytest.raises(ValueError, match="jwt_algorithm"):
            ApiSettings(_env_file=None)
