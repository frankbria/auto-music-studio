"""Unit tests for audio analysis module (US-4.4)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from acemusic.audio import SUPPORTED_FORMATS, detect_bpm, detect_key


class TestSupportedFormats:
    def test_wav_in_supported(self):
        assert ".wav" in SUPPORTED_FORMATS

    def test_flac_in_supported(self):
        assert ".flac" in SUPPORTED_FORMATS

    def test_mp3_in_supported(self):
        assert ".mp3" in SUPPORTED_FORMATS

    def test_ogg_in_supported(self):
        assert ".ogg" in SUPPORTED_FORMATS

    def test_aac_in_supported(self):
        assert ".aac" in SUPPORTED_FORMATS

    def test_aiff_in_supported(self):
        assert ".aiff" in SUPPORTED_FORMATS

    def test_unsupported_not_included(self):
        assert ".txt" not in SUPPORTED_FORMATS
        assert ".mp4" not in SUPPORTED_FORMATS


class TestDetectBpm:
    def test_returns_float_on_success(self, tmp_path):
        fake_path = tmp_path / "song.wav"
        fake_path.write_bytes(b"fake audio")

        mock_librosa = MagicMock()
        mock_librosa.load.return_value = (MagicMock(), 22050)
        mock_librosa.beat.beat_track.return_value = (120.0, MagicMock())

        with patch.dict("sys.modules", {"librosa": mock_librosa}):
            result = detect_bpm(fake_path)

        assert isinstance(result, float)
        assert result == 120.0

    def test_returns_none_on_exception(self, tmp_path):
        fake_path = tmp_path / "bad.wav"
        fake_path.write_bytes(b"not audio")

        mock_librosa = MagicMock()
        mock_librosa.load.side_effect = Exception("load failed")

        with patch.dict("sys.modules", {"librosa": mock_librosa}):
            result = detect_bpm(fake_path)

        assert result is None

    def test_returns_none_on_librosa_beat_track_failure(self, tmp_path):
        fake_path = tmp_path / "song.wav"
        fake_path.write_bytes(b"fake audio")

        mock_librosa = MagicMock()
        mock_librosa.load.return_value = (MagicMock(), 22050)
        mock_librosa.beat.beat_track.side_effect = Exception("beat track failed")

        with patch.dict("sys.modules", {"librosa": mock_librosa}):
            result = detect_bpm(fake_path)

        assert result is None


class TestDetectKey:
    def test_returns_string_on_success(self, tmp_path):
        import numpy as np

        fake_path = tmp_path / "song.wav"
        fake_path.write_bytes(b"fake audio")

        chroma = np.zeros((12, 100))
        chroma[0, :] = 1.0  # Dominant pitch class 0 = C

        mock_librosa = MagicMock()
        mock_librosa.load.return_value = (MagicMock(), 22050)
        mock_librosa.feature.chroma_cqt.return_value = chroma

        with patch.dict("sys.modules", {"librosa": mock_librosa}):
            result = detect_key(fake_path)

        assert isinstance(result, str)
        assert len(result) > 0

    def test_returns_none_on_exception(self, tmp_path):
        fake_path = tmp_path / "bad.wav"
        fake_path.write_bytes(b"not audio")

        mock_librosa = MagicMock()
        mock_librosa.load.side_effect = Exception("load failed")

        with patch.dict("sys.modules", {"librosa": mock_librosa}):
            result = detect_key(fake_path)

        assert result is None

    def test_returns_none_on_chroma_failure(self, tmp_path):
        fake_path = tmp_path / "song.wav"
        fake_path.write_bytes(b"fake audio")

        mock_librosa = MagicMock()
        mock_librosa.load.return_value = (MagicMock(), 22050)
        mock_librosa.feature.chroma_cqt.side_effect = Exception("chroma failed")

        with patch.dict("sys.modules", {"librosa": mock_librosa}):
            result = detect_key(fake_path)

        assert result is None

    def test_key_name_is_human_readable(self, tmp_path):
        import numpy as np

        fake_path = tmp_path / "song.wav"
        fake_path.write_bytes(b"fake audio")

        chroma = np.zeros((12, 100))
        chroma[9, :] = 1.0  # Dominant pitch class 9 = A

        mock_librosa = MagicMock()
        mock_librosa.load.return_value = (MagicMock(), 22050)
        mock_librosa.feature.chroma_cqt.return_value = chroma

        with patch.dict("sys.modules", {"librosa": mock_librosa}):
            result = detect_key(fake_path)

        assert result == "A major"


class TestCropAudio:
    """Tests for crop_audio() — the pure audio trim/fade function."""

    def test_crop_audio_slices_correct_range(self, tmp_path):
        """crop_audio slices the audio segment to [start_ms:end_ms]."""
        input_path = tmp_path / "input.wav"
        output_path = tmp_path / "output.wav"
        input_path.write_bytes(b"fake")

        mock_seg = MagicMock()
        mock_sliced = MagicMock()
        mock_seg.__getitem__ = MagicMock(return_value=mock_sliced)
        mock_sliced.fade_in.return_value = mock_sliced
        mock_sliced.fade_out.return_value = mock_sliced

        mock_pydub = MagicMock()
        mock_pydub.AudioSegment.from_file.return_value = mock_seg

        with patch.dict("sys.modules", {"pydub": mock_pydub}):
            from acemusic.audio import crop_audio as _crop

            _crop(
                input_path=str(input_path),
                output_path=str(output_path),
                start_ms=10_000,
                end_ms=45_000,
            )

        mock_seg.__getitem__.assert_called_once_with(slice(10_000, 45_000))
        mock_sliced.export.assert_called_once()

    def test_crop_audio_applies_fade_in(self, tmp_path):
        """crop_audio applies fade_in when fade_in_ms > 0."""

        input_path = tmp_path / "in.wav"
        output_path = tmp_path / "out.wav"
        input_path.write_bytes(b"fake")

        mock_seg = MagicMock()
        mock_sliced = MagicMock()
        mock_seg.__getitem__ = MagicMock(return_value=mock_sliced)
        mock_sliced.fade_in.return_value = mock_sliced
        mock_sliced.fade_out.return_value = mock_sliced

        mock_pydub = MagicMock()
        mock_pydub.AudioSegment.from_file.return_value = mock_seg

        with patch.dict("sys.modules", {"pydub": mock_pydub}):
            from acemusic.audio import crop_audio as _crop

            _crop(
                input_path=str(input_path),
                output_path=str(output_path),
                start_ms=0,
                end_ms=5000,
                fade_in_ms=500,
            )

        mock_sliced.fade_in.assert_called_once_with(500)

    def test_crop_audio_applies_fade_out(self, tmp_path):
        """crop_audio applies fade_out when fade_out_ms > 0."""

        input_path = tmp_path / "in2.wav"
        output_path = tmp_path / "out2.wav"
        input_path.write_bytes(b"fake")

        mock_seg = MagicMock()
        mock_sliced = MagicMock()
        mock_seg.__getitem__ = MagicMock(return_value=mock_sliced)
        mock_sliced.fade_in.return_value = mock_sliced
        mock_sliced.fade_out.return_value = mock_sliced

        mock_pydub = MagicMock()
        mock_pydub.AudioSegment.from_file.return_value = mock_seg

        with patch.dict("sys.modules", {"pydub": mock_pydub}):
            from acemusic.audio import crop_audio as _crop

            _crop(
                input_path=str(input_path),
                output_path=str(output_path),
                start_ms=0,
                end_ms=5000,
                fade_out_ms=1000,
            )

        mock_sliced.fade_out.assert_called_once_with(1000)

    def test_crop_audio_no_fade_by_default(self, tmp_path):
        """crop_audio does not apply fades when fade params are 0."""
        input_path = tmp_path / "in3.wav"
        output_path = tmp_path / "out3.wav"
        input_path.write_bytes(b"fake")

        mock_seg = MagicMock()
        mock_sliced = MagicMock()
        mock_seg.__getitem__ = MagicMock(return_value=mock_sliced)
        mock_sliced.fade_in.return_value = mock_sliced
        mock_sliced.fade_out.return_value = mock_sliced

        mock_pydub = MagicMock()
        mock_pydub.AudioSegment.from_file.return_value = mock_seg

        with patch.dict("sys.modules", {"pydub": mock_pydub}):
            from acemusic.audio import crop_audio as _crop

            _crop(
                input_path=str(input_path),
                output_path=str(output_path),
                start_ms=0,
                end_ms=5000,
            )

        mock_sliced.fade_in.assert_not_called()
        mock_sliced.fade_out.assert_not_called()


class TestCalculateSpeedMultiplier:
    """Tests for calculate_speed_multiplier() — BPM-based rate calculation."""

    def test_same_bpm_returns_one(self):
        from acemusic.audio import calculate_speed_multiplier

        result = calculate_speed_multiplier(120, 120)
        assert result == 1.0

    def test_lower_target_bpm_returns_less_than_one(self):
        from acemusic.audio import calculate_speed_multiplier

        # 100 BPM target from 120 BPM = 100/120 = 0.833...
        result = calculate_speed_multiplier(120, 100)
        assert result == pytest.approx(100 / 120)
        assert result < 1.0

    def test_higher_target_bpm_returns_greater_than_one(self):
        from acemusic.audio import calculate_speed_multiplier

        # 150 BPM target from 120 BPM = 150/120 = 1.25
        result = calculate_speed_multiplier(120, 150)
        assert result == pytest.approx(150 / 120)
        assert result > 1.0

    def test_zero_original_bpm_raises_error(self):
        from acemusic.audio import calculate_speed_multiplier

        with pytest.raises(ValueError, match="original_bpm must be positive"):
            calculate_speed_multiplier(0, 100)

    def test_zero_target_bpm_raises_error(self):
        from acemusic.audio import calculate_speed_multiplier

        with pytest.raises(ValueError, match="target_bpm must be positive"):
            calculate_speed_multiplier(120, 0)

    def test_negative_original_bpm_raises_error(self):
        from acemusic.audio import calculate_speed_multiplier

        with pytest.raises(ValueError, match="original_bpm must be positive"):
            calculate_speed_multiplier(-120, 100)

    def test_negative_target_bpm_raises_error(self):
        from acemusic.audio import calculate_speed_multiplier

        with pytest.raises(ValueError, match="target_bpm must be positive"):
            calculate_speed_multiplier(120, -100)

    def test_fractional_bpm(self):
        from acemusic.audio import calculate_speed_multiplier

        # 120.5 BPM target from 100 BPM
        result = calculate_speed_multiplier(100, 120.5)
        assert result == pytest.approx(120.5 / 100)


class TestTimeStretchAudio:
    """Tests for time_stretch_audio() — the pure audio stretch function."""

    def test_time_stretch_with_valid_rate(self, tmp_path):
        """time_stretch_audio loads, stretches, and exports audio."""
        input_path = tmp_path / "input.wav"
        output_path = tmp_path / "output.wav"
        input_path.write_bytes(b"fake")

        import numpy as np

        mock_audio = np.array([[0.1, 0.2], [0.3, 0.4]])
        mock_stretched = np.array([[0.1, 0.15, 0.2], [0.3, 0.35, 0.4]])

        mock_librosa = MagicMock()
        mock_librosa.load.return_value = (mock_audio, 22050)
        mock_librosa.effects.time_stretch.return_value = mock_stretched

        mock_sf = MagicMock()

        with patch.dict("sys.modules", {"librosa": mock_librosa, "soundfile": mock_sf}):
            from acemusic.audio import time_stretch_audio

            time_stretch_audio(str(input_path), str(output_path), rate=1.5)

        mock_librosa.load.assert_called_once_with(str(input_path), mono=False)
        mock_librosa.effects.time_stretch.assert_called_once_with(mock_audio, rate=1.5)
        mock_sf.write.assert_called_once()

    def test_time_stretch_zero_rate_raises_error(self, tmp_path):
        """time_stretch_audio rejects rate <= 0."""
        input_path = tmp_path / "in.wav"
        output_path = tmp_path / "out.wav"
        input_path.write_bytes(b"fake")

        from acemusic.audio import time_stretch_audio

        with pytest.raises(ValueError, match="rate must be positive"):
            time_stretch_audio(str(input_path), str(output_path), rate=0)

    def test_time_stretch_negative_rate_raises_error(self, tmp_path):
        """time_stretch_audio rejects negative rate."""
        input_path = tmp_path / "in.wav"
        output_path = tmp_path / "out.wav"
        input_path.write_bytes(b"fake")

        from acemusic.audio import time_stretch_audio

        with pytest.raises(ValueError, match="rate must be positive"):
            time_stretch_audio(str(input_path), str(output_path), rate=-0.5)

    def test_time_stretch_slow_rate(self, tmp_path):
        """time_stretch_audio handles rate < 1 (slowing down)."""
        input_path = tmp_path / "slow.wav"
        output_path = tmp_path / "slow_out.wav"
        input_path.write_bytes(b"fake")

        import numpy as np

        mock_audio = np.array([[0.1, 0.2], [0.3, 0.4]])
        mock_stretched = np.array([[0.1, 0.15, 0.2], [0.3, 0.35, 0.4]])

        mock_librosa = MagicMock()
        mock_librosa.load.return_value = (mock_audio, 22050)
        mock_librosa.effects.time_stretch.return_value = mock_stretched

        mock_sf = MagicMock()

        with patch.dict("sys.modules", {"librosa": mock_librosa, "soundfile": mock_sf}):
            from acemusic.audio import time_stretch_audio

            time_stretch_audio(str(input_path), str(output_path), rate=0.8)

        # Verify rate was passed to librosa
        args, kwargs = mock_librosa.effects.time_stretch.call_args
        assert kwargs["rate"] == 0.8

    def test_time_stretch_fast_rate(self, tmp_path):
        """time_stretch_audio handles rate > 1 (speeding up)."""
        input_path = tmp_path / "fast.wav"
        output_path = tmp_path / "fast_out.wav"
        input_path.write_bytes(b"fake")

        import numpy as np

        mock_audio = np.array([[0.1, 0.2], [0.3, 0.4]])
        mock_stretched = np.array([[0.1, 0.15, 0.2, 0.25], [0.3, 0.35, 0.4, 0.45]])

        mock_librosa = MagicMock()
        mock_librosa.load.return_value = (mock_audio, 22050)
        mock_librosa.effects.time_stretch.return_value = mock_stretched

        mock_sf = MagicMock()

        with patch.dict("sys.modules", {"librosa": mock_librosa, "soundfile": mock_sf}):
            from acemusic.audio import time_stretch_audio

            time_stretch_audio(str(input_path), str(output_path), rate=1.25)

        # Verify rate was passed to librosa
        args, kwargs = mock_librosa.effects.time_stretch.call_args
        assert kwargs["rate"] == 1.25


class TestCombineSample:
    """Tests for combine_sample() — role-based sample/generated audio combination (US-6.5)."""

    def test_rejects_unknown_role(self, tmp_path, write_tone):
        from acemusic.audio import combine_sample

        sample = tmp_path / "s.wav"
        gen = tmp_path / "g.wav"
        out = tmp_path / "out.wav"
        write_tone(sample, duration_s=1.0)
        write_tone(gen, duration_s=2.0)

        with pytest.raises(ValueError, match="Unknown sample role"):
            combine_sample(sample, gen, out, role="not-a-role")

    def test_loop_bed_produces_output_matching_generated_length(self, tmp_path, write_tone):
        """loop-bed overlays the sample at -10dB; output length matches generated."""
        from pydub import AudioSegment

        from acemusic.audio import combine_sample

        sample = tmp_path / "s.wav"
        gen = tmp_path / "g.wav"
        out = tmp_path / "out.wav"
        write_tone(sample, duration_s=1.0)
        write_tone(gen, duration_s=3.0)

        combine_sample(sample, gen, out, role="loop-bed")
        result = AudioSegment.from_file(str(out), format="wav")
        assert abs(len(result) - 3000) < 50

    def test_intro_outro_extends_beyond_generated(self, tmp_path, write_tone):
        """intro-outro prepends + appends the sample, so output > generated length."""
        from pydub import AudioSegment

        from acemusic.audio import combine_sample

        sample = tmp_path / "s.wav"
        gen = tmp_path / "g.wav"
        out = tmp_path / "out.wav"
        write_tone(sample, duration_s=1.0)
        write_tone(gen, duration_s=2.0)

        combine_sample(sample, gen, out, role="intro-outro")
        result = AudioSegment.from_file(str(out), format="wav")
        assert len(result) > 3000

    def test_melodic_hook_extends_beyond_generated(self, tmp_path, write_tone):
        """melodic-hook prepends the sample with a crossfade."""
        from pydub import AudioSegment

        from acemusic.audio import combine_sample

        sample = tmp_path / "s.wav"
        gen = tmp_path / "g.wav"
        out = tmp_path / "out.wav"
        write_tone(sample, duration_s=1.0)
        write_tone(gen, duration_s=2.0)

        combine_sample(sample, gen, out, role="melodic-hook")
        result = AudioSegment.from_file(str(out), format="wav")
        assert len(result) > 2500

    def test_rhythmic_element_matches_generated_length(self, tmp_path, write_tone):
        """rhythmic-element overlays sample at intervals; output matches generated."""
        from pydub import AudioSegment

        from acemusic.audio import combine_sample

        sample = tmp_path / "s.wav"
        gen = tmp_path / "g.wav"
        out = tmp_path / "out.wav"
        write_tone(sample, duration_s=0.5)
        write_tone(gen, duration_s=8.0)

        combine_sample(sample, gen, out, role="rhythmic-element")
        result = AudioSegment.from_file(str(out), format="wav")
        assert abs(len(result) - 8000) < 50

    def test_roles_produce_different_audio(self, tmp_path, write_tone):
        """Different roles must produce different output byte content."""
        from pathlib import Path

        from acemusic.audio import combine_sample

        sample = tmp_path / "s.wav"
        gen = tmp_path / "g.wav"
        write_tone(sample, duration_s=1.0)
        write_tone(gen, duration_s=4.0)

        outputs: dict[str, bytes] = {}
        for role in ("loop-bed", "intro-outro", "rhythmic-element", "melodic-hook"):
            out = tmp_path / f"out-{role}.wav"
            combine_sample(sample, gen, out, role=role)
            outputs[role] = Path(out).read_bytes()

        assert len({hash(v) for v in outputs.values()}) == 4


class TestWriteSampleMetadata:
    """Tests for write_sample_metadata() — JSON sidecar attribution (US-6.5)."""

    def test_sidecar_written_next_to_audio(self, tmp_path):
        import json

        from acemusic.utils import write_sample_metadata

        audio = tmp_path / "out.wav"
        audio.write_bytes(b"fake")
        sidecar = write_sample_metadata(
            audio,
            source_clip_id=42,
            source_file="/path/to/source.wav",
            start_ms=1000,
            end_ms=3000,
            role="loop-bed",
            prompt="chill",
            backend="ace-step",
        )
        assert sidecar == tmp_path / "out.wav.meta.json"
        data = json.loads(sidecar.read_text())
        assert data["source_clip_id"] == 42
        assert data["source_file"] == "/path/to/source.wav"
        assert data["start_ms"] == 1000
        assert data["end_ms"] == 3000
        assert data["role"] == "loop-bed"
        assert data["prompt"] == "chill"
        assert data["backend"] == "ace-step"
        assert data["created_at"]

    def test_sidecar_accepts_none_clip_id(self, tmp_path):
        import json

        from acemusic.utils import write_sample_metadata

        audio = tmp_path / "out.wav"
        audio.write_bytes(b"fake")
        sidecar = write_sample_metadata(
            audio,
            source_clip_id=None,
            source_file="/path/to/source.wav",
            start_ms=0,
            end_ms=1000,
            role="melodic-hook",
            prompt="x",
            backend="ace-step",
        )
        data = json.loads(sidecar.read_text())
        assert data["source_clip_id"] is None


class TestExportAudio:
    """Tests for export_audio() — single-clip export with per-format quality specs (US-7.1)."""

    def test_export_rejects_unknown_format(self, tmp_path):
        from acemusic.audio import export_audio

        src = tmp_path / "in.wav"
        src.write_bytes(b"fake")
        dest = tmp_path / "out.xyz"
        with pytest.raises(ValueError, match="Unsupported export format"):
            export_audio(src, dest, "xyz")

    def test_export_wav_real_roundtrip_is_48k_24bit(self, tmp_path, write_tone):
        """Real pydub WAV export: source tone → exported WAV is 48kHz, 24-bit PCM.

        Uses ffmpeg parameters for codec/rate control, so skip when ffmpeg is not
        on PATH (CI runners without the system package).
        """
        import shutil
        import wave

        if shutil.which("ffmpeg") is None:
            pytest.skip("ffmpeg not installed; required for codec parameter override")

        from acemusic.audio import export_audio

        src = tmp_path / "tone.wav"
        dest = tmp_path / "exported.wav"
        write_tone(src, duration_s=0.5, sample_rate=44100)

        export_audio(src, dest, "wav")

        assert dest.exists()
        with wave.open(str(dest), "rb") as wf:
            assert wf.getframerate() == 48000
            assert wf.getsampwidth() == 3  # 24-bit = 3 bytes

    def test_export_flac_invokes_pydub_with_flac_format(self, tmp_path):
        from acemusic.audio import export_audio

        src = tmp_path / "in.wav"
        src.write_bytes(b"fake")
        dest = tmp_path / "out.flac"

        mock_seg = MagicMock()
        mock_pydub = MagicMock()
        mock_pydub.AudioSegment.from_file.return_value = mock_seg

        with patch.dict("sys.modules", {"pydub": mock_pydub}):
            export_audio(src, dest, "flac")

        mock_pydub.AudioSegment.from_file.assert_called_once_with(str(src), format="wav")
        mock_seg.export.assert_called_once()
        _, kwargs = mock_seg.export.call_args
        assert kwargs["format"] == "flac"

    def test_export_mp3_invokes_pydub_with_320k_bitrate(self, tmp_path):
        from acemusic.audio import export_audio

        src = tmp_path / "in.wav"
        src.write_bytes(b"fake")
        dest = tmp_path / "out.mp3"

        mock_seg = MagicMock()
        mock_pydub = MagicMock()
        mock_pydub.AudioSegment.from_file.return_value = mock_seg

        with patch.dict("sys.modules", {"pydub": mock_pydub}):
            export_audio(src, dest, "mp3")

        _, kwargs = mock_seg.export.call_args
        assert kwargs["format"] == "mp3"
        assert kwargs["bitrate"] == "320k"

    def test_export_wav32_uses_float_codec_parameters(self, tmp_path):
        from acemusic.audio import export_audio

        src = tmp_path / "in.wav"
        src.write_bytes(b"fake")
        dest = tmp_path / "out.wav"

        mock_seg = MagicMock()
        mock_seg.set_frame_rate.return_value = mock_seg
        mock_pydub = MagicMock()
        mock_pydub.AudioSegment.from_file.return_value = mock_seg

        with patch.dict("sys.modules", {"pydub": mock_pydub}):
            export_audio(src, dest, "wav32")

        _, kwargs = mock_seg.export.call_args
        assert kwargs["format"] == "wav"
        params = kwargs.get("parameters", [])
        assert "pcm_f32le" in params
        assert "48000" in params

    def test_export_uses_source_extension_as_format_hint(self, tmp_path):
        """The from_file format= hint is derived from the source file extension."""
        from acemusic.audio import export_audio

        src = tmp_path / "in.mp3"
        src.write_bytes(b"fake")
        dest = tmp_path / "out.flac"

        mock_seg = MagicMock()
        mock_pydub = MagicMock()
        mock_pydub.AudioSegment.from_file.return_value = mock_seg

        with patch.dict("sys.modules", {"pydub": mock_pydub}):
            export_audio(src, dest, "flac")

        mock_pydub.AudioSegment.from_file.assert_called_once_with(str(src), format="mp3")

    def test_export_formats_constant_lists_all_four_formats(self):
        from acemusic.audio import EXPORT_FORMATS

        assert set(EXPORT_FORMATS) == {"wav", "wav32", "flac", "mp3"}

    def test_export_unhandled_branch_raises_assertion(self, tmp_path, monkeypatch):
        """If EXPORT_FORMATS is extended without a matching if/elif branch, the function
        should fail loudly instead of silently returning the dest path."""
        from acemusic import audio as _audio

        src = tmp_path / "in.wav"
        src.write_bytes(b"fake")
        dest = tmp_path / "out.xyz"

        # Inject a phantom format that the if/elif chain doesn't handle.
        monkeypatch.setattr(_audio, "EXPORT_FORMATS", _audio.EXPORT_FORMATS + ("opus",))

        mock_seg = MagicMock()
        mock_pydub = MagicMock()
        mock_pydub.AudioSegment.from_file.return_value = mock_seg

        with patch.dict("sys.modules", {"pydub": mock_pydub}):
            with pytest.raises(AssertionError, match="Unhandled export format"):
                _audio.export_audio(src, dest, "opus")
