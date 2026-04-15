"""Tests for the StemsClient module (US-5.3).

These tests require torch to be installed (used for tensor creation in mocks).
They are automatically skipped in CI where torch is not available.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

torch = pytest.importorskip("torch", reason="torch required for StemsClient tests")

from acemusic.stems_client import STEM_LABELS, StemsClient, StemsError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_model():
    """Create a mock demucs model with correct attributes."""
    model = MagicMock()
    model.sources = ["drums", "bass", "other", "vocals"]
    model.samplerate = 44100
    return model


# ---------------------------------------------------------------------------
# StemsClient.separate()
# ---------------------------------------------------------------------------


class TestStemsClientSeparate:
    @patch("acemusic.stems_client.demucs_apply")
    @patch("acemusic.stems_client.demucs_pretrained")
    @patch("acemusic.stems_client.ta")
    def test_separate_returns_four_stems(self, mock_ta, mock_pretrained, mock_apply, tmp_path):
        """separate() returns a dict with exactly four stem labels."""
        src = tmp_path / "song.wav"
        src.write_bytes(b"fake wav")

        mock_pretrained.get_model.return_value = _make_mock_model()
        mock_ta.load.return_value = (torch.randn(2, 44100), 44100)
        mock_apply.apply_model.return_value = torch.randn(1, 4, 2, 44100)

        client = StemsClient()
        result = client.separate(src)

        assert set(result.keys()) == set(STEM_LABELS)
        for label in STEM_LABELS:
            assert result[label].ndim == 2  # [channels, samples]

    @patch("acemusic.stems_client.demucs_apply")
    @patch("acemusic.stems_client.demucs_pretrained")
    @patch("acemusic.stems_client.ta")
    def test_separate_caches_model(self, mock_ta, mock_pretrained, mock_apply, tmp_path):
        """Model is loaded once and reused across calls."""
        src = tmp_path / "song.wav"
        src.write_bytes(b"fake wav")

        mock_pretrained.get_model.return_value = _make_mock_model()
        mock_ta.load.return_value = (torch.randn(2, 44100), 44100)
        mock_apply.apply_model.return_value = torch.randn(1, 4, 2, 44100)

        client = StemsClient()
        client.separate(src)
        client.separate(src)

        assert mock_pretrained.get_model.call_count == 1

    def test_separate_missing_file_raises(self, tmp_path):
        """separate() raises StemsError for missing input file."""
        client = StemsClient()
        with pytest.raises(StemsError, match="not found"):
            client.separate(tmp_path / "nonexistent.wav")

    @patch("acemusic.stems_client.demucs_apply")
    @patch("acemusic.stems_client.demucs_pretrained")
    @patch("acemusic.stems_client.ta")
    def test_separate_wraps_demucs_errors(self, mock_ta, mock_pretrained, mock_apply, tmp_path):
        """Errors from demucs are wrapped in StemsError."""
        src = tmp_path / "song.wav"
        src.write_bytes(b"fake wav")

        mock_pretrained.get_model.return_value = _make_mock_model()
        mock_ta.load.return_value = (torch.randn(2, 44100), 44100)
        mock_apply.apply_model.side_effect = RuntimeError("CUDA OOM")

        client = StemsClient()
        with pytest.raises(StemsError, match="Separation failed"):
            client.separate(src)


# ---------------------------------------------------------------------------
# StemsClient.save_stems()
# ---------------------------------------------------------------------------


class TestStemsClientSaveStems:
    @patch("acemusic.stems_client.ta")
    def test_save_stems_creates_four_wav_files(self, mock_ta, tmp_path):
        """save_stems() writes 4 WAV files with correct naming."""
        stems = {label: torch.randn(2, 44100) for label in STEM_LABELS}
        client = StemsClient()
        paths = client.save_stems(stems, tmp_path, "mysong", sample_rate=44100, output_format="wav")

        assert len(paths) == 4
        for label in STEM_LABELS:
            expected = tmp_path / f"mysong-{label}.wav"
            assert expected in paths
            mock_ta.save.assert_any_call(str(expected), stems[label], 44100)

    @patch("acemusic.stems_client.ta")
    def test_save_stems_flac_format(self, mock_ta, tmp_path):
        """save_stems() with format=flac writes FLAC files."""
        stems = {label: torch.randn(2, 44100) for label in STEM_LABELS}
        client = StemsClient()
        paths = client.save_stems(stems, tmp_path, "mysong", sample_rate=44100, output_format="flac")

        for label in STEM_LABELS:
            expected = tmp_path / f"mysong-{label}.flac"
            assert expected in paths

    @patch("acemusic.stems_client.ta")
    def test_save_stems_creates_output_dir(self, mock_ta, tmp_path):
        """save_stems() creates the output directory if it doesn't exist."""
        stems = {label: torch.randn(2, 44100) for label in STEM_LABELS}
        out_dir = tmp_path / "new_dir" / "stems"
        client = StemsClient()
        client.save_stems(stems, out_dir, "mysong", sample_rate=44100)

        assert out_dir.exists()
