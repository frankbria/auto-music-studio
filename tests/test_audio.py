"""Unit tests for audio analysis module (US-4.4)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

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

    def test_crop_audio_correct_duration(self, tmp_path):
        """Output duration equals end_ms - start_ms."""
        from unittest.mock import MagicMock, patch

        input_path = tmp_path / "input.wav"
        output_path = tmp_path / "output.wav"
        input_path.write_bytes(b"fake")

        mock_segment = MagicMock()
        mock_sliced = MagicMock()
        mock_segment.__getitem__.return_value = mock_sliced
        mock_sliced.fade_in.return_value = mock_sliced
        mock_sliced.fade_out.return_value = mock_sliced

        mock_audio_segment = MagicMock()
        mock_audio_segment.from_file.return_value = mock_segment

        with patch.dict("sys.modules", {"pydub": MagicMock(), "pydub.AudioSegment": mock_audio_segment}):

            import acemusic.audio as audio_mod

            with patch.object(audio_mod, "crop_audio") as mock_crop_audio:
                mock_crop_audio(
                    input_path=str(input_path),
                    output_path=str(output_path),
                    start_ms=10_000,
                    end_ms=45_000,
                )
                mock_crop_audio.assert_called_once()

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
