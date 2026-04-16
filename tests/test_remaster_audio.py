"""Unit tests for remaster audio processing functions (US-5.5)."""

from __future__ import annotations

import numpy as np


def _make_stereo_sine(
    frequency: float = 440.0,
    duration_s: float = 2.0,
    sample_rate: int = 44100,
    amplitude: float = 0.5,
) -> tuple[np.ndarray, int]:
    """Create a stereo sine wave for testing."""
    t = np.linspace(0, duration_s, int(sample_rate * duration_s), endpoint=False)
    mono = (amplitude * np.sin(2 * np.pi * frequency * t)).astype(np.float64)
    stereo = np.column_stack([mono, mono])
    return stereo, sample_rate


def _make_dynamic_stereo(
    sample_rate: int = 44100,
    duration_s: float = 2.0,
) -> tuple[np.ndarray, int]:
    """Create a stereo signal with high dynamic range (loud + quiet sections)."""
    n_samples = int(sample_rate * duration_s)
    t = np.linspace(0, duration_s, n_samples, endpoint=False)
    half = n_samples // 2
    signal = np.zeros(n_samples, dtype=np.float64)
    signal[:half] = 0.8 * np.sin(2 * np.pi * 440.0 * t[:half])
    signal[half:] = 0.05 * np.sin(2 * np.pi * 440.0 * t[half:])
    stereo = np.column_stack([signal, signal])
    return stereo, sample_rate


class TestMeasureLufs:
    def test_returns_float(self):
        from acemusic.audio import measure_lufs

        audio, sr = _make_stereo_sine(amplitude=0.5)
        result = measure_lufs(audio, sr)
        assert isinstance(result, float)

    def test_louder_signal_has_higher_lufs(self):
        from acemusic.audio import measure_lufs

        loud, sr = _make_stereo_sine(amplitude=0.8)
        quiet, _ = _make_stereo_sine(amplitude=0.1)
        loud_lufs = measure_lufs(loud, sr)
        quiet_lufs = measure_lufs(quiet, sr)
        assert loud_lufs > quiet_lufs

    def test_result_is_negative(self):
        from acemusic.audio import measure_lufs

        audio, sr = _make_stereo_sine(amplitude=0.5)
        result = measure_lufs(audio, sr)
        assert result < 0


class TestNormalizeLoudness:
    def test_output_near_target_lufs(self):
        from acemusic.audio import measure_lufs, normalize_loudness

        audio, sr = _make_stereo_sine(amplitude=0.3)
        target = -14.0
        normalized = normalize_loudness(audio, sr, target)
        result_lufs = measure_lufs(normalized, sr)
        assert abs(result_lufs - target) < 1.5

    def test_preserves_shape(self):
        from acemusic.audio import normalize_loudness

        audio, sr = _make_stereo_sine(amplitude=0.3)
        normalized = normalize_loudness(audio, sr, -14.0)
        assert normalized.shape == audio.shape

    def test_no_clipping(self):
        from acemusic.audio import normalize_loudness

        audio, sr = _make_stereo_sine(amplitude=0.3)
        normalized = normalize_loudness(audio, sr, -14.0)
        assert np.max(np.abs(normalized)) <= 1.0


class TestApplyEq:
    def test_preserves_audio_length(self):
        from acemusic.audio import apply_eq

        audio, sr = _make_stereo_sine()
        result = apply_eq(audio, sr)
        assert result.shape == audio.shape

    def test_no_clipping(self):
        from acemusic.audio import apply_eq

        audio, sr = _make_stereo_sine(amplitude=0.5)
        result = apply_eq(audio, sr)
        assert np.max(np.abs(result)) <= 1.01  # small tolerance for filter ringing


