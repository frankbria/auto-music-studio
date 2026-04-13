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

        with patch("acemusic.audio.librosa") as mock_librosa:
            mock_librosa.load.return_value = (MagicMock(), 22050)
            mock_librosa.beat.beat_track.return_value = (120.0, MagicMock())
            result = detect_bpm(fake_path)

        assert isinstance(result, float)
        assert result == 120.0

    def test_returns_none_on_exception(self, tmp_path):
        fake_path = tmp_path / "bad.wav"
        fake_path.write_bytes(b"not audio")

        with patch("acemusic.audio.librosa") as mock_librosa:
            mock_librosa.load.side_effect = Exception("load failed")
            result = detect_bpm(fake_path)

        assert result is None

    def test_returns_none_on_librosa_beat_track_failure(self, tmp_path):
        fake_path = tmp_path / "song.wav"
        fake_path.write_bytes(b"fake audio")

        with patch("acemusic.audio.librosa") as mock_librosa:
            mock_librosa.load.return_value = (MagicMock(), 22050)
            mock_librosa.beat.beat_track.side_effect = Exception("beat track failed")
            result = detect_bpm(fake_path)

        assert result is None


class TestDetectKey:
    def test_returns_string_on_success(self, tmp_path):
        import numpy as np

        fake_path = tmp_path / "song.wav"
        fake_path.write_bytes(b"fake audio")

        chroma = np.zeros((12, 100))
        chroma[0, :] = 1.0  # Dominant pitch class 0 = C

        with patch("acemusic.audio.librosa") as mock_librosa:
            mock_librosa.load.return_value = (MagicMock(), 22050)
            mock_librosa.feature.chroma_cqt.return_value = chroma
            result = detect_key(fake_path)

        assert isinstance(result, str)
        assert len(result) > 0

    def test_returns_none_on_exception(self, tmp_path):
        fake_path = tmp_path / "bad.wav"
        fake_path.write_bytes(b"not audio")

        with patch("acemusic.audio.librosa") as mock_librosa:
            mock_librosa.load.side_effect = Exception("load failed")
            result = detect_key(fake_path)

        assert result is None

    def test_returns_none_on_chroma_failure(self, tmp_path):
        fake_path = tmp_path / "song.wav"
        fake_path.write_bytes(b"fake audio")

        with patch("acemusic.audio.librosa") as mock_librosa:
            mock_librosa.load.return_value = (MagicMock(), 22050)
            mock_librosa.feature.chroma_cqt.side_effect = Exception("chroma failed")
            result = detect_key(fake_path)

        assert result is None

    def test_key_name_is_human_readable(self, tmp_path):
        import numpy as np

        fake_path = tmp_path / "song.wav"
        fake_path.write_bytes(b"fake audio")

        chroma = np.zeros((12, 100))
        chroma[9, :] = 1.0  # Dominant pitch class 9 = A

        with patch("acemusic.audio.librosa") as mock_librosa:
            mock_librosa.load.return_value = (MagicMock(), 22050)
            mock_librosa.feature.chroma_cqt.return_value = chroma
            result = detect_key(fake_path)

        assert result is not None
        assert "major" in result.lower() or "minor" in result.lower()
