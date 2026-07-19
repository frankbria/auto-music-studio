"""API configuration via pydantic-settings (US-8.1).

Distinct from the CLI's :mod:`acemusic.config` (which serves the ACE-Step client).
All API settings are namespaced under the ``ACEMUSIC_API_`` env prefix so they do
not collide with CLI or ACE-Step server variables.
"""

import re
from typing import Annotated, Literal
from urllib.parse import urlsplit

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

    # SoundCloud OAuth 2.1 + PKCE for distribution account-linking (US-13.2).
    # Separate from the login providers above: these link an *already
    # authenticated* user's SoundCloud account so the platform can upload tracks
    # on their behalf. Unusable until all three are set via the environment.
    soundcloud_client_id: str | None = None
    soundcloud_client_secret: str | None = None
    soundcloud_redirect_uri: str | None = None

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
    job_processor_enabled: bool = Field(default=True)

    # SoundCloud distribution-status poller (US-13.6). A background task that keeps
    # the SoundCloud channel's status in sync with the real track state.
    # ``soundcloud_poll_interval`` is the gap between cycles; ``soundcloud_poll_batch_size``
    # caps how many pending releases each cycle checks. Disable it (or run a
    # poller-less API) via ACEMUSIC_API_SOUNDCLOUD_POLLER_ENABLED=false.
    soundcloud_poller_enabled: bool = Field(default=True)
    # Floor at 5s so a misconfiguration can't hammer the SoundCloud API.
    soundcloud_poll_interval: float = Field(default=60.0, ge=5)
    soundcloud_poll_batch_size: int = Field(default=20, ge=1)

    # Compute routing (US-11.1). ``compute_preference`` selects where a generation
    # runs when the request does not pin a ``compute_target``: ``*_first`` tries
    # the named target then falls back to the other; ``*_only`` never falls back
    # (a 503 surfaces when that target is down). ``local_url`` is the local
    # ACE-Step base URL whose ``/v1/stats`` endpoint is the availability probe;
    # it defaults to the conventional local port and is independent of the CLI's
    # ACE-Step config (which drives actual job execution).
    compute_preference: Literal["local_first", "remote_first", "local_only", "remote_only"] = "local_first"
    local_url: str = "http://localhost:8001"

    # RunPod serverless remote routing (US-11.2). The credentials are optional: a
    # deployment without them runs local-only — ``runpod_enabled`` is False, so the
    # routing engine reports remote unavailable (``*_first`` falls back, ``remote_only``
    # 503s) rather than crashing. ``runpod_timeout`` caps how long a remote job may run
    # before it is failed; ``runpod_poll_interval`` is the gap between status polls,
    # defaulted high to tolerate serverless cold starts without hammering the API.
    runpod_api_key: str | None = None
    runpod_endpoint_id: str | None = None
    runpod_base_url: str = "https://api.runpod.ai/v2"
    runpod_timeout: float = Field(default=300.0, gt=0)
    runpod_poll_interval: float = Field(default=5.0, gt=0)

    # RunPod Network Volume (US-11.5). ``runpod_network_volume_id`` names the
    # persisted weights volume that ``scripts/runpod-setup.py`` provisions once and
    # every serverless worker mounts; it is what ``GET /compute/remote/volume`` looks
    # up. It stays None on deployments that have not run the setup script (the
    # endpoint then 503s rather than crashing). ``runpod_rest_base_url`` is RunPod's
    # *management* REST API (volumes/pods) — a different host from the serverless
    # ``runpod_base_url`` above — overridable only to point at a staging proxy.
    runpod_network_volume_id: str | None = None
    runpod_rest_base_url: str = "https://rest.runpod.io/v1"

    # Dolby.io Music Mastering (US-12.2). The credentials are optional: a
    # deployment without them runs with mastering disabled — ``dolby_enabled`` is
    # False, so the mastering worker fails a claimed job with a clear "not
    # configured" error rather than crashing the app. Both an app key and secret
    # are required (Dolby.io exchanges them for a short-lived bearer token).
    dolby_api_key: str | None = None
    dolby_api_secret: str | None = None

    # LANDR B2B Music Mastering (US-12.3). Optional fallback alongside Dolby.io;
    # the B2B API exchanges an app key/secret for a session token, mirroring
    # Dolby.io. ``landr_enabled`` is False unless both are set, so the
    # orchestrator skips LANDR in the fallback chain on a LANDR-less deployment.
    landr_api_key: str | None = None
    landr_api_secret: str | None = None

    # Bakuage AI Mastering (US-12.3). Optional cost-effective fallback (the end of
    # the Dolby -> LANDR -> Bakuage chain). Bakuage uses a single API-key bearer
    # token (no OAuth), so only one credential is required; ``bakuage_enabled`` is
    # False until it is set.
    bakuage_api_key: str | None = None

    # Cover art generation (US-13.1). Optional: a deployment without an OpenAI key
    # runs with artwork generation disabled — ``artwork_enabled`` is False, so the
    # artwork worker fails a claimed job with a clear "not configured" error rather
    # than crashing. ``artwork_generation_enabled`` is a manual kill-switch
    # independent of the key (e.g. to pause a working integration).
    openai_api_key: str | None = None
    artwork_generation_enabled: bool = True

    # Release identifiers (US-13.4). ISRC = country code + registrant code issued
    # by the platform operator's national agency; UPC = the operator's 7-digit GS1
    # company prefix. The defaults are demo placeholders ("US"/"A1B"/"0000000") so
    # codes are well-formed out of the box; a production deployment overrides them
    # with its own registered allocations via the environment.
    isrc_country_code: str = "US"
    isrc_registrant_code: str = "A1B"
    upc_prefix: str = "0000000"

    # Audio streaming rate limit (US-14.2). The /clips/{id}/stream endpoint is
    # public for public clips, so it is rate-limited per client IP to curb abuse.
    # In-memory fixed window; raise via the environment for higher-traffic
    # deployments (swap for a shared store if the API runs multiple workers).
    stream_rate_limit_per_minute: int = Field(default=100, ge=1)

    # Reverse proxies whose forwarded client-IP header the limiter trusts (#283).
    # A same-origin BFF proxy calls the backend server-side, so every visitor
    # arrives as the proxy's egress IP and the per-IP limiter collapses to one
    # shared bucket. Listing the proxy's IP here lets the limiter key on the
    # real client from its X-Forwarded-For instead. Empty by default: trust
    # nobody, so a directly-reachable backend can't be evaded with a spoofed
    # header (the header is only honored when the peer is a listed proxy).
    trusted_proxies: Annotated[list[str], NoDecode] = []

    # Compute status endpoint (US-11.4). Per-target health-probe budget for
    # ``GET /api/v1/compute/status``; the local and remote checks run in parallel,
    # each bounded by this timeout, so the aggregate response stays well under the
    # issue's 5-second ceiling even when one target hangs. Bounded ``< 5`` so a
    # misconfiguration fails at startup rather than silently breaking that ceiling.
    compute_status_timeout: float = Field(default=3.0, gt=0, lt=5.0)

    @property
    def runpod_enabled(self) -> bool:
        """True only when both RunPod credentials are configured (remote routing is usable)."""
        return bool(self.runpod_api_key and self.runpod_endpoint_id)

    @property
    def dolby_enabled(self) -> bool:
        """True only when both Dolby.io credentials are configured (mastering is usable)."""
        return bool(self.dolby_api_key and self.dolby_api_secret)

    @property
    def landr_enabled(self) -> bool:
        """True only when both LANDR B2B credentials are configured."""
        return bool(self.landr_api_key and self.landr_api_secret)

    @property
    def bakuage_enabled(self) -> bool:
        """True only when the Bakuage API key is configured."""
        return bool(self.bakuage_api_key)

    @property
    def artwork_enabled(self) -> bool:
        """True only when artwork generation is configured and not kill-switched."""
        return bool(self.openai_api_key and self.artwork_generation_enabled)

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

    @field_validator("local_url")
    @classmethod
    def _check_local_url(cls, value: str) -> str:
        """Reject a malformed local_url at startup, not at probe time.

        Without a scheme/host the availability probe would raise an
        ``httpx.InvalidURL`` (not an ``httpx.HTTPError``, so it escapes the
        probe's catch) and surface as a 500. Validating here turns a
        misconfiguration into a clear startup error instead.
        """
        parsed = urlsplit(value.strip())
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError(f"local_url {value!r} must be an absolute http(s):// URL")
        return value.strip()

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

    @field_validator("isrc_country_code")
    @classmethod
    def _check_isrc_country_code(cls, value: str) -> str:
        """ISRC country code is exactly two uppercase letters (US-13.4).

        Validated here so a misconfiguration fails at startup, not silently at
        mint time as a malformed ISRC the generator can't reject.
        """
        if not re.fullmatch(r"[A-Z]{2}", value):
            raise ValueError(f"isrc_country_code {value!r} must be exactly two uppercase letters")
        return value

    @field_validator("isrc_registrant_code")
    @classmethod
    def _check_isrc_registrant_code(cls, value: str) -> str:
        """ISRC registrant code is exactly three uppercase alphanumerics (US-13.4)."""
        if not re.fullmatch(r"[A-Z0-9]{3}", value):
            raise ValueError(f"isrc_registrant_code {value!r} must be exactly three uppercase alphanumerics")
        return value

    @field_validator("upc_prefix")
    @classmethod
    def _check_upc_prefix(cls, value: str) -> str:
        """GS1 company prefix is exactly seven digits, so prefix + 5-digit item +
        check digit form a valid 13-digit EAN-13 (US-13.4)."""
        if not re.fullmatch(r"\d{7}", value):
            raise ValueError(f"upc_prefix {value!r} must be exactly seven digits")
        return value

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

    @property
    def trusted_proxy_set(self) -> frozenset[str]:
        """Trusted-proxy IPs as a set for O(1) membership in the limiter."""
        return frozenset(self.trusted_proxies)

    @field_validator("trusted_proxies", mode="before")
    @classmethod
    def _split_trusted_proxies(cls, value: object) -> object:
        """Accept a comma-separated string; blank/unset -> [] (trust nobody)."""
        if isinstance(value, str):
            return [ip.strip() for ip in value.split(",") if ip.strip()]
        return value

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
