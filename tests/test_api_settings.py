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


class TestTrustedProxies:
    """issue #283: proxies whose forwarded client-IP header the limiter trusts."""

    def test_default_is_empty(self, monkeypatch):
        """Unset -> trust nobody, i.e. today's peer-IP-only behavior (AC4)."""
        monkeypatch.delenv("ACEMUSIC_API_TRUSTED_PROXIES", raising=False)
        settings = ApiSettings(_env_file=None)
        assert settings.trusted_proxies == []
        assert settings.trusted_proxy_set == frozenset()

    def test_parsed_from_comma_separated_env(self, monkeypatch):
        monkeypatch.setenv("ACEMUSIC_API_TRUSTED_PROXIES", "10.0.0.2, 127.0.0.1")
        settings = ApiSettings(_env_file=None)
        assert settings.trusted_proxies == ["10.0.0.2", "127.0.0.1"]
        assert settings.trusted_proxy_set == frozenset({"10.0.0.2", "127.0.0.1"})

    def test_blank_env_is_empty(self, monkeypatch):
        """A blank value behaves like unset (trust nobody), unlike CORS which
        falls back to localhost defaults — an empty trust set is the safe one."""
        monkeypatch.setenv("ACEMUSIC_API_TRUSTED_PROXIES", "  ")
        settings = ApiSettings(_env_file=None)
        assert settings.trusted_proxies == []


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
        "ACEMUSIC_API_OAUTH_COOKIE_SAMESITE",
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

    def test_oauth_cookie_samesite_defaults_lax(self):
        """A same-origin frontend/API deployment uses Lax by default."""
        assert ApiSettings(_env_file=None).oauth_cookie_samesite == "lax"

    def test_oauth_cookie_samesite_normalized_and_overridable(self, monkeypatch):
        """Split-origin SPAs set 'none'; the value is normalized to lowercase."""
        monkeypatch.setenv("ACEMUSIC_API_OAUTH_COOKIE_SAMESITE", "None")
        assert ApiSettings(_env_file=None).oauth_cookie_samesite == "none"

    def test_oauth_cookie_samesite_rejects_unknown(self, monkeypatch):
        monkeypatch.setenv("ACEMUSIC_API_OAUTH_COOKIE_SAMESITE", "bogus")
        with pytest.raises(ValueError, match="oauth_cookie_samesite"):
            ApiSettings(_env_file=None)

    def test_oauth_cookie_samesite_none_requires_secure(self, monkeypatch):
        """SameSite=None without Secure is rejected (browsers would ignore it)."""
        monkeypatch.setenv("ACEMUSIC_API_OAUTH_COOKIE_SAMESITE", "none")
        monkeypatch.setenv("ACEMUSIC_API_OAUTH_COOKIE_SECURE", "false")
        with pytest.raises(ValueError, match="requires oauth_cookie_secure"):
            ApiSettings(_env_file=None)

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


class TestComputeRoutingSettings:
    """Compute routing configuration (US-11.1)."""

    @pytest.fixture(autouse=True)
    def _clear_routing_env(self, monkeypatch):
        for key in ("ACEMUSIC_API_COMPUTE_PREFERENCE", "ACEMUSIC_API_LOCAL_URL"):
            monkeypatch.delenv(key, raising=False)

    def test_defaults(self):
        """Compute defaults to local-first against the conventional local port."""
        settings = ApiSettings(_env_file=None)
        assert settings.compute_preference == "local_first"
        assert settings.local_url == "http://localhost:8001"

    @pytest.mark.parametrize("preference", ["local_first", "remote_first", "local_only", "remote_only"])
    def test_compute_preference_accepts_each_mode(self, monkeypatch, preference):
        monkeypatch.setenv("ACEMUSIC_API_COMPUTE_PREFERENCE", preference)
        assert ApiSettings(_env_file=None).compute_preference == preference

    def test_compute_preference_rejects_unknown(self, monkeypatch):
        monkeypatch.setenv("ACEMUSIC_API_COMPUTE_PREFERENCE", "bogus")
        with pytest.raises(ValueError, match="compute_preference"):
            ApiSettings(_env_file=None)

    def test_local_url_from_env(self, monkeypatch):
        monkeypatch.setenv("ACEMUSIC_API_LOCAL_URL", "http://gpu-box:9000")
        assert ApiSettings(_env_file=None).local_url == "http://gpu-box:9000"

    @pytest.mark.parametrize("value", ["localhost:8001", "ftp://host:1", "not a url", ""])
    def test_local_url_rejects_malformed(self, monkeypatch, value):
        """A scheme-less or non-http(s) value is rejected at startup, not at probe time."""
        monkeypatch.setenv("ACEMUSIC_API_LOCAL_URL", value)
        with pytest.raises(ValueError, match="local_url"):
            ApiSettings(_env_file=None)


