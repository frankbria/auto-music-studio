"""Audio analysis and manipulation utilities for acemusic (US-4.4, US-5.1, US-5.5)."""

from __future__ import annotations

from pathlib import Path

import numpy as np

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

    # Export to file
    sf.write(output_path, y_stretched.T if y_stretched.ndim > 1 else y_stretched, sr, subtype="PCM_16")


# ---------------------------------------------------------------------------
# Remaster pipeline (US-5.5)
# ---------------------------------------------------------------------------


def measure_lufs(audio: np.ndarray, sample_rate: int) -> float:
    """Measure integrated loudness (LUFS) using ITU-R BS.1770-4."""
    import pyloudnorm as pyln

    meter = pyln.Meter(sample_rate)
    return meter.integrated_loudness(audio)


def normalize_loudness(audio: np.ndarray, sample_rate: int, target_lufs: float) -> np.ndarray:
    """Normalize audio to target LUFS with true-peak limiting at -1 dBTP."""
    import pyloudnorm as pyln

    meter = pyln.Meter(sample_rate)
    current_lufs = meter.integrated_loudness(audio)

    if not np.isfinite(current_lufs):
        return audio.copy()

    normalized = pyln.normalize.loudness(audio, current_lufs, target_lufs)

    # True-peak limiting at -1 dBTP (~0.891)
    peak_limit = 10 ** (-1.0 / 20.0)
    peak = np.max(np.abs(normalized))
    if peak > peak_limit:
        normalized = normalized * (peak_limit / peak)

    return normalized


def apply_eq(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    """Apply gentle EQ: presence boost (~3kHz) and low-end warmth (~100Hz).

    Uses scipy IIR peak filters (second-order) for frequency-selective boosts.
    """
    from scipy.signal import iirpeak, lfilter

    result = audio.copy()

    # Presence boost: +3dB peak at 3kHz, Q=1.0
    b_pres, a_pres = iirpeak(3000 / (sample_rate / 2), 1.0)
    gain_presence = 10 ** (3.0 / 20.0)

    # Low-end warmth: +2dB peak at 100Hz, Q=0.7
    b_low, a_low = iirpeak(100 / (sample_rate / 2), 0.7)
    gain_low = 10 ** (2.0 / 20.0)

    for ch in range(result.shape[1] if result.ndim > 1 else 1):
        channel = result[:, ch] if result.ndim > 1 else result
        # Apply as parallel EQ: original + boosted bands
        presence_band = lfilter(b_pres, a_pres, channel)
        low_band = lfilter(b_low, a_low, channel)
        # Mix: original + gain * filtered bands (shelf-style additive EQ)
        filtered = channel + (gain_presence - 1.0) * presence_band + (gain_low - 1.0) * low_band
        if result.ndim > 1:
            result[:, ch] = filtered
        else:
            result = filtered

    return result


def apply_compression(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    """Apply soft-knee dynamic range compression.

    Uses envelope-following with moderate ratio (3:1), ~10ms attack, ~100ms release.
    Loudness recovery is handled by the pipeline's final normalization pass.
    """
    threshold_db = -20.0
    ratio = 3.0
    attack_s = 0.01
    release_s = 0.1
    knee_db = 6.0

    attack_coeff = np.exp(-1.0 / (sample_rate * attack_s))
    release_coeff = np.exp(-1.0 / (sample_rate * release_s))

    result = audio.copy()
    if result.ndim > 1:
        envelope_signal = np.mean(np.abs(result), axis=1)
    else:
        envelope_signal = np.abs(result)

    # Pre-compute sample dB levels as a vector (avoids per-sample np calls)
    sample_db_all = 20.0 * np.log10(envelope_signal + 1e-10)

    n_samples = len(envelope_signal)
    env_db_arr = np.empty(n_samples)
    env_db = -120.0

    # Envelope follower (sequential — state-dependent)
    for i in range(n_samples):
        s = sample_db_all[i]
        if s > env_db:
            env_db = attack_coeff * env_db + (1.0 - attack_coeff) * s
        else:
            env_db = release_coeff * env_db + (1.0 - release_coeff) * s
        env_db_arr[i] = env_db

    # Vectorized gain computation (soft-knee)
    over_db = env_db_arr - threshold_db
    gain_reduction = 1.0 - 1.0 / ratio
    gain_db = np.where(
        over_db <= -knee_db / 2,
        0.0,
        np.where(
            over_db >= knee_db / 2,
            -gain_reduction * over_db,
            -gain_reduction * (over_db + knee_db / 2) ** 2 / (2.0 * knee_db),
        ),
    )

    gain_linear = 10.0 ** (gain_db / 20.0)

    if result.ndim > 1:
        for ch in range(result.shape[1]):
            result[:, ch] *= gain_linear
    else:
        result *= gain_linear

    return result


def apply_stereo_widening(audio: np.ndarray, amount: float = 1.2) -> np.ndarray:
    """Apply stereo widening via mid/side processing.

    amount=1.0 is neutral, >1.0 widens, <1.0 narrows, 0.0 collapses to mono.
    Includes mono-compatibility safeguard.
    """
    if audio.ndim < 2 or audio.shape[1] < 2:
        return audio

    left = audio[:, 0]
    right = audio[:, 1]

    mid = (left + right) / 2.0
    side = (left - right) / 2.0

    side_scaled = side * amount

    new_left = mid + side_scaled
    new_right = mid - side_scaled

    result = np.column_stack([new_left, new_right])

    # Mono-compatibility safeguard: prevent clipping
    peak = np.max(np.abs(result))
    if peak > 1.0:
        result /= peak

    return result


def remaster_audio(input_path: Path, output_path: Path, target_lufs: float = -14.0) -> dict:
    """Orchestrate the full remaster pipeline: normalize → EQ → compress → widen → peak-limit → write.

    Returns a dict with before/after LUFS measurements.
    """
    import soundfile as sf

    audio, sample_rate = sf.read(str(input_path))

    # Ensure stereo
    if audio.ndim == 1:
        audio = np.column_stack([audio, audio])

    before_lufs = measure_lufs(audio, sample_rate)

    # Pipeline: normalize → EQ → compress → widen
    audio = normalize_loudness(audio, sample_rate, target_lufs)
    audio = apply_eq(audio, sample_rate)
    audio = apply_compression(audio, sample_rate)
    audio = apply_stereo_widening(audio, amount=1.2)

    # Final loudness pass to hit target after processing
    audio = normalize_loudness(audio, sample_rate, target_lufs)

    after_lufs = measure_lufs(audio, sample_rate)

    sf.write(str(output_path), audio, sample_rate, subtype="PCM_16")

    return {
        "before_lufs": before_lufs,
        "after_lufs": after_lufs,
    }
