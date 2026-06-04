"""Unit tests for the backend resolver and capability map (#95)."""

import pytest

from acemusic.backends import (
    DEFAULT_BACKEND,
    VALID_BACKENDS,
    BackendError,
    ensure_supports,
    resolve_backend,
    supports,
)


class TestResolveBackend:
    def test_default_is_auto_when_nothing_set(self):
        assert resolve_backend(None, None) == "auto"
        assert DEFAULT_BACKEND == "auto"

    def test_cli_value_takes_precedence_over_config(self):
        assert resolve_backend("elevenlabs", "ace-step") == "elevenlabs"

    def test_config_used_when_no_cli_value(self):
        assert resolve_backend(None, "elevenlabs") == "elevenlabs"

    def test_case_insensitive_and_trimmed(self):
        assert resolve_backend("  ElevenLabs ", None) == "elevenlabs"

    def test_all_valid_values_resolve(self):
        for b in VALID_BACKENDS:
            assert resolve_backend(b, None) == b

    def test_invalid_value_raises(self):
        with pytest.raises(BackendError, match="Invalid backend"):
            resolve_backend("suno", None)


class TestCapabilities:
    def test_generate_supported_by_both_engines(self):
        assert supports("ace-step", "generate")
        assert supports("elevenlabs", "generate")

    def test_midi_is_ace_step_only(self):
        assert supports("ace-step", "midi")
        assert not supports("elevenlabs", "midi")

    def test_auto_supports_any_op_with_a_capable_engine(self):
        # auto picks whichever engine can do it
        assert supports("auto", "generate")
        assert supports("auto", "midi")

    def test_ensure_supports_passes_for_supported(self):
        ensure_supports("elevenlabs", "generate")  # must not raise

    def test_ensure_supports_raises_actionable_for_unsupported(self):
        with pytest.raises(BackendError, match="does not support 'midi'"):
            ensure_supports("elevenlabs", "midi")
        # message names the engine that does support it
        with pytest.raises(BackendError, match="ace-step"):
            ensure_supports("elevenlabs", "midi")


class TestIssue96Capabilities:
    """Capability entries added by #96 (ElevenLabs first-class generate/compose)."""

    def test_sounds_supported_by_both_engines(self):
        assert supports("ace-step", "sounds")
        assert supports("elevenlabs", "sounds")
        assert supports("auto", "sounds")

    def test_compose_is_elevenlabs_only(self):
        assert supports("elevenlabs", "compose")
        assert not supports("ace-step", "compose")
        assert supports("auto", "compose")