class TestRunPodSettings:
    """RunPod serverless remote-routing configuration (US-11.2)."""

    @pytest.fixture(autouse=True)
    def _clear_runpod_env(self, monkeypatch):
        for key in (
            "ACEMUSIC_API_RUNPOD_API_KEY",
            "ACEMUSIC_API_RUNPOD_ENDPOINT_ID",
            "ACEMUSIC_API_RUNPOD_TIMEOUT",
            "ACEMUSIC_API_RUNPOD_POLL_INTERVAL",
            "ACEMUSIC_API_RUNPOD_NETWORK_VOLUME_ID",
            "ACEMUSIC_API_RUNPOD_REST_BASE_URL",
        ):
            monkeypatch.delenv(key, raising=False)

    def test_defaults_are_unset_and_disabled(self):
        settings = ApiSettings(_env_file=None)
        assert settings.runpod_api_key is None
        assert settings.runpod_endpoint_id is None
        assert settings.runpod_timeout == 300.0
        assert settings.runpod_poll_interval == 5.0
        assert settings.runpod_enabled is False

    def test_enabled_requires_both_credentials(self, monkeypatch):
        monkeypatch.setenv("ACEMUSIC_API_RUNPOD_API_KEY", "rp-key")
        assert ApiSettings(_env_file=None).runpod_enabled is False

        monkeypatch.delenv("ACEMUSIC_API_RUNPOD_API_KEY")
        monkeypatch.setenv("ACEMUSIC_API_RUNPOD_ENDPOINT_ID", "ep-1")
        assert ApiSettings(_env_file=None).runpod_enabled is False

    def test_enabled_when_both_credentials_set(self, monkeypatch):
        monkeypatch.setenv("ACEMUSIC_API_RUNPOD_API_KEY", "rp-key")
        monkeypatch.setenv("ACEMUSIC_API_RUNPOD_ENDPOINT_ID", "ep-1")
        settings = ApiSettings(_env_file=None)
        assert settings.runpod_enabled is True
        assert settings.runpod_api_key == "rp-key"
        assert settings.runpod_endpoint_id == "ep-1"

    def test_timeout_and_poll_interval_from_env(self, monkeypatch):
        monkeypatch.setenv("ACEMUSIC_API_RUNPOD_TIMEOUT", "600")
        monkeypatch.setenv("ACEMUSIC_API_RUNPOD_POLL_INTERVAL", "10")
        settings = ApiSettings(_env_file=None)
        assert settings.runpod_timeout == 600.0
        assert settings.runpod_poll_interval == 10.0

    @pytest.mark.parametrize("value", ["0", "-1"])
    def test_timeout_rejects_non_positive(self, monkeypatch, value):
        monkeypatch.setenv("ACEMUSIC_API_RUNPOD_TIMEOUT", value)
        with pytest.raises(ValueError, match="runpod_timeout"):
            ApiSettings(_env_file=None)

    @pytest.mark.parametrize("value", ["0", "-2"])
    def test_poll_interval_rejects_non_positive(self, monkeypatch, value):
        monkeypatch.setenv("ACEMUSIC_API_RUNPOD_POLL_INTERVAL", value)
        with pytest.raises(ValueError, match="runpod_poll_interval"):
            ApiSettings(_env_file=None)


class TestRunPodVolumeSettings:
    """RunPod Network Volume configuration (US-11.5).

    The serverless credentials (US-11.2) drive job routing; the volume id names
    the persisted weights volume those workers mount, so it is configured
    separately and the volume-info endpoint reads it to look the volume up.
    """

    @pytest.fixture(autouse=True)
    def _clear_volume_env(self, monkeypatch):
        for key in (
            "ACEMUSIC_API_RUNPOD_NETWORK_VOLUME_ID",
            "ACEMUSIC_API_RUNPOD_REST_BASE_URL",
        ):
            monkeypatch.delenv(key, raising=False)

    def test_volume_id_defaults_to_none(self):
        """No volume is configured until the setup script provisions one."""
        assert ApiSettings(_env_file=None).runpod_network_volume_id is None

    def test_rest_base_url_default(self):
        """The volume-management REST API is distinct from the serverless base URL."""
        settings = ApiSettings(_env_file=None)
        assert settings.runpod_rest_base_url == "https://rest.runpod.io/v1"
        # The serverless base URL (US-11.2) is a separate endpoint and untouched.
        assert settings.runpod_base_url == "https://api.runpod.ai/v2"

    def test_volume_id_from_env(self, monkeypatch):
        monkeypatch.setenv("ACEMUSIC_API_RUNPOD_NETWORK_VOLUME_ID", "vol-abc123")
        assert ApiSettings(_env_file=None).runpod_network_volume_id == "vol-abc123"

    def test_rest_base_url_from_env(self, monkeypatch):
        monkeypatch.setenv("ACEMUSIC_API_RUNPOD_REST_BASE_URL", "https://staging.runpod.io/v1")
        assert ApiSettings(_env_file=None).runpod_rest_base_url == "https://staging.runpod.io/v1"
