"""Structured logs with request ids, and error tracking (US-28.5, #342)."""

import json
import logging

import pytest
import sentry_sdk
from fastapi.testclient import TestClient

from acemusic.api import observability
from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.settings import ApiSettings

SECRET = "test-secret-key-at-least-32-bytes-long-xx"
NOWHERE = f"{API_V1_PREFIX}/no-such-route"


def _settings(**fields) -> ApiSettings:
    return ApiSettings(_env_file=None, jwt_secret_key=SECRET, job_processor_enabled=False, **fields)


@pytest.fixture
def client() -> TestClient:
    app = create_app(_settings())

    async def crash() -> None:
        logging.getLogger("acemusic.test").warning("about to fail")
        raise RuntimeError("boom")

    app.add_api_route("/test/crash", crash)
    return TestClient(app, raise_server_exceptions=False)


def test_every_response_carries_a_generated_request_id(client) -> None:
    first, second = client.get(NOWHERE), client.get(NOWHERE)

    assert len(first.headers["x-request-id"]) == 32
    assert first.headers["x-request-id"] != second.headers["x-request-id"]


def test_a_well_formed_incoming_id_is_kept_and_anything_else_replaced(client) -> None:
    kept = client.get(NOWHERE, headers={"X-Request-ID": "edge-abc12345"})
    replaced = client.get(NOWHERE, headers={"X-Request-ID": "has spaces <script>"})

    assert kept.headers["x-request-id"] == "edge-abc12345"
    assert replaced.headers["x-request-id"] != "has spaces <script>"


def test_an_id_with_a_trailing_newline_is_replaced() -> None:
    assert observability._SAFE_REQUEST_ID.fullmatch("edge-abc12345\n") is None


def test_extra_fields_cannot_overwrite_the_core_keys() -> None:
    record = logging.LogRecord("acemusic.x", logging.INFO, __file__, 1, "real", None, None)
    record.fields = {"message": "forged", "level": "DEBUG", "path": "/x"}

    line = json.loads(observability.JsonFormatter().format(record))

    assert (line["message"], line["level"], line["path"]) == ("real", "INFO", "/x")


def test_a_500_quotes_the_request_id_and_its_log_lines_carry_it(client, caplog) -> None:
    with caplog.at_level(logging.INFO):
        resp = client.get("/test/crash", headers={"X-Request-ID": "trace-0001-abcd"})

    assert "trace-0001-abcd" in resp.json()["detail"]
    # The test client's own httpx lines are outside the app, so they rightly carry no id.
    lines = [
        json.loads(observability.JsonFormatter().format(r)) for r in caplog.records if r.name.startswith("acemusic")
    ]
    assert {line.get("request_id") for line in lines} == {"trace-0001-abcd"}
    assert any(line["message"] == "about to fail" for line in lines)
    assert any("RuntimeError: boom" in line.get("exc", "") for line in lines)
    [access] = [line for line in lines if line["logger"] == "acemusic.access"]
    assert (access["method"], access["path"], access["status"]) == ("GET", "/test/crash", 500)


def test_a_signed_in_request_logs_its_user(caplog) -> None:
    settings = _settings()
    client = TestClient(create_app(settings))
    token = create_access_token(user_id="u-42", email="u@example.com", subscription_tier="free", settings=settings)

    with caplog.at_level(logging.INFO):
        client.get(NOWHERE, headers={"Authorization": f"Bearer {token}"})

    [access] = [r for r in caplog.records if r.name == "acemusic.access"]
    assert json.loads(observability.JsonFormatter().format(access))["user_id"] == "u-42"


def test_a_line_outside_any_request_has_no_ids() -> None:
    record = logging.LogRecord("acemusic.x", logging.INFO, __file__, 1, "started", None, None)

    line = json.loads(observability.JsonFormatter().format(record))

    assert line["message"] == "started" and line["level"] == "INFO"
    assert "request_id" not in line and "user_id" not in line


def test_the_log_level_is_checked_and_case_insensitive() -> None:
    assert _settings(log_level="warning").log_level == "WARNING"
    assert _settings(log_level="critical").log_level == "CRITICAL"
    with pytest.raises(ValueError):
        _settings(log_level="info2")


class TestErrorTracking:
    def test_off_without_a_dsn(self, monkeypatch) -> None:
        calls = []
        monkeypatch.setattr(sentry_sdk, "init", lambda **kw: calls.append(kw))

        observability.configure_error_tracking(_settings())

        assert calls == []

    def test_an_unhandled_error_reaches_sentry_tagged_with_its_request_id(self, monkeypatch) -> None:
        events: list[dict] = []
        real_init = sentry_sdk.init
        # A plain function transport receives each event as a dict.
        monkeypatch.setattr(sentry_sdk, "init", lambda **kw: real_init(**kw, transport=events.append))
        app = create_app(_settings(sentry_dsn="https://key@o1.ingest.sentry.io/1"))

        async def crash() -> None:
            raise RuntimeError("boom")

        app.add_api_route("/test/crash", crash)
        try:
            TestClient(app, raise_server_exceptions=False).get(
                "/test/crash", headers={"X-Request-ID": "sentry-0001-ab"}
            )
            sentry_sdk.flush()
        finally:
            real_init()  # no DSN: Sentry off again for the rest of the run

        assert events, "the unhandled error was not reported"
        assert {event["tags"]["request_id"] for event in events} == {"sentry-0001-ab"}

    def test_on_with_a_dsn_and_tags_events_with_the_request_id(self, monkeypatch) -> None:
        calls = []
        monkeypatch.setattr(sentry_sdk, "init", lambda **kw: calls.append(kw))

        observability.configure_error_tracking(_settings(sentry_dsn="https://key@o1.ingest.sentry.io/1"))

        [options] = calls
        assert options["send_default_pii"] is False
        token = observability.request_id_var.set("req-123")
        try:
            event = options["before_send"]({}, {})
        finally:
            observability.request_id_var.reset(token)
        assert event["tags"]["request_id"] == "req-123"
