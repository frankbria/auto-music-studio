"""API configuration via pydantic-settings (US-8.1).

Distinct from the CLI's :mod:`acemusic.config` (which serves the ACE-Step client).
All API settings are namespaced under the ``ACEMUSIC_API_`` env prefix so they do
not collide with CLI or ACE-Step server variables.
"""

from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEFAULT_CORS_ORIGINS = ["http://localhost:3000", "http://localhost:8000"]


class ApiSettings(BaseSettings):
    """Runtime configuration for the FastAPI service."""

    model_config = SettingsConfigDict(
        env_prefix="ACEMUSIC_API_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # NoDecode disables pydantic-settings' default JSON decoding so the env value
    # can be a friendly comma-separated string (e.g. "https://a.com,https://b.com")
    # rather than a JSON array. The validator below does the splitting.
    cors_allow_origins: Annotated[list[str], NoDecode] = DEFAULT_CORS_ORIGINS

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Accept a comma-separated string or an already-parsed list."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value
