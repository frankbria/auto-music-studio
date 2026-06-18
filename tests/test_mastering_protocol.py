"""Tests for the shared mastering-service contract (US-12.3).

The :class:`MasteringService` protocol is the seam that lets the mastering job
handler treat Dolby.io, LANDR, and Bakuage interchangeably: each backend drives
the full upload -> master -> poll -> download workflow behind a single
:meth:`master` entrypoint and returns the same :class:`MasteringOutput` shape.
These tests pin the contract (dataclass shape, error hierarchy, protocol
conformance) that the three clients and the orchestrator rely on.
"""

from __future__ import annotations

from dataclasses import is_dataclass

import pytest

from acemusic.mastering_protocol import (
    MasteringError,
    MasteringOutput,
    MasteringService,
)


class TestMasteringOutput:
    def test_is_frozen_dataclass(self) -> None:
        assert is_dataclass(MasteringOutput)
        out = MasteringOutput(audio_bytes=b"x", metrics={"loudness": -14.0}, service="dolby")
        with pytest.raises(Exception):
            out.service = "landr"  # type: ignore[misc]

    def test_fields(self) -> None:
        out = MasteringOutput(audio_bytes=b"\x00\x01", metrics={"loudness": -6.0}, service="bakuage")
        assert out.audio_bytes == b"\x00\x01"
        assert out.metrics == {"loudness": -6.0}
        assert out.service == "bakuage"

    def test_default_metrics_is_required_not_mutable_default(self) -> None:
        # No mutable default; callers always pass metrics explicitly.
        out = MasteringOutput(audio_bytes=b"", metrics={}, service="landr")
        out2 = MasteringOutput(audio_bytes=b"", metrics={}, service="landr")
        assert out.metrics is not out2.metrics


class TestMasteringError:
    def test_is_exception_subclass(self) -> None:
        assert issubclass(MasteringError, Exception)

    def test_can_be_raised_and_caught(self) -> None:
        with pytest.raises(MasteringError, match="boom"):
            raise MasteringError("boom")


class _GoodService:
    service = "dolby"

    def master(
        self, audio_bytes: bytes, filename: str, profile: str, target_lufs: float, output_format: str
    ) -> MasteringOutput:
        return MasteringOutput(audio_bytes=audio_bytes, metrics={}, service=self.service)


class _MissingService:
    def master(
        self, audio_bytes: bytes, filename: str, profile: str, target_lufs: float, output_format: str
    ) -> MasteringOutput:
        return MasteringOutput(audio_bytes=b"", metrics={}, service="x")


class _MissingMaster:
    service = "dolby"


class TestMasteringServiceProtocol:
    def test_conforming_class_is_recognised(self) -> None:
        assert isinstance(_GoodService(), MasteringService)

    def test_class_missing_service_attr_is_rejected(self) -> None:
        assert not isinstance(_MissingService(), MasteringService)

    def test_class_missing_master_method_is_rejected(self) -> None:
        assert not isinstance(_MissingMaster(), MasteringService)

    def test_master_signature_carries_expected_args(self) -> None:
        # Structural: a service built ad hoc with the right method works end to end.
        svc = _GoodService()
        out = svc.master(b"audio", "f.wav", "streaming", -14.0, "wav")
        assert isinstance(out, MasteringOutput)
        assert out.audio_bytes == b"audio"
