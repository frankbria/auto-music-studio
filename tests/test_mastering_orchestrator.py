"""Unit tests for the MasteringOrchestrator fallback chain (US-12.3).

The orchestrator is the seam between the mastering job handler and the three
backends: it picks the requested service, and on a backend failure retries the
next *configured* service in the canonical order (Dolby -> LANDR -> Bakuage).
These tests pin the fallback contract with lightweight fake services — no HTTP,
no DB — covering: explicit-service success, primary-failure -> fallback success,
all-fail propagation, the "explicitly requested but unconfigured" error (no
silent substitution), and skipping unconfigured services in the chain.
"""

from __future__ import annotations

import pytest

from acemusic.mastering_orchestrator import (
    DEFAULT_FALLBACK_ORDER,
    MasteringOrchestrator,
    ServiceNotConfiguredError,
)
from acemusic.mastering_protocol import MasteringError, MasteringOutput, MasteringService


class FakeService:
    """A mastering service that either succeeds with canned output or raises."""

    service: str

    def __init__(self, *, service: str, audio: bytes = b"X", fail: bool = False) -> None:
        self.service = service
        self._audio = audio
        self._fail = fail
        self.calls = 0

    def master(
        self,
        audio_bytes: bytes,
        filename: str,
        profile: str,
        target_lufs: float,
        output_format: str,
    ) -> MasteringOutput:
        self.calls += 1
        if self._fail:
            raise MasteringError(f"{self.service} unavailable")
        return MasteringOutput(audio_bytes=self._audio, metrics={"loudness": -14.0}, service=self.service)


# ---------------------------------------------------------------------------
# Availability / dispatch
# ---------------------------------------------------------------------------


class TestAvailability:
    def test_is_service_available_for_configured_only(self) -> None:
        orch = MasteringOrchestrator({"dolby": FakeService(service="dolby")})
        assert orch.is_service_available("dolby")
        assert not orch.is_service_available("landr")
        assert not orch.is_service_available("bakuage")

    def test_get_client_returns_configured_client(self) -> None:
        svc = FakeService(service="dolby")
        orch = MasteringOrchestrator({"dolby": svc})
        assert orch.get_client("dolby") is svc

    def test_get_client_unconfigured_raises(self) -> None:
        orch = MasteringOrchestrator({"dolby": FakeService(service="dolby")})
        with pytest.raises(ServiceNotConfiguredError):
            orch.get_client("landr")

    def test_default_fallback_order(self) -> None:
        assert DEFAULT_FALLBACK_ORDER == ("dolby", "landr", "bakuage")


# ---------------------------------------------------------------------------
# Fallback behaviour
# ---------------------------------------------------------------------------


class TestFallback:
    def test_requested_service_succeeds_no_fallback(self) -> None:
        dolby = FakeService(service="dolby")
        bakuage = FakeService(service="bakuage")
        orch = MasteringOrchestrator({"dolby": dolby, "bakuage": bakuage})
        out = orch.master_with_fallback(b"a", "f.wav", "streaming", -14.0, "wav", requested_service="dolby")
        assert out.service == "dolby"
        assert dolby.calls == 1
        assert bakuage.calls == 0  # no fallback attempted

    def test_primary_failure_falls_back_to_next_configured(self) -> None:
        dolby = FakeService(service="dolby", fail=True)
        bakuage = FakeService(service="bakuage")
        orch = MasteringOrchestrator({"dolby": dolby, "bakuage": bakuage})
        out = orch.master_with_fallback(b"a", "f.wav", "streaming", -14.0, "wav", requested_service="dolby")
        assert out.service == "bakuage"  # AC3: Dolby error -> Bakuage succeeds
        assert dolby.calls == 1
        assert bakuage.calls == 1

    def test_chain_skips_unconfigured_services(self) -> None:
        # dolby fails, landr NOT configured, bakuage configured -> falls back to bakuage.
        dolby = FakeService(service="dolby", fail=True)
        bakuage = FakeService(service="bakuage")
        orch = MasteringOrchestrator({"dolby": dolby, "bakuage": bakuage})
        out = orch.master_with_fallback(b"a", "f.wav", "streaming", -14.0, "wav", requested_service="dolby")
        assert out.service == "bakuage"

    def test_full_chain_dolby_to_bakuage_through_landr(self) -> None:
        dolby = FakeService(service="dolby", fail=True)
        landr = FakeService(service="landr", fail=True)
        bakuage = FakeService(service="bakuage")
        orch = MasteringOrchestrator({"dolby": dolby, "landr": landr, "bakuage": bakuage})
        out = orch.master_with_fallback(b"a", "f.wav", "streaming", -14.0, "wav", requested_service="dolby")
        assert out.service == "bakuage"
        assert all(c.calls == 1 for c in (dolby, landr, bakuage))

    def test_all_fail_propagates_last_error(self) -> None:
        dolby = FakeService(service="dolby", fail=True)
        bakuage = FakeService(service="bakuage", fail=True)
        orch = MasteringOrchestrator({"dolby": dolby, "bakuage": bakuage})
        with pytest.raises(MasteringError, match="bakuage unavailable"):
            orch.master_with_fallback(b"a", "f.wav", "streaming", -14.0, "wav", requested_service="dolby")

    def test_requested_unconfigured_raises_clear_error_no_silent_substitution(self) -> None:
        # Explicitly requested landr but only dolby configured -> must NOT silently
        # run dolby; raise so the handler can refund and report a clear failure.
        dolby = FakeService(service="dolby")
        orch = MasteringOrchestrator({"dolby": dolby})
        with pytest.raises(ServiceNotConfiguredError):
            orch.master_with_fallback(b"a", "f.wav", "streaming", -14.0, "wav", requested_service="landr")
        assert dolby.calls == 0

    def test_bakuage_primary_uses_canonical_order_for_fallbacks(self) -> None:
        # Requesting bakuage explicitly: fallback order still tries dolby then landr first.
        bakuage = FakeService(service="bakuage", fail=True)
        dolby = FakeService(service="dolby")
        orch = MasteringOrchestrator({"dolby": dolby, "bakuage": bakuage})
        out = orch.master_with_fallback(b"a", "f.wav", "streaming", -14.0, "wav", requested_service="bakuage")
        assert out.service == "dolby"

    def test_fallback_passes_through_all_master_args(self) -> None:
        captured: dict = {}

        class CapturingService:
            service = "dolby"

            def master(self, audio_bytes, filename, profile, target_lufs, output_format):
                captured.update(
                    audio_bytes=audio_bytes,
                    filename=filename,
                    profile=profile,
                    target_lufs=target_lufs,
                    output_format=output_format,
                )
                return MasteringOutput(audio_bytes=audio_bytes, metrics={}, service="dolby")

        orch = MasteringOrchestrator({"dolby": CapturingService()})
        orch.master_with_fallback(b"AUDIO", "clip.wav", "club", -6.0, "flac", requested_service="dolby")
        assert captured == {
            "audio_bytes": b"AUDIO",
            "filename": "clip.wav",
            "profile": "club",
            "target_lufs": -6.0,
            "output_format": "flac",
        }


class TestProtocolConformance:
    def test_fakes_conform_to_protocol(self) -> None:
        assert isinstance(FakeService(service="dolby"), MasteringService)
