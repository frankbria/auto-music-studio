"""Unit tests for the compute routing engine (US-11.1).

Pure-logic tests with no DB: availability checks are monkeypatched (routing
branches) or mocked with respx (the HTTP probe itself), so these run in CI
without the ``integration`` marker.
"""

import httpx
import pytest
import respx

from acemusic.api.services import routing
from acemusic.api.services.routing import (
    ComputePreference,
    ComputeTarget,
    ComputeUnavailableError,
    resolve_compute_target,
)

LOCAL_URL = "http://localhost:8001"
STATS_URL = f"{LOCAL_URL}/v1/stats"


def _set_availability(monkeypatch, *, local: bool, remote: bool) -> None:
    """Stub both availability probes so routing logic can be tested in isolation."""

    async def _local(url: str, timeout: float = routing.LOCAL_AVAILABILITY_TIMEOUT) -> bool:
        return local

    async def _remote() -> bool:
        return remote

    monkeypatch.setattr(routing, "check_local_availability", _local)
    monkeypatch.setattr(routing, "check_remote_availability", _remote)


class TestCheckLocalAvailability:
    @respx.mock
    async def test_2xx_response_is_available(self):
        respx.get(STATS_URL).mock(return_value=httpx.Response(200, json={"ok": True}))
        assert await routing.check_local_availability(LOCAL_URL) is True

    @respx.mock
    async def test_trailing_slash_url_is_normalised(self):
        route = respx.get(STATS_URL).mock(return_value=httpx.Response(200))
        assert await routing.check_local_availability(LOCAL_URL + "/") is True
        assert route.called

    @respx.mock
    async def test_server_error_is_unavailable(self):
        respx.get(STATS_URL).mock(return_value=httpx.Response(503))
        assert await routing.check_local_availability(LOCAL_URL) is False

    @respx.mock
    async def test_connection_error_is_unavailable(self):
        respx.get(STATS_URL).mock(side_effect=httpx.ConnectError("refused"))
        assert await routing.check_local_availability(LOCAL_URL) is False

    @respx.mock
    async def test_timeout_is_unavailable(self):
        respx.get(STATS_URL).mock(side_effect=httpx.ReadTimeout("slow"))
        assert await routing.check_local_availability(LOCAL_URL, timeout=0.01) is False


class TestCheckRemoteAvailability:
    async def test_remote_is_unavailable_until_us_11_2(self):
        # Until US-11.2 wires up RunPod, the remote probe degrades to unavailable.
        assert await routing.check_remote_availability() is False


class TestLocalFirst:
    async def test_routes_local_when_local_available(self, monkeypatch):
        _set_availability(monkeypatch, local=True, remote=False)
        target = await resolve_compute_target(
            request_target="auto", preference=ComputePreference.LOCAL_FIRST, local_url=LOCAL_URL
        )
        assert target is ComputeTarget.LOCAL

    async def test_falls_back_to_remote_when_local_down(self, monkeypatch):
        _set_availability(monkeypatch, local=False, remote=True)
        target = await resolve_compute_target(
            request_target="auto", preference=ComputePreference.LOCAL_FIRST, local_url=LOCAL_URL
        )
        assert target is ComputeTarget.REMOTE

    async def test_raises_when_neither_available(self, monkeypatch):
        _set_availability(monkeypatch, local=False, remote=False)
        with pytest.raises(ComputeUnavailableError):
            await resolve_compute_target(
                request_target="auto", preference=ComputePreference.LOCAL_FIRST, local_url=LOCAL_URL
            )


class TestRemoteFirst:
    async def test_routes_remote_when_remote_available(self, monkeypatch):
        _set_availability(monkeypatch, local=True, remote=True)
        target = await resolve_compute_target(
            request_target="auto", preference=ComputePreference.REMOTE_FIRST, local_url=LOCAL_URL
        )
        assert target is ComputeTarget.REMOTE

    async def test_falls_back_to_local_when_remote_down(self, monkeypatch):
        _set_availability(monkeypatch, local=True, remote=False)
        target = await resolve_compute_target(
            request_target="auto", preference=ComputePreference.REMOTE_FIRST, local_url=LOCAL_URL
        )
        assert target is ComputeTarget.LOCAL

    async def test_raises_when_neither_available(self, monkeypatch):
        _set_availability(monkeypatch, local=False, remote=False)
        with pytest.raises(ComputeUnavailableError):
            await resolve_compute_target(
                request_target="auto", preference=ComputePreference.REMOTE_FIRST, local_url=LOCAL_URL
            )


