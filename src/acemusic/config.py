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


def load_config() -> AceConfig:
    """Load configuration from env vars, .env file, and ~/.acemusic/config.yaml."""
    # Load .env without overriding already-set env vars
    load_dotenv(override=False)

    api_url = os.environ.get("ACEMUSIC_BASE_URL") or None
    api_key = os.environ.get("ACEMUSIC_API_KEY") or None
    output_dir: str | None = None

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
        except Exception as exc:
            logger.warning("Failed to read config file %s: %s", yaml_path, exc)

    return AceConfig(api_url=api_url, api_key=api_key, output_dir=output_dir)
