"""Tests for the file storage abstraction layer (US-8.5).

Covers LocalStorage (real filesystem via tmp_path), S3Storage (boto3 mocked),
and the get_storage_backend() factory.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# A canonical key following the documented convention:
# {user_id}/{workspace_id}/clips/{clip_id}.{format}
SAMPLE_KEY = "user123/ws456/clips/clip789.mp3"


# ---------------------------------------------------------------------------
# LocalStorage
# ---------------------------------------------------------------------------


class TestLocalStorage:
    def _backend(self, tmp_path: Path):
        from acemusic.storage import LocalStorage

        return LocalStorage(root_dir=tmp_path)

    def test_upload_creates_file_with_content(self, tmp_path: Path):
        backend = self._backend(tmp_path)
        backend.upload(SAMPLE_KEY, b"audio-bytes")

        written = tmp_path / SAMPLE_KEY
        assert written.exists()
        assert written.read_bytes() == b"audio-bytes"

    def test_upload_creates_nested_parent_dirs(self, tmp_path: Path):
        backend = self._backend(tmp_path)
        backend.upload("a/b/c/d/file.bin", b"x")
        assert (tmp_path / "a/b/c/d/file.bin").read_bytes() == b"x"

    def test_download_returns_bytes(self, tmp_path: Path):
        backend = self._backend(tmp_path)
        backend.upload(SAMPLE_KEY, b"hello-world")
        assert backend.download(SAMPLE_KEY) == b"hello-world"

    def test_download_missing_raises(self, tmp_path: Path):
        backend = self._backend(tmp_path)
        with pytest.raises(FileNotFoundError):
            backend.download("does/not/exist.mp3")

    def test_delete_removes_existing_file(self, tmp_path: Path):
        backend = self._backend(tmp_path)
        backend.upload(SAMPLE_KEY, b"data")
        backend.delete(SAMPLE_KEY)
        assert not (tmp_path / SAMPLE_KEY).exists()

    def test_delete_missing_is_silent(self, tmp_path: Path):
        backend = self._backend(tmp_path)
        # Should not raise.
        backend.delete("never/created.mp3")

    def test_get_url_returns_absolute_path(self, tmp_path: Path):
        backend = self._backend(tmp_path)
        backend.upload(SAMPLE_KEY, b"data")
        url = backend.get_url(SAMPLE_KEY)
        assert url == str((tmp_path / SAMPLE_KEY).resolve())

    @pytest.mark.parametrize(
        "evil_key",
        ["../escape.bin", "a/../../escape.bin", "/etc/passwd", "user/../../../../tmp/x"],
    )
    def test_keys_escaping_root_are_rejected(self, tmp_path: Path, evil_key: str):
        from acemusic.storage import StorageError

        backend = self._backend(tmp_path)
        with pytest.raises(StorageError, match="escapes root"):
            backend.upload(evil_key, b"data")
        with pytest.raises(StorageError, match="escapes root"):
            backend.download(evil_key)
        with pytest.raises(StorageError, match="escapes root"):
            backend.delete(evil_key)
        with pytest.raises(StorageError, match="escapes root"):
            backend.get_url(evil_key)

    @pytest.mark.parametrize("empty_key", ["", "   "])
    def test_empty_key_is_rejected(self, tmp_path: Path, empty_key: str):
        from acemusic.storage import StorageError

        backend = self._backend(tmp_path)
        with pytest.raises(StorageError, match="non-empty"):
            backend.upload(empty_key, b"data")

    @pytest.mark.parametrize("root_key", [".", "clips/.."])
    def test_root_referencing_key_is_rejected(self, tmp_path: Path, root_key: str):
        from acemusic.storage import StorageError

        backend = self._backend(tmp_path)
        with pytest.raises(StorageError, match="must reference a file"):
            backend.upload(root_key, b"data")

    def test_path_convention_round_trip(self, tmp_path: Path):
        backend = self._backend(tmp_path)
        backend.upload(SAMPLE_KEY, b"round-trip")
        assert backend.download(SAMPLE_KEY) == b"round-trip"
        # Stored under the exact convention path.
        assert (tmp_path / "user123" / "ws456" / "clips" / "clip789.mp3").exists()


# ---------------------------------------------------------------------------
# S3Storage (boto3 mocked)
# ---------------------------------------------------------------------------


class TestS3Storage:
    def _backend_and_client(self, **kwargs):
        """Build an S3Storage with boto3 patched; return (backend, mock_client)."""
        from acemusic import storage

        mock_client = MagicMock()
        mock_boto3 = MagicMock()
        mock_boto3.client.return_value = mock_client
        params = {"bucket": "my-bucket", "region": "us-east-1"}
        params.update(kwargs)
        with patch.object(storage, "boto3", mock_boto3):
            backend = storage.S3Storage(**params)
        return backend, mock_client, mock_boto3

    def test_upload_calls_put_object(self):
        backend, client, _ = self._backend_and_client()
        backend.upload(SAMPLE_KEY, b"audio")
        client.put_object.assert_called_once()
        kwargs = client.put_object.call_args.kwargs
        assert kwargs["Bucket"] == "my-bucket"
        assert kwargs["Key"] == SAMPLE_KEY
        assert kwargs["Body"] == b"audio"

    def test_upload_sets_content_type_from_extension(self):
        backend, client, _ = self._backend_and_client()
        backend.upload(SAMPLE_KEY, b"audio")  # .mp3
        assert client.put_object.call_args.kwargs["ContentType"] == "audio/mpeg"

    def test_upload_unknown_extension_falls_back_to_octet_stream(self):
        backend, client, _ = self._backend_and_client()
        backend.upload("user/ws/clips/clip.weirdext", b"x")
        assert client.put_object.call_args.kwargs["ContentType"] == "application/octet-stream"

    def test_download_returns_body_bytes(self):
        backend, client, _ = self._backend_and_client()
        body = MagicMock()
        body.read.return_value = b"downloaded"
        client.get_object.return_value = {"Body": body}
        assert backend.download(SAMPLE_KEY) == b"downloaded"
        client.get_object.assert_called_once_with(Bucket="my-bucket", Key=SAMPLE_KEY)

    def test_download_missing_key_raises_file_not_found(self):
        backend, client, _ = self._backend_and_client()
        err = Exception("not found")
        err.response = {"Error": {"Code": "NoSuchKey"}}  # type: ignore[attr-defined]
        client.get_object.side_effect = err
        with pytest.raises(FileNotFoundError):
            backend.download(SAMPLE_KEY)

    def test_download_other_client_error_propagates(self):
        backend, client, _ = self._backend_and_client()
        err = Exception("access denied")
        err.response = {"Error": {"Code": "AccessDenied"}}  # type: ignore[attr-defined]
        client.get_object.side_effect = err
        with pytest.raises(Exception, match="access denied"):
            backend.download(SAMPLE_KEY)

    def test_download_missing_bucket_does_not_look_like_a_miss(self):
        # A misconfigured/deleted bucket must surface loudly, not as FileNotFoundError.
        backend, client, _ = self._backend_and_client()
        err = Exception("bucket gone")
        err.response = {"Error": {"Code": "NoSuchBucket"}}  # type: ignore[attr-defined]
        client.get_object.side_effect = err
        with pytest.raises(Exception, match="bucket gone") as exc_info:
            backend.download(SAMPLE_KEY)
        assert not isinstance(exc_info.value, FileNotFoundError)

    def test_download_non_client_error_propagates(self):
        # An exception with no ``response`` attribute is not an S3 not-found.
        backend, client, _ = self._backend_and_client()
        client.get_object.side_effect = RuntimeError("network down")
        with pytest.raises(RuntimeError, match="network down"):
            backend.download(SAMPLE_KEY)

    def test_delete_calls_delete_object(self):
        backend, client, _ = self._backend_and_client()
        backend.delete(SAMPLE_KEY)
        client.delete_object.assert_called_once_with(Bucket="my-bucket", Key=SAMPLE_KEY)

    def test_get_url_generates_presigned_url_with_expiry(self):
        backend, client, _ = self._backend_and_client(url_expiry=900)
        client.generate_presigned_url.return_value = "https://signed.example/url"
        url = backend.get_url(SAMPLE_KEY)
        assert url == "https://signed.example/url"
        kwargs = client.generate_presigned_url.call_args.kwargs
        assert kwargs["ExpiresIn"] == 900
        assert kwargs["Params"] == {"Bucket": "my-bucket", "Key": SAMPLE_KEY}

    def test_prefix_is_prepended_to_key(self):
        backend, client, _ = self._backend_and_client(prefix="staging")
        backend.upload(SAMPLE_KEY, b"audio")
        assert client.put_object.call_args.kwargs["Key"] == f"staging/{SAMPLE_KEY}"

    def test_endpoint_url_forwarded_to_client(self):
        _, _, mock_boto3 = self._backend_and_client(endpoint_url="http://minio:9000")
        kwargs = mock_boto3.client.call_args.kwargs
        assert kwargs["endpoint_url"] == "http://minio:9000"
        assert kwargs["region_name"] == "us-east-1"

    def test_raises_clear_error_when_boto3_missing(self):
        from acemusic import storage

        with patch.object(storage, "boto3", None):
            with pytest.raises(storage.StorageError, match="boto3"):
                storage.S3Storage(bucket="my-bucket")


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


class TestGetStorageBackend:
    def test_returns_local_storage(self, monkeypatch, tmp_path: Path):
        from acemusic import storage
        from acemusic.storage import LocalStorage

        monkeypatch.setenv("ACEMUSIC_STORAGE_BACKEND", "local")
        monkeypatch.setenv("ACEMUSIC_STORAGE_LOCAL_ROOT", str(tmp_path))
        backend = storage.get_storage_backend()
        assert isinstance(backend, LocalStorage)

    def test_returns_s3_storage(self, monkeypatch):
        from acemusic import storage
        from acemusic.storage import S3Storage

        monkeypatch.setenv("ACEMUSIC_STORAGE_BACKEND", "s3")
        monkeypatch.setenv("ACEMUSIC_S3_BUCKET", "prod-bucket")
        with patch.object(storage, "boto3", MagicMock()):
            backend = storage.get_storage_backend()
        assert isinstance(backend, S3Storage)

    def test_s3_without_bucket_raises_storage_error(self, monkeypatch):
        from acemusic import storage

        monkeypatch.setenv("ACEMUSIC_STORAGE_BACKEND", "s3")
        monkeypatch.delenv("ACEMUSIC_S3_BUCKET", raising=False)
        with patch.object(storage, "boto3", MagicMock()):
            with pytest.raises(storage.StorageError, match="ACEMUSIC_S3_BUCKET"):
                storage.get_storage_backend()

    def test_unknown_backend_raises_storage_error(self, monkeypatch):
        from acemusic import storage

        monkeypatch.setenv("ACEMUSIC_STORAGE_BACKEND", "ftp")
        with pytest.raises(storage.StorageError, match="ftp"):
            storage.get_storage_backend()

    def test_default_backend_is_local(self, monkeypatch):
        from acemusic import storage
        from acemusic.storage import LocalStorage

        monkeypatch.delenv("ACEMUSIC_STORAGE_BACKEND", raising=False)
        backend = storage.get_storage_backend()
        assert isinstance(backend, LocalStorage)


# ---------------------------------------------------------------------------
# Storage configuration (US-8.5)
# ---------------------------------------------------------------------------


class TestStorageConfig:
    def test_invalid_url_expiry_raises_clear_error(self, monkeypatch):
        from acemusic.config import load_config

        monkeypatch.setenv("ACEMUSIC_S3_URL_EXPIRY", "not-a-number")
        with pytest.raises(ValueError, match="ACEMUSIC_S3_URL_EXPIRY"):
            load_config()

    def test_non_positive_url_expiry_raises(self, monkeypatch):
        from acemusic.config import load_config

        monkeypatch.setenv("ACEMUSIC_S3_URL_EXPIRY", "0")
        with pytest.raises(ValueError, match="positive"):
            load_config()

    def test_env_overrides_and_defaults(self, monkeypatch):
        from acemusic.config import load_config

        monkeypatch.setenv("ACEMUSIC_STORAGE_BACKEND", "s3")
        monkeypatch.setenv("ACEMUSIC_S3_BUCKET", "b")
        monkeypatch.setenv("ACEMUSIC_S3_URL_EXPIRY", "120")
        config = load_config()
        assert config.storage_backend == "s3"
        assert config.s3_bucket == "b"
        assert config.s3_url_expiry == 120