class TestLocalOnly:
    async def test_routes_local_when_available(self, monkeypatch):
        _set_availability(monkeypatch, local=True, remote=True)
        target = await resolve_compute_target(
            request_target="auto", preference=ComputePreference.LOCAL_ONLY, local_url=LOCAL_URL
        )
        assert target is ComputeTarget.LOCAL

    async def test_raises_without_falling_back_when_local_down(self, monkeypatch):
        # Even though remote is "available", local_only never falls back.
        _set_availability(monkeypatch, local=False, remote=True)
        with pytest.raises(ComputeUnavailableError) as exc:
            await resolve_compute_target(
                request_target="auto", preference=ComputePreference.LOCAL_ONLY, local_url=LOCAL_URL
            )
        assert exc.value.target is ComputeTarget.LOCAL
        assert exc.value.preference is ComputePreference.LOCAL_ONLY


class TestRemoteOnly:
    async def test_routes_remote_when_available(self, monkeypatch):
        _set_availability(monkeypatch, local=True, remote=True)
        target = await resolve_compute_target(
            request_target="auto", preference=ComputePreference.REMOTE_ONLY, local_url=LOCAL_URL
        )
        assert target is ComputeTarget.REMOTE

    async def test_raises_without_falling_back_when_remote_down(self, monkeypatch):
        _set_availability(monkeypatch, local=True, remote=False)
        with pytest.raises(ComputeUnavailableError) as exc:
            await resolve_compute_target(
                request_target="auto", preference=ComputePreference.REMOTE_ONLY, local_url=LOCAL_URL
            )
        assert exc.value.target is ComputeTarget.REMOTE
        assert exc.value.preference is ComputePreference.REMOTE_ONLY


class TestPerRequestOverride:
    async def test_explicit_local_overrides_remote_first_preference(self, monkeypatch):
        _set_availability(monkeypatch, local=True, remote=True)
        target = await resolve_compute_target(
            request_target="local", preference=ComputePreference.REMOTE_FIRST, local_url=LOCAL_URL
        )
        assert target is ComputeTarget.LOCAL

    async def test_explicit_remote_overrides_local_first_preference(self, monkeypatch):
        _set_availability(monkeypatch, local=True, remote=True)
        target = await resolve_compute_target(
            request_target="remote", preference=ComputePreference.LOCAL_FIRST, local_url=LOCAL_URL
        )
        assert target is ComputeTarget.REMOTE

    async def test_explicit_local_does_not_fall_back(self, monkeypatch):
        # An explicit target is honoured with *_only semantics: no silent fallback.
        _set_availability(monkeypatch, local=False, remote=True)
        with pytest.raises(ComputeUnavailableError) as exc:
            await resolve_compute_target(
                request_target="local", preference=ComputePreference.LOCAL_FIRST, local_url=LOCAL_URL
            )
        assert exc.value.target is ComputeTarget.LOCAL

    async def test_none_request_target_uses_preference(self, monkeypatch):
        _set_availability(monkeypatch, local=True, remote=False)
        target = await resolve_compute_target(
            request_target=None, preference=ComputePreference.LOCAL_FIRST, local_url=LOCAL_URL
        )
        assert target is ComputeTarget.LOCAL

    async def test_unknown_request_target_raises_value_error(self, monkeypatch):
        # The router's Literal guards this, but the service fails loudly rather
        # than silently defaulting if ever called with a bad value directly.
        _set_availability(monkeypatch, local=True, remote=True)
        with pytest.raises(ValueError, match="unknown compute_target"):
            await resolve_compute_target(
                request_target="banana", preference=ComputePreference.LOCAL_FIRST, local_url=LOCAL_URL
            )


class TestEnums:
    def test_compute_preference_values_match_settings_literal(self):
        assert {p.value for p in ComputePreference} == {
            "local_first",
            "remote_first",
            "local_only",
            "remote_only",
        }

    def test_compute_target_values(self):
        assert {t.value for t in ComputeTarget} == {"local", "remote"}
