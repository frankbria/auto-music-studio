"""API configuration via pydantic-settings (US-8.1).

Distinct from the CLI's :mod:`acemusic.config` (which serves the ACE-Step client).
All API settings are namespaced under the ``ACEMUSIC_API_`` env prefix so they do
not collide with CLI or ACE-Step server variables.
"""

from typing import Annotated

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEFAULT_CORS_ORIGINS = ["http://localhost:3000", "http://localhost:8000"]

# HMAC only: the auth layer signs with a single shared secret. Allowing an
# asymmetric alg (e.g. RS256) without a key would fail at token-mint time rather
# than startup, so the allowed set is restricted to the HS family.
ALLOWED_JWT_ALGORITHMS = ("HS256", "HS384", "HS512")

# SameSite policies for the OAuth state cookie. "lax" suits a same-origin
# deployment (frontend and API behind one origin); "none" is required for a
# split-origin SPA so the cookie is sent on the cross-site callback (browsers
# also require Secure in that case).
ALLOWED_COOKIE_SAMESITE = ("lax", "strict", "none")


class ApiSettings(BaseSettings):
    """Runtime configuration for the FastAPI service.

    ``cors_allow_origins`` is annotated with :class:`~pydantic_settings.NoDecode`
    to disable pydantic-settings' default JSON decoding, so its env value can be a
    friendly comma-separated string (e.g. ``https://a.com,https://b.com``) rather
    than a JSON array. :meth:`_split_origins` performs the splitting.
    """

    model_config = SettingsConfigDict(
        env_prefix="ACEMUSIC_API_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    cors_allow_origins: Annotated[list[str], NoDecode] = DEFAULT_CORS_ORIGINS

    # MongoDB (US-8.2). Defaults target a local server; production/staging set
    # mongodb_url to an Atlas mongodb+srv:// string via the environment.
    mongodb_url: str = "mongodb://localhost:27017"
    mongodb_db_name: str = "acemusic"
    mongodb_min_pool_size: int = Field(default=10, ge=0)
    mongodb_max_pool_size: int = Field(default=100, ge=1)
    mongodb_server_selection_timeout_ms: int = Field(default=5000, ge=1)

    # OAuth2 providers (US-8.3). Credentials are issued per-provider in their
    # developer consoles; left unset until configured via the environment. A
    # provider is only usable once its three vars (id/secret/redirect_uri) are set.
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str | None = None
    discord_client_id: str | None = None
    discord_client_secret: str | None = None
    discord_redirect_uri: str | None = None

    # JWT signing (US-8.3). ``jwt_secret_key`` has no default on purpose: the auth
    # layer raises a clear error if a token is minted while it is unset, rather
    # than silently signing with a guessable key. Lifetimes follow the common
    # short-access / longer-refresh pattern.
    jwt_secret_key: str | None = None
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = Field(default=15, ge=1)
    refresh_token_expire_days: int = Field(default=7, ge=1)

    # Async job processor (US-9.2). The processor runs as a background task inside
    # the API process, polling MongoDB for queued jobs. ``job_concurrency`` bounds
    # how many run at once; ``job_poll_interval`` is the idle sleep between polls
    # when the queue is empty; ``job_poll_timeout`` caps how long a single job
    # waits for ACE-Step before it is failed. ``job_processor_enabled`` lets a
    # deployment (or a test) run the API without the background worker.
    job_concurrency: int = Field(default=2, ge=1)
    job_poll_interval: float = Field(default=1.0, gt=0)
    job_poll_timeout: float = Field(default=600.0, gt=0)
    job_processor_enabled: bool = True

    # OAuth ``state`` cookie policy (issue #110, login-CSRF binding). The login
    # flow sets a per-client nonce cookie that the callback requires.
    # ``oauth_cookie_secure`` marks it Secure (HTTPS-only); keep True in
    # production, set False only for local/dev or tests over plain HTTP.
    # ``oauth_cookie_samesite`` is "lax" for a same-origin frontend/API; a
    # split-origin SPA must use "none" (which the browser only honours when the
    # cookie is also Secure, i.e. over HTTPS) so the cookie is sent on the
    # cross-site callback.
    oauth_cookie_secure: bool = True
    oauth_cookie_samesite: str = "lax"

    @field_validator("oauth_cookie_samesite")
    @classmethod
    def _check_cookie_samesite(cls, value: str) -> str:
        """Normalize and validate the SameSite policy at parse time."""
        normalized = value.strip().lower()
        if normalized not in ALLOWED_COOKIE_SAMESITE:
            raise ValueError(
                f"oauth_cookie_samesite {value!r} is not supported; "
                f"choose one of {', '.join(ALLOWED_COOKIE_SAMESITE)}"
            )
        return normalized

    @model_validator(mode="after")
    def _samesite_none_requires_secure(self) -> "ApiSettings":
        """SameSite=None cookies are ignored by browsers unless also Secure."""
        if self.oauth_cookie_samesite == "none" and not self.oauth_cookie_secure:
            raise ValueError(
                "oauth_cookie_samesite='none' requires oauth_cookie_secure=True (browsers ignore it otherwise)."
            )
        return self

    @field_validator("jwt_algorithm")
    @classmethod
    def _check_jwt_algorithm(cls, value: str) -> str:
        """Reject non-HMAC algorithms at parse time, not at token-mint time."""
        if value not in ALLOWED_JWT_ALGORITHMS:
            raise ValueError(
                f"jwt_algorithm {value!r} is not supported; " f"choose one of {', '.join(ALLOWED_JWT_ALGORITHMS)}"
            )
        return value

    @model_validator(mode="after")
    def _check_pool_bounds(self) -> "ApiSettings":
        """Catch misconfigured pool sizes at parse time, not during DB init."""
        if self.mongodb_min_pool_size > self.mongodb_max_pool_size:
            raise ValueError(
                f"mongodb_min_pool_size ({self.mongodb_min_pool_size}) cannot exceed "
                f"mongodb_max_pool_size ({self.mongodb_max_pool_size})"
            )
        return self

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Accept a comma-separated string or an already-parsed list.

        A blank string falls back to the defaults, matching the CLI's
        "empty env var == unset" convention (see acemusic.config) so the
        shipped `.env.example` (ACEMUSIC_API_CORS_ALLOW_ORIGINS=) does not
        silently disable local CORS.
        """
        if isinstance(value, str):
            origins = [origin.strip() for origin in value.split(",") if origin.strip()]
            return origins or DEFAULT_CORS_ORIGINS
        return value
