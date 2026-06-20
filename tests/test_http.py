"""Unit tests for the shared HTTP request/retry helper (US-15.3)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx

from acemusic import _http


def _resp(status_code: int) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    return resp


def test_backoff_delay_is_exponential_with_jitter():
    with patch("acemusic._http.random.uniform", return_value=0.0):
        assert [_http.backoff_delay(a) for a in range(3)] == [1.0, 2.0, 4.0]


def test_success_returns_immediately_without_retry():
    method = MagicMock(return_value=_resp(200))
    with patch("acemusic._http.time.sleep") as sleep:
        result = _http.request(method, "http://x", timeout=1.0)
    assert result.status_code == 200
    assert method.call_count == 1
    sleep.assert_not_called()


def test_4xx_fails_fast_without_retry():
    method = MagicMock(return_value=_resp(404))
    with patch("acemusic._http.time.sleep") as sleep:
        result = _http.request(method, "http://x", timeout=1.0)
    assert result.status_code == 404
    assert method.call_count == 1
    sleep.assert_not_called()


def test_5xx_retries_then_returns_last_response():
    method = MagicMock(return_value=_resp(503))
    with patch("acemusic._http.time.sleep") as sleep:
        result = _http.request(method, "http://x", timeout=1.0)
    # initial attempt + MAX_RETRIES retries; one sleep between each retry
    assert method.call_count == _http.MAX_RETRIES + 1
    assert sleep.call_count == _http.MAX_RETRIES
    assert result.status_code == 503


def test_5xx_then_success_recovers():
    method = MagicMock(side_effect=[_resp(500), _resp(200)])
    with patch("acemusic._http.time.sleep"):
        result = _http.request(method, "http://x", timeout=1.0)
    assert result.status_code == 200
    assert method.call_count == 2


def test_retries_zero_makes_a_single_attempt():
    method = MagicMock(return_value=_resp(503))
    with patch("acemusic._http.time.sleep") as sleep:
        result = _http.request(method, "http://x", timeout=1.0, retries=0)
    assert method.call_count == 1
    sleep.assert_not_called()
    assert result.status_code == 503


def test_connection_errors_propagate_unretried():
    method = MagicMock(side_effect=httpx.ConnectError("refused"))
    with patch("acemusic._http.time.sleep") as sleep:
        try:
            _http.request(method, "http://x", timeout=1.0)
        except httpx.ConnectError:
            pass
        else:  # pragma: no cover
            raise AssertionError("expected ConnectError to propagate")
    assert method.call_count == 1
    sleep.assert_not_called()


def test_passes_headers_and_kwargs_through():
    method = MagicMock(return_value=_resp(200))
    _http.request(method, "http://x", timeout=2.0, headers={"a": "b"}, json={"k": 1})
    assert method.call_args.kwargs == {"headers": {"a": "b"}, "timeout": 2.0, "json": {"k": 1}}
