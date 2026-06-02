"""Configuration loading for acemusic (US-2.1).

Priority: env vars > .env file > ~/.acemusic/config.yaml
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)


@dataclass
class AceConfig:
    """Application configuration holding the ACE-Step server URL and optional API key."""

    api_url: str | None
    api_key: str | None
    output_dir: str | None = None
    elevenlabs_api_key: str | None = None
    elevenlabs_output_format: str = "mp3_44100_128"
    # Loaded from ACEMUSIC_DEFAULT_MODEL env var or `default_model` in config.yaml.
    # Not validated at load time; invalid values are caught by generate() at runtime.
    default_model: str | None = None
    # Default backend (auto|ace-step|elevenlabs) from ACEMUSIC_BACKEND env or
    # `backend` in config.yaml. None means "unset" → resolver falls back to auto.
    # Not validated here; resolve_backend() validates and reports bad values.
    backend: str | None = None


def load_config() -> AceConfig:
    """Load configuration from env vars, .env file, and ~/.acemusic/config.yaml."""
    # Load .env without overriding already-set env vars
    load_dotenv(override=False)

    api_url = os.environ.get("ACEMUSIC_BASE_URL") or None
    api_key = os.environ.get("ACEMUSIC_API_KEY") or None
    output_dir: str | None = None
    yaml_default_model: str | None = None

    # Read ~/.acemusic/config.yaml — always load for output_dir; only fill
    # api_url/api_key from it when the env vars are absent.
    yaml_path = Path.home() / ".acemusic" / "config.yaml"
    if yaml_path.exists():
        import yaml

        try:
            data = yaml.safe_load(yaml_path.read_text()) or {}
            if not api_url:
                api_url = data.get("api_url") or data.get("ACEMUSIC_BASE_URL") or None
            if not api_key:
                api_key = data.get("api_key") or data.get("ACEMUSIC_API_KEY") or None
            output_dir = data.get("output_dir") or None
            yaml_default_model = data.get("default_model") or None
            yaml_backend = data.get("backend") or None
        except Exception as exc:
            logger.warning("Failed to read config file %s: %s", yaml_path, exc)
            yaml_backend = None
    else:
        yaml_backend = None

    elevenlabs_api_key = os.environ.get("ELEVENLABS_API_KEY") or None
    elevenlabs_output_format = os.environ.get("ELEVENLABS_OUTPUT_FORMAT") or "mp3_44100_128"
    default_model: str | None = os.environ.get("ACEMUSIC_DEFAULT_MODEL") or yaml_default_model or None
    backend: str | None = os.environ.get("ACEMUSIC_BACKEND") or yaml_backend or None

    return AceConfig(
        api_url=api_url,
        api_key=api_key,
        output_dir=output_dir,
        elevenlabs_api_key=elevenlabs_api_key,
        elevenlabs_output_format=elevenlabs_output_format,
        default_model=default_model,
        backend=backend,
    )
