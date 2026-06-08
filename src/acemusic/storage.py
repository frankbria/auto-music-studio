"""File storage abstraction (US-8.5).

A single interface over local-filesystem (development) and S3-compatible
(production) storage, so audio-file operations are deployment-agnostic.

Keys follow the convention::

    {user_id}/{workspace_id}/clips/{clip_id}.{format}

Select a backend with ``ACEMUSIC_STORAGE_BACKEND=local|s3`` and build one via
:func:`get_storage_backend`; callers never instantiate a concrete backend.
"""

from __future__ import annotations

import mimetypes
from abc import ABC, abstractmethod
from pathlib import Path

from .config import load_config

# S3 error codes that mean "this object does not exist"; normalised to
# FileNotFoundError so callers handle a miss identically across backends.
# NoSuchBucket is deliberately excluded: a missing/misconfigured bucket is a
# backend configuration failure and must surface loudly, not look like a miss.
_S3_NOT_FOUND_CODES = {"NoSuchKey", "404"}

# boto3 is an optional dependency (the ``s3`` extra). Guard the import so the
# module stays usable with only LocalStorage; S3Storage raises if it is missing.
try:
    import boto3
except ImportError:  # pragma: no cover - exercised via patched sentinel in tests
    boto3 = None  # type: ignore[assignment]


class StorageError(Exception):
    """Raised when a storage operation cannot be performed."""


def _validate_key(path: str) -> str:
    """Reject empty/whitespace keys so every backend honours one key contract."""
    if not path or not path.strip():
        raise StorageError("Storage key must be a non-empty path")
    return path


def _s3_error_code(exc: Exception) -> str | None:
    """Extract the S3 error code from a boto3 ClientError without importing it.

    boto3 is optional, so we duck-type ``exc.response["Error"]["Code"]`` rather
    than depending on ``botocore.exceptions.ClientError`` at import time.
    """
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        code = response.get("Error", {}).get("Code")
        return str(code) if code is not None else None
    return None


class StorageBackend(ABC):
    """Common interface for file storage backends.

    Implementations operate on ``path`` keys of the form
    ``{user_id}/{workspace_id}/clips/{clip_id}.{format}``.
    """

    @abstractmethod
    def upload(self, path: str, data: bytes) -> None:
        """Store ``data`` at ``path``, overwriting any existing object."""

    @abstractmethod
    def download(self, path: str) -> bytes:
        """Return the bytes stored at ``path``; raise if it does not exist."""

    @abstractmethod
    def delete(self, path: str) -> None:
        """Remove ``path``. Missing objects are not an error (idempotent)."""

    @abstractmethod
    def get_url(self, path: str) -> str:
        """Return a retrievable URL/location for ``path``."""


class LocalStorage(StorageBackend):
    """Store files on the local filesystem under ``root_dir``."""

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = Path(root_dir).resolve()

    def _full_path(self, path: str) -> Path:
        # Resolve the key against the root and reject anything that escapes it
        # (absolute paths, ``..`` traversal, or an empty key that resolves to the
        # root itself). Keys derive from user/workspace identifiers, so this
        # guards against path-traversal access.
        _validate_key(path)
        target = (self.root_dir / path).resolve()
        if target != self.root_dir and not target.is_relative_to(self.root_dir):
            raise StorageError(f"Storage key escapes root directory: {path!r}")
        if target == self.root_dir:
            raise StorageError(f"Storage key must reference a file, not the root: {path!r}")
        return target

    def upload(self, path: str, data: bytes) -> None:
        target = self._full_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def download(self, path: str) -> bytes:
        return self._full_path(path).read_bytes()

    def delete(self, path: str) -> None:
        self._full_path(path).unlink(missing_ok=True)

    def get_url(self, path: str) -> str:
        return str(self._full_path(path).resolve())


class S3Storage(StorageBackend):
    """Store files in an S3-compatible bucket via boto3.

    Works with AWS S3, MinIO, and Backblaze B2 by passing ``endpoint_url``.
    Authentication uses boto3's default credential chain (env vars, shared
    config, IAM roles); credentials are never read from app config.
    """

    def __init__(
        self,
        bucket: str,
        prefix: str | None = None,
        region: str | None = None,
        endpoint_url: str | None = None,
        url_expiry: int = 3600,
    ) -> None:
        if boto3 is None:
            raise StorageError("S3Storage requires boto3. Install the 's3' extra: pip install 'acemusic[s3]'")
        self.bucket = bucket
        self.prefix = prefix
        self.url_expiry = url_expiry
        self.client = boto3.client(
            "s3",
            region_name=region,
            endpoint_url=endpoint_url,
        )

    def _key(self, path: str) -> str:
        _validate_key(path)
        if self.prefix:
            return f"{self.prefix.rstrip('/')}/{path}"
        return path

    def upload(self, path: str, data: bytes) -> None:
        # Derive ContentType from the key extension so presigned URLs served to
        # browsers/CDNs get the right type instead of binary/octet-stream.
        content_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
        self.client.put_object(Bucket=self.bucket, Key=self._key(path), Body=data, ContentType=content_type)

    def download(self, path: str) -> bytes:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=self._key(path))
        except Exception as exc:  # noqa: BLE001 - inspected and re-raised below
            if _s3_error_code(exc) in _S3_NOT_FOUND_CODES:
                raise FileNotFoundError(path) from exc
            raise
        return response["Body"].read()

    def delete(self, path: str) -> None:
        # The S3 DeleteObject API is already idempotent for missing keys.
        self.client.delete_object(Bucket=self.bucket, Key=self._key(path))

    def get_url(self, path: str) -> str:
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": self._key(path)},
            ExpiresIn=self.url_expiry,
        )


def get_storage_backend() -> StorageBackend:
    """Build the configured storage backend.

    Reads ``ACEMUSIC_STORAGE_BACKEND`` (and the ``ACEMUSIC_S3_*`` /
    ``ACEMUSIC_STORAGE_LOCAL_ROOT`` settings) via :func:`load_config`. Callers
    depend only on :class:`StorageBackend`, so switching backends needs no
    code changes.

    Builds a fresh backend on every call (constructing an S3 client is not free).
    Callers on a hot path should hold onto the returned instance and reuse it
    rather than calling this repeatedly.
    """
    config = load_config()
    backend = config.storage_backend

    if backend == "local":
        root = Path(config.storage_local_root) if config.storage_local_root else Path.cwd() / "storage"
        return LocalStorage(root_dir=root)

    if backend == "s3":
        if not config.s3_bucket:
            raise StorageError("ACEMUSIC_S3_BUCKET must be set when ACEMUSIC_STORAGE_BACKEND=s3")
        return S3Storage(
            bucket=config.s3_bucket,
            prefix=config.s3_prefix,
            region=config.s3_region,
            endpoint_url=config.s3_endpoint_url,
            url_expiry=config.s3_url_expiry,
        )

    raise StorageError(f"Unknown ACEMUSIC_STORAGE_BACKEND: {backend!r} (expected 'local' or 's3')")