class TestApplyCompression:
    def test_reduces_dynamic_range(self):
        from acemusic.audio import apply_compression

        audio, sr = _make_dynamic_stereo()
        compressed = apply_compression(audio, sr)

        half = len(audio) // 2
        # Measure RMS of loud and quiet sections
        rms_loud_orig = np.sqrt(np.mean(audio[:half] ** 2))
        rms_quiet_orig = np.sqrt(np.mean(audio[half:] ** 2))
        ratio_orig = rms_loud_orig / rms_quiet_orig

        rms_loud_comp = np.sqrt(np.mean(compressed[:half] ** 2))
        rms_quiet_comp = np.sqrt(np.mean(compressed[half:] ** 2))
        ratio_comp = rms_loud_comp / rms_quiet_comp

        # After compression, the ratio between loud and quiet should decrease
        assert ratio_comp < ratio_orig

    def test_preserves_shape(self):
        from acemusic.audio import apply_compression

        audio, sr = _make_dynamic_stereo()
        result = apply_compression(audio, sr)
        assert result.shape == audio.shape


class TestApplyStereoWidening:
    def test_preserves_shape(self):
        from acemusic.audio import apply_stereo_widening

        audio, sr = _make_stereo_sine()
        result = apply_stereo_widening(audio, amount=1.2)
        assert result.shape == audio.shape

    def test_mono_compatibility(self):
        """Sum of L+R should not be significantly reduced."""
        from acemusic.audio import apply_stereo_widening

        audio, sr = _make_stereo_sine()
        result = apply_stereo_widening(audio, amount=1.2)

        mono_orig = audio[:, 0] + audio[:, 1]
        mono_widened = result[:, 0] + result[:, 1]

        energy_orig = np.sum(mono_orig**2)
        energy_widened = np.sum(mono_widened**2)

        # Mono energy should not drop by more than 3dB
        assert energy_widened >= energy_orig * 0.5

    def test_amount_zero_returns_mono_collapse(self):
        """Amount 0 should collapse to mono (L=R)."""
        from acemusic.audio import apply_stereo_widening

        # Create a signal with L/R difference
        left = np.sin(2 * np.pi * 440 * np.linspace(0, 1, 44100))
        right = np.sin(2 * np.pi * 880 * np.linspace(0, 1, 44100))
        audio = np.column_stack([left, right])

        result = apply_stereo_widening(audio, amount=0.0)
        # At amount=0, L and R should be identical (pure mid)
        np.testing.assert_allclose(result[:, 0], result[:, 1], atol=1e-10)


class TestRemasterAudio:
    def test_end_to_end_creates_output_file(self, tmp_path):
        from acemusic.audio import remaster_audio

        audio, sr = _make_stereo_sine(amplitude=0.3, duration_s=2.0)
        input_path = tmp_path / "input.wav"
        output_path = tmp_path / "output.wav"

        import soundfile as sf

        sf.write(str(input_path), audio, sr)

        result = remaster_audio(input_path, output_path, target_lufs=-14.0)
        assert output_path.exists()
        assert "before_lufs" in result
        assert "after_lufs" in result

    def test_output_lufs_near_target(self, tmp_path):
        from acemusic.audio import remaster_audio

        audio, sr = _make_stereo_sine(amplitude=0.1, duration_s=2.0)
        input_path = tmp_path / "quiet_input.wav"
        output_path = tmp_path / "remastered.wav"

        import soundfile as sf

        sf.write(str(input_path), audio, sr)

        result = remaster_audio(input_path, output_path, target_lufs=-14.0)
        assert abs(result["after_lufs"] - (-14.0)) < 2.0

    def test_original_file_unchanged(self, tmp_path):
        from acemusic.audio import remaster_audio

        audio, sr = _make_stereo_sine(amplitude=0.3, duration_s=2.0)
        input_path = tmp_path / "original.wav"
        output_path = tmp_path / "remastered.wav"

        import soundfile as sf

        sf.write(str(input_path), audio, sr)

        original_bytes = input_path.read_bytes()
        remaster_audio(input_path, output_path, target_lufs=-14.0)
        assert input_path.read_bytes() == original_bytes

    def test_custom_target_lufs(self, tmp_path):
        from acemusic.audio import remaster_audio

        audio, sr = _make_stereo_sine(amplitude=0.3, duration_s=2.0)
        input_path = tmp_path / "input.wav"
        output_path = tmp_path / "output.wav"

        import soundfile as sf

        sf.write(str(input_path), audio, sr)

        result = remaster_audio(input_path, output_path, target_lufs=-12.0)
        assert abs(result["after_lufs"] - (-12.0)) < 2.0
