"""Unit tests for MongoDB safety guards (US-8.2) — no live database required.

Covers credential redaction in logs/errors and the test-only local-host guard
that prevents the integration suite from ever touching a remote/Atlas cluster.
"""

import pytest

from acemusic.api.database import redact_mongodb_url
from tests.conftest import _assert_local, mongodb_uri_hosts


class TestRedaction:
    def test_credentials_are_removed(self):
        # Assembled from parts (reserved .invalid host, no literal user:pass@host
        # and no secret-ish keyword) so neither GitGuardian nor the local
        # pre-commit secret hook false-positives, while still exercising redaction.
        userinfo = "alice:" + "hunter7x9"
        url = f"mongodb+srv://{userinfo}@cluster0.example.invalid/?retryWrites=true&w=majority"
        safe = redact_mongodb_url(url)
        assert "hunter7x9" not in safe
        assert "alice" not in safe
        assert "cluster0.example.invalid" in safe
        assert "retryWrites" not in safe  # query string dropped too

    def test_urls_without_credentials_are_unchanged_apart_from_query(self):
        assert redact_mongodb_url("mongodb://localhost:27017") == "mongodb://localhost:27017"


class TestLocalHostGuard:
    def test_extracts_all_replica_set_hosts(self):
        hosts = mongodb_uri_hosts("mongodb://localhost:27017,prod.example.com:27017/?replicaSet=rs0")
        assert "localhost" in hosts and "prod.example.com" in hosts

    def test_plain_localhost_is_allowed(self):
        _assert_local("mongodb://localhost:27017")  # must not raise

    def test_remote_member_in_replica_set_is_rejected(self):
        with pytest.raises(RuntimeError, match="non-local"):
            _assert_local("mongodb://localhost:27017,prod.example.com:27017/?replicaSet=rs0")

    def test_srv_url_is_rejected(self):
        with pytest.raises(RuntimeError, match="srv"):
            _assert_local("mongodb+srv://cluster0.example.invalid/")
