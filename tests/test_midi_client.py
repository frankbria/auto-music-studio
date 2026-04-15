"""Tests for the MIDI extraction client (US-5.4)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Unit tests for MidiClient
# ---------------------------------------------------------------------------


class TestCategorizeNotes:
    def test_splits_notes_by_pitch_range(self):
        """Notes are categorized into melody, chords, and bass by pitch range."""
        from acemusic.midi_client import MidiClient

        # (start_time, end_time, pitch_midi, velocity)
        notes = [
            (0.0, 0.5, 72, 100),  # melody (C5)
            (0.0, 0.5, 76, 90),  # melody (E5)
            (0.0, 0.5, 60, 80),  # chords (C4)
            (0.0, 0.5, 64, 80),  # chords (E4)
            (0.0, 0.5, 36, 100),  # bass (C2)
            (0.0, 0.5, 40, 90),  # bass (E2)
        ]
        result = MidiClient.categorize_notes(notes)

        assert "melody" in result
        assert "chords" in result
        assert "bass" in result
        # Bass notes should be in the bass category (pitch < 48)
        bass_pitches = [n[2] for n in result["bass"]]
        assert 36 in bass_pitches
        assert 40 in bass_pitches
        # Melody notes should be in melody category (pitch >= 72)
        melody_pitches = [n[2] for n in result["melody"]]
        assert 72 in melody_pitches
        assert 76 in melody_pitches

    def test_empty_notes_returns_empty_categories(self):
        """Empty input returns empty categories."""
        from acemusic.midi_client import MidiClient

        result = MidiClient.categorize_notes([])
        assert result["melody"] == []
        assert result["chords"] == []
        assert result["bass"] == []


class TestSaveMidi:
    def test_creates_valid_midi_files(self, tmp_path):
        """save_midi writes valid MIDI Type 1 files with correct structure."""
        from acemusic.midi_client import MidiClient

        client = MidiClient()
        categorized = {
            "melody": [(0.0, 0.5, 72, 100), (0.5, 1.0, 74, 90)],
            "chords": [(0.0, 1.0, 60, 80)],
            "drums": [(0.0, 0.1, 36, 127), (0.5, 0.6, 38, 100)],
            "bass": [(0.0, 1.0, 36, 100)],
        }
        paths = client.save_midi(categorized, tmp_path, "test_song", bpm=120.0)

        assert len(paths) == 4
        for label, path in paths.items():
            assert path.exists()
            assert path.suffix == ".mid"
            # Verify MIDI header magic bytes
            data = path.read_bytes()
            assert data[:4] == b"MThd"

    def test_respects_bpm_in_tempo_track(self, tmp_path):
        """Written MIDI file contains correct tempo meta message."""
        import mido

        from acemusic.midi_client import MidiClient

        client = MidiClient()
        categorized = {
            "melody": [(0.0, 0.5, 72, 100)],
            "chords": [],
            "drums": [],
            "bass": [],
        }
        paths = client.save_midi(categorized, tmp_path, "tempo_test", bpm=140.0)

        midi_file = mido.MidiFile(str(paths["melody"]))
        # Find tempo message in first track
        tempo_msgs = [msg for msg in midi_file.tracks[0] if msg.type == "set_tempo"]
        assert len(tempo_msgs) == 1
        expected_tempo = mido.bpm2tempo(140.0)
        assert tempo_msgs[0].tempo == expected_tempo

    def test_correct_channel_assignments(self, tmp_path):
        """MIDI channels: melody=0, chords=1, drums=9, bass=2."""
        import mido

        from acemusic.midi_client import MidiClient

        client = MidiClient()
        categorized = {
            "melody": [(0.0, 0.5, 72, 100)],
            "chords": [(0.0, 0.5, 60, 80)],
            "drums": [(0.0, 0.1, 36, 127)],
            "bass": [(0.0, 0.5, 36, 100)],
        }
        paths = client.save_midi(categorized, tmp_path, "channel_test", bpm=120.0)

        # Check melody uses channel 0 (MIDI channel 1)
        midi_file = mido.MidiFile(str(paths["melody"]))
        note_msgs = [msg for track in midi_file.tracks for msg in track if msg.type == "note_on"]
        assert all(msg.channel == 0 for msg in note_msgs)

        # Check drums uses channel 9 (MIDI channel 10)
        midi_file = mido.MidiFile(str(paths["drums"]))
        note_msgs = [msg for track in midi_file.tracks for msg in track if msg.type == "note_on"]
        assert all(msg.channel == 9 for msg in note_msgs)

    def test_empty_category_skipped(self, tmp_path):
        """Empty categories don't produce MIDI files."""
        from acemusic.midi_client import MidiClient

        client = MidiClient()
        categorized = {
            "melody": [(0.0, 0.5, 72, 100)],
            "chords": [],
            "drums": [],
            "bass": [],
        }
        paths = client.save_midi(categorized, tmp_path, "sparse", bpm=120.0)

        assert "melody" in paths
        assert "chords" not in paths
        assert "drums" not in paths
        assert "bass" not in paths


class TestExtract:
    def test_raises_on_missing_file(self):
        """extract() raises MidiError for non-existent audio file."""
        from acemusic.midi_client import MidiClient, MidiError

        client = MidiClient()
        with pytest.raises(MidiError, match="not found"):
            client.extract(Path("/nonexistent/audio.wav"))

    def test_raises_when_basic_pitch_not_installed(self, tmp_path):
        """extract() raises MidiError when basic_pitch is not available."""
        from acemusic.midi_client import MidiClient, MidiError

        audio_file = tmp_path / "test.wav"
        audio_file.write_bytes(b"fake audio")

        client = MidiClient()
        with patch("acemusic.midi_client.bp_inference", None):
            with pytest.raises(MidiError, match="not installed"):
                client.extract(audio_file)
