"""Audio analysis and manipulation utilities for acemusic (US-4.4, US-5.1)."""

from __future__ import annotations

from pathlib import Path

SUPPORTED_FORMATS: set[str] = {".wav", ".flac", ".mp3", ".ogg", ".aac", ".aiff"}

_PITCH_CLASSES: list[str] = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def detect_bpm(path: Path) -> float | None:
    """Return estimated BPM for the audio file, or None if detection fails."""
    try:
        import librosa

        y, sr = librosa.load(str(path), mono=True)
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        return float(tempo)
    except Exception:
        return None


def detect_key(path: Path) -> str | None:
    """Return estimated musical key (e.g. 'C major') for the audio file, or None on failure."""
    try:
        import librosa

        y, sr = librosa.load(str(path), mono=True)
        chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
        dominant = int(chroma.mean(axis=1).argmax())
        return f"{_PITCH_CLASSES[dominant]} major"
    except Exception:
        return None


def crop_audio(
    input_path: str,
    output_path: str,
    start_ms: int,
    end_ms: int,
    fade_in_ms: int = 0,
    fade_out_ms: int = 0,
) -> None:
    """Trim an audio file to [start_ms, end_ms] and optionally apply fades.

    Loads input_path, slices to the given range, applies fade-in/fade-out if
    requested, and exports to output_path preserving the original format.
    The original file is never modified.
    """
    from pydub import AudioSegment

    audio = AudioSegment.from_file(input_path)
    segment = audio[start_ms:end_ms]
    if fade_in_ms > 0:
        segment = segment.fade_in(fade_in_ms)
    if fade_out_ms > 0:
        segment = segment.fade_out(fade_out_ms)
    fmt = output_path.rsplit(".", 1)[-1] if "." in output_path else "wav"
    segment.export(output_path, format=fmt)
