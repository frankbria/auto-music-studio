"""MIDI extraction client using basic-pitch (US-5.4)."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

try:
    import basic_pitch
    import pretty_midi
    import numpy as np
    import librosa
except ImportError:  # pragma: no cover
    basic_pitch = None  # type: ignore[assignment]
    pretty_midi = None  # type: ignore[assignment]
    np = None  # type: ignore[assignment]
    librosa = None  # type: ignore[assignment]


class MidiError(Exception):
    """Raised when MIDI extraction fails."""


MIDI_OUTPUT_LABELS: list[str] = ["melody", "chords", "drums", "bass"]


class MidiClient:
    """Encapsulates basic-pitch-based MIDI extraction."""

    def __init__(self, sample_rate: int = 22050) -> None:
        """Initialize MIDI client.

        Args:
            sample_rate: Sample rate for audio loading (default 22050 Hz).
        """
        self._sample_rate = sample_rate

    def extract(
        self,
        audio_path: Path | str,
        from_stems: bool = False,
        stem_paths: dict[str, Path | str] | None = None,
        progress_callback: Callable[[str], None] | None = None,
    ) -> dict[str, list[tuple[float, float, float]]]:
        """Extract MIDI from audio file.

        Args:
            audio_path: Path to the input audio file.
            from_stems: If True, use stem_paths for better accuracy.
            stem_paths: Optional dict mapping stem labels to paths for improved extraction.
            progress_callback: Optional callable receiving status messages.

        Returns:
            Dict mapping 'melody', 'chords', 'drums', 'bass' to lists of (time, midi_note, confidence) tuples.

        Raises:
            MidiError: If the file is missing or extraction fails.
        """
        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise MidiError(f"Input file not found: {audio_path}")

        if basic_pitch is None:
            raise MidiError(
                "basic_pitch is not installed. Install with: uv pip install 'acemusic[audio-ml-midi]'"
            )

        if progress_callback:
            progress_callback("Loading audio...")

        try:
            # Load audio
            y, sr = librosa.load(str(audio_path), sr=self._sample_rate, mono=True)
        except Exception as exc:
            raise MidiError(f"Failed to load audio: {exc}") from exc

        if progress_callback:
            progress_callback("Extracting MIDI contours...")

        result = {}

        # Use full mix for melody/harmony extraction
        try:
            # Extract fundamental frequencies and convert to MIDI
            contour_data = basic_pitch.predict_contour(
                y, sample_rate=sr, fmin=30, fmax=400, threshold=0.1
            )
            result["melody"] = self._contour_to_midi_notes(contour_data, time_scale=len(y) / sr)
        except Exception as exc:
            raise MidiError(f"Failed to extract melody: {exc}") from exc

        # Extract chords (harmonic analysis)
        try:
            chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
            result["chords"] = self._chroma_to_midi_chords(chroma, time_scale=len(y) / sr)
        except Exception as exc:
            raise MidiError(f"Failed to extract chords: {exc}") from exc

        # Extract drums and bass from stems or full mix
        if from_stems and stem_paths:
            try:
                # Use bass stem for bass extraction
                if "bass" in stem_paths:
                    bass_y, bass_sr = librosa.load(str(stem_paths["bass"]), sr=self._sample_rate, mono=True)
                    bass_contour = basic_pitch.predict_contour(
                        bass_y, sample_rate=bass_sr, fmin=20, fmax=150, threshold=0.1
                    )
                    result["bass"] = self._contour_to_midi_notes(bass_contour, time_scale=len(bass_y) / bass_sr)
                else:
                    result["bass"] = []

                # Use drums stem for drum extraction (just note onsets)
                if "drums" in stem_paths:
                    drums_y, drums_sr = librosa.load(str(stem_paths["drums"]), sr=self._sample_rate, mono=True)
                    drum_notes = self._extract_drum_notes(drums_y, drums_sr)
                    result["drums"] = drum_notes
                else:
                    result["drums"] = []
            except Exception as exc:
                raise MidiError(f"Failed to extract from stems: {exc}") from exc
        else:
            # Fallback: estimate from full mix
            try:
                # Simple drum detection from energy peaks
                result["drums"] = self._extract_drum_notes(y, sr)
                # Estimate bass from lower frequencies
                bass_y = librosa.effects.preemphasis(y, coef=-0.97)
                bass_contour = basic_pitch.predict_contour(
                    bass_y, sample_rate=sr, fmin=20, fmax=150, threshold=0.1
                )
                result["bass"] = self._contour_to_midi_notes(bass_contour, time_scale=len(y) / sr)
            except Exception as exc:
                raise MidiError(f"Failed to extract drums/bass: {exc}") from exc

        return result

    @staticmethod
    def _contour_to_midi_notes(
        contour_data: tuple, time_scale: float, hop_length: int = 512, sample_rate: int = 22050
    ) -> list[tuple[float, float, float]]:
        """Convert basic_pitch contour output to MIDI note list.

        Args:
            contour_data: Output from basic_pitch.predict_contour()
            time_scale: Total duration in seconds
            hop_length: Hop length used in STFT
            sample_rate: Sample rate of audio

        Returns:
            List of (time, midi_note, confidence) tuples
        """
        if contour_data is None or len(contour_data) == 0:
            return []

        contour, confidence = contour_data

        notes = []
        current_note_start = None
        current_midi = None
        current_confidence = 0

        frames = len(confidence)
        frame_duration = time_scale / frames

        for frame_idx, (freq, conf) in enumerate(zip(contour, confidence)):
            time = frame_idx * frame_duration

            if freq <= 0 or conf < 0.1:
                # Note off
                if current_note_start is not None:
                    notes.append((current_note_start, current_midi, current_confidence))
                    current_note_start = None
                    current_midi = None
            else:
                # Convert frequency to MIDI note
                midi_note = librosa.hz_to_midi(freq) if librosa else MidiClient._hz_to_midi(freq)

                if current_note_start is None:
                    # Note on
                    current_note_start = time
                    current_midi = midi_note
                    current_confidence = conf
                elif abs(midi_note - current_midi) > 0.5:
                    # Note changed
                    notes.append((current_note_start, current_midi, current_confidence))
                    current_note_start = time
                    current_midi = midi_note
                    current_confidence = conf
                else:
                    # Sustain note, update with higher confidence if available
                    if conf > current_confidence:
                        current_confidence = conf

        # Close out final note if any
        if current_note_start is not None:
            notes.append((current_note_start, current_midi, current_confidence))

        return notes

    @staticmethod
    def _chroma_to_midi_chords(chroma: np.ndarray, time_scale: float) -> list[tuple[float, float, float]]:
        """Extract chord information from chroma features.

        Args:
            chroma: Chroma feature matrix from librosa
            time_scale: Total duration in seconds

        Returns:
            List of (time, chord_root_midi, confidence) tuples
        """
        if chroma is None or chroma.size == 0:
            return []

        chords = []
        frames = chroma.shape[1]
        frame_duration = time_scale / frames

        for frame_idx in range(frames):
            time = frame_idx * frame_duration
            # Find dominant pitch class (0-11, representing C through B)
            pitch_class = chroma[:, frame_idx].argmax()
            # Map to MIDI note (using C4 = 60 as root)
            chord_root = 60 + pitch_class
            confidence = float(chroma[pitch_class, frame_idx])

            if confidence > 0.1:
                chords.append((time, float(chord_root), confidence))

        return chords

    @staticmethod
    def _extract_drum_notes(audio: np.ndarray, sample_rate: int, threshold: float = 0.5) -> list[tuple[float, float, float]]:
        """Extract drum note onsets from audio.

        Args:
            audio: Audio signal
            sample_rate: Sample rate in Hz
            threshold: Onset detection threshold

        Returns:
            List of (time, midi_note, confidence) tuples
        """
        if librosa is None:
            return []

        try:
            # Detect onsets
            onset_env = librosa.onset.onset_strength(y=audio, sr=sample_rate)
            onsets = librosa.onset.onset_detect(onset_env=onset_env, sr=sample_rate, backtrack=True)

            drums = []
            for onset_frame in onsets:
                time = librosa.frames_to_time(onset_frame, sr=sample_rate)
                # Use fixed drum note (e.g., kick drum = MIDI 36)
                drums.append((time, 36.0, 1.0))

            return drums
        except Exception:
            return []

    @staticmethod
    def _hz_to_midi(frequency: float) -> float:
        """Convert frequency in Hz to MIDI note number.

        Args:
            frequency: Frequency in Hertz

        Returns:
            MIDI note number (floating point)
        """
        if frequency <= 0:
            return 0.0
        return 12.0 * (frequency / 440.0) ** (1.0 / 12.0) + 69.0

    @staticmethod
    def save_midi(
        midi_data: dict[str, list[tuple[float, float, float]]],
        output_dir: Path | str,
        base_name: str,
        tempo: float = 120.0,
    ) -> dict[str, Path]:
        """Save extracted MIDI data to files.

        Args:
            midi_data: Dict from extract() method
            output_dir: Directory to write MIDI files into
            base_name: Base filename (without extension)
            tempo: Tempo in BPM for MIDI file

        Returns:
            Dict mapping label to the path of the written MIDI file
        """
        if pretty_midi is None:
            raise MidiError("pretty_midi is not installed. Install with: uv pip install 'acemusic[audio-ml-midi]'")

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        paths: dict[str, Path] = {}

        for label in MIDI_OUTPUT_LABELS:
            if label not in midi_data or not midi_data[label]:
                continue

            # Create a MIDI file
            midi_file = pretty_midi.PrettyMIDI(initial_tempo=tempo)
            instrument = pretty_midi.Instrument(program=0)  # Acoustic Grand Piano

            notes_data = midi_data[label]

            # Convert extracted notes to MIDI Note objects
            note_end_time = 0
            for i, (start_time, note_value, confidence) in enumerate(notes_data):
                # Determine note duration
                if i < len(notes_data) - 1:
                    end_time = notes_data[i + 1][0]
                else:
                    end_time = start_time + 0.5  # Default 500ms for last note

                # Create MIDI note
                midi_note = int(round(note_value))
                velocity = int(min(127, max(64, confidence * 100)))

                note_obj = pretty_midi.Note(velocity=velocity, pitch=midi_note, start=start_time, end=end_time)
                instrument.notes.append(note_obj)
                note_end_time = max(note_end_time, end_time)

            midi_file.instruments.append(instrument)

            # Write to file
            output_path = output_dir / f"{base_name}-{label}.mid"
            midi_file.write(str(output_path))
            paths[label] = output_path

        return paths
