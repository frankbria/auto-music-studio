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
