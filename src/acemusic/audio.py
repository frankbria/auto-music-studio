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
    fmt = output_path.rsplit(".", 1)[-1].lower() if "." in output_path else "wav"
    segment.export(output_path, format=fmt)


def calculate_speed_multiplier(original_bpm: float, target_bpm: float) -> float:
    """Calculate the playback speed multiplier to go from original to target BPM.

    When time-stretching to change from original_bpm to target_bpm without
    changing pitch, the multiplier is target_bpm / original_bpm.
    For example, going from 120 BPM to 100 BPM means multiplier = 100/120 = 0.833.

    Args:
        original_bpm: Current BPM of the audio
        target_bpm: Desired BPM after time-stretch

    Returns:
        Float multiplier to apply (> 0)

    Raises:
        ValueError if original_bpm or target_bpm is <= 0
    """
    if original_bpm <= 0:
        raise ValueError(f"original_bpm must be positive, got {original_bpm}")
    if target_bpm <= 0:
        raise ValueError(f"target_bpm must be positive, got {target_bpm}")

    return target_bpm / original_bpm


def time_stretch_audio(
    input_path: str,
    output_path: str,
    rate: float,
) -> None:
    """Time-stretch (resample) audio to change playback speed without changing pitch.

    Uses librosa's phase vocoder to change the speed of the audio.
    A rate > 1.0 speeds up the audio, rate < 1.0 slows it down.
    Pitch is preserved (no pitch-shift occurs).

    Args:
        input_path: Path to input audio file
        output_path: Path to write output audio file
        rate: Stretch rate (e.g. 0.9 for 90% speed, 1.1 for 110% speed)

    Raises:
        ValueError if rate <= 0
        Exception if librosa operations fail
    """
    if rate <= 0:
        raise ValueError(f"rate must be positive, got {rate}")

    import librosa
    import soundfile as sf

    # Load audio
    y, sr = librosa.load(str(input_path), mono=False)

    # Apply time-stretch using phase vocoder
    y_stretched = librosa.effects.time_stretch(y, rate=rate)

    # Infer output format from extension
    fmt = output_path.rsplit(".", 1)[-1].lower() if "." in output_path else "wav"

    # Export to file
    sf.write(output_path, y_stretched.T if y_stretched.ndim > 1 else y_stretched, sr, subtype="PCM_16")
