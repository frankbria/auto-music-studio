"""Audio analysis utilities for acemusic (US-4.4)."""

from __future__ import annotations

from pathlib import Path

import librosa

SUPPORTED_FORMATS: set[str] = {".wav", ".flac", ".mp3", ".ogg", ".aac", ".aiff"}

_PITCH_CLASSES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def detect_bpm(path: Path) -> float | None:
    """Return estimated BPM for the audio file, or None if detection fails."""
    try:
        y, sr = librosa.load(str(path), mono=True)
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        return float(tempo)
    except Exception:
        return None


def detect_key(path: Path) -> str | None:
    """Return estimated musical key (e.g. 'C major') for the audio file, or None on failure."""
    try:
        y, sr = librosa.load(str(path), mono=True)
        chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
        dominant = int(chroma.mean(axis=1).argmax())
        return f"{_PITCH_CLASSES[dominant]} major"
    except Exception:
        return None
