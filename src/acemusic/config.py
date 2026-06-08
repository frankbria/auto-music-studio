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
    # File storage abstraction (US-8.5). Selects which StorageBackend the factory
    # builds; "local" or "s3". Validated by get_storage_backend(), not here.
    storage_backend: str = "local"
    storage_local_root: str | None = None
    s3_bucket: str | None = None
    s3_prefix: str | None = None
    s3_region: str | None = None
    s3_endpoint_url: str | None = None
    s3_url_expiry: int = 3600


def _parse_url_expiry(env_value: str | None, yaml_value: object) -> int:
    """Resolve ACEMUSIC_S3_URL_EXPIRY (env > yaml > default), validating it.

    Raises ValueError with a clear message for non-integer or non-positive
    values rather than letting a bare ``int()`` failure surface later.
    """
    raw: object = env_value if env_value is not None else yaml_value
    if raw is None:
        return 3600
    try:
        expiry = int(raw)
    except (TypeError, ValueError):
        raise ValueError(f"ACEMUSIC_S3_URL_EXPIRY must be an integer, got {raw!r}") from None
    if expiry <= 0:
        raise ValueError(f"ACEMUSIC_S3_URL_EXPIRY must be a positive number of seconds, got {expiry}")
    return expiry


def load_config() -> AceConfig:
    """Load configuration from env vars, .env file, and ~/.acemusic/config.yaml."""
    # Load .env without overriding already-set env vars
    load_dotenv(override=False)

    api_url = os.environ.get("ACEMUSIC_BASE_URL") or None
    api_key = os.environ.get("ACEMUSIC_API_KEY") or None
    output_dir: str | None = None
    yaml_default_model: str | None = None
    yaml_backend: str | None = None
    # Storage settings honour the same env > .env > config.yaml precedence as the
    # rest of this module; collect any YAML values here as fallbacks.
    yaml_storage: dict[str, object] = {}

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
            for key in (
                "storage_backend",
                "storage_local_root",
                "s3_bucket",
                "s3_prefix",
                "s3_region",
                "s3_endpoint_url",
                "s3_url_expiry",
            ):
                if data.get(key) is not None:
                    yaml_storage[key] = data[key]
        except Exception as exc:
            logger.warning("Failed to read config file %s: %s", yaml_path, exc)

    elevenlabs_api_key = os.environ.get("ELEVENLABS_API_KEY") or None
    elevenlabs_output_format = os.environ.get("ELEVENLABS_OUTPUT_FORMAT") or "mp3_44100_128"
    default_model: str | None = os.environ.get("ACEMUSIC_DEFAULT_MODEL") or yaml_default_model or None
    backend: str | None = os.environ.get("ACEMUSIC_BACKEND") or yaml_backend or None

    # Storage abstraction (US-8.5). Precedence: env > config.yaml > default.
    storage_backend = os.environ.get("ACEMUSIC_STORAGE_BACKEND") or yaml_storage.get("storage_backend") or "local"
    storage_local_root = os.environ.get("ACEMUSIC_STORAGE_LOCAL_ROOT") or yaml_storage.get("storage_local_root") or None
    s3_bucket = os.environ.get("ACEMUSIC_S3_BUCKET") or yaml_storage.get("s3_bucket") or None
    s3_prefix = os.environ.get("ACEMUSIC_S3_PREFIX") or yaml_storage.get("s3_prefix") or None
    s3_region = os.environ.get("ACEMUSIC_S3_REGION") or yaml_storage.get("s3_region") or None
    s3_endpoint_url = os.environ.get("ACEMUSIC_S3_ENDPOINT_URL") or yaml_storage.get("s3_endpoint_url") or None
    s3_url_expiry = _parse_url_expiry(os.environ.get("ACEMUSIC_S3_URL_EXPIRY"), yaml_storage.get("s3_url_expiry"))

    return AceConfig(
        api_url=api_url,
        api_key=api_key,
        output_dir=output_dir,
        elevenlabs_api_key=elevenlabs_api_key,
        elevenlabs_output_format=elevenlabs_output_format,
        default_model=default_model,
        backend=backend,
        storage_backend=storage_backend,
        storage_local_root=storage_local_root,
        s3_bucket=s3_bucket,
        s3_prefix=s3_prefix,
        s3_region=s3_region,
        s3_endpoint_url=s3_endpoint_url,
        s3_url_expiry=s3_url_expiry,
    )
