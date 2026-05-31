"""API configuration via pydantic-settings (US-8.1).

Distinct from the CLI's :mod:`acemusic.config` (which serves the ACE-Step client).
All API settings are namespaced under the ``ACEMUSIC_API_`` env prefix so they do
not collide with CLI or ACE-Step server variables.
"""

from typing import Annotated

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEFAULT_CORS_ORIGINS = ["http://localhost:3000", "http://localhost:8000"]


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
