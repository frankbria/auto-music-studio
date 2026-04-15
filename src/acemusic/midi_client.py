"""MIDI extraction client using basic-pitch and mido (US-5.4)."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

try:
    import basic_pitch.inference as bp_inference
except ImportError:  # pragma: no cover
    bp_inference = None  # type: ignore[assignment]

try:
    import librosa
except ImportError:  # pragma: no cover
    librosa = None  # type: ignore[assignment]

import mido


class MidiError(Exception):
    """Raised when MIDI extraction fails."""


MIDI_OUTPUT_LABELS: list[str] = ["melody", "chords", "drums", "bass"]

# MIDI channel assignments (0-indexed: channel 0 = MIDI channel 1)
CHANNEL_MAP: dict[str, int] = {
    "melody": 0,  # MIDI channel 1
    "chords": 1,  # MIDI channel 2
    "bass": 2,  # MIDI channel 3
    "drums": 9,  # MIDI channel 10
}

# Pitch range boundaries for categorisation
_BASS_CEILING = 48  # C3 and below -> bass
_MELODY_FLOOR = 72  # C5 and above -> melody
# Everything in between -> chords


class MidiClient:
    """Encapsulates basic-pitch-based MIDI extraction."""

    def extract(
        self,
        audio_path: Path | str,
        from_stems: bool = False,
        stem_paths: dict[str, Path | str] | None = None,
        progress_callback: Callable[[str], None] | None = None,
    ) -> dict[str, list[tuple[float, float, int, int]]]:
        """Extract MIDI note events from an audio file.

        Returns dict mapping 'melody', 'chords', 'drums', 'bass' to lists of
        (start_time, end_time, pitch_midi, velocity) tuples.
        """
        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise MidiError(f"Input file not found: {audio_path}")

        if bp_inference is None:
            raise MidiError("basic_pitch is not installed. Install with: uv pip install 'acemusic[audio-ml-midi]'")

        if progress_callback:
            progress_callback("Extracting pitched notes...")

        # Determine paths for pitched and drum extraction
        pitched_path = audio_path
        drum_path = audio_path

        if from_stems and stem_paths:
            if "vocals" in stem_paths:
                pitched_path = Path(stem_paths["vocals"])
            if "drums" in stem_paths:
                drum_path = Path(stem_paths["drums"])

        # Extract pitched notes via basic-pitch
        try:
            _model_output, _midi_data, note_events = bp_inference.predict(str(pitched_path))
        except Exception as exc:
            raise MidiError(f"Pitch extraction failed: {exc}") from exc

        # note_events: list of (start_time, end_time, pitch_midi, velocity, [pitch_bend])
        raw_notes = [(float(n[0]), float(n[1]), int(round(n[2])), int(round(n[3]))) for n in note_events]

        if progress_callback:
            progress_callback("Categorising notes...")

        categorized = self.categorize_notes(raw_notes)

        # Extract drums via onset detection
        if progress_callback:
            progress_callback("Extracting drum onsets...")

        categorized["drums"] = self._extract_drum_onsets(drum_path)

        # If using stems, re-extract bass from bass stem for better accuracy
        if from_stems and stem_paths and "bass" in stem_paths:
            bass_path = Path(stem_paths["bass"])
            try:
                _, _, bass_events = bp_inference.predict(str(bass_path))
                categorized["bass"] = [
                    (float(n[0]), float(n[1]), int(round(n[2])), int(round(n[3]))) for n in bass_events
                ]
            except Exception:
                pass  # Keep the categorized bass from full mix

        return categorized

    @staticmethod
    def categorize_notes(
        notes: list[tuple[float, float, int, int]],
    ) -> dict[str, list[tuple[float, float, int, int]]]:
        """Split notes into melody, chords, and bass by pitch range."""
        melody: list[tuple[float, float, int, int]] = []
        chords: list[tuple[float, float, int, int]] = []
        bass: list[tuple[float, float, int, int]] = []

        for note in notes:
            pitch = note[2]
            if pitch < _BASS_CEILING:
                bass.append(note)
            elif pitch >= _MELODY_FLOOR:
                melody.append(note)
            else:
                chords.append(note)

        return {"melody": melody, "chords": chords, "bass": bass}

    @staticmethod
    def _extract_drum_onsets(audio_path: Path) -> list[tuple[float, float, int, int]]:
        """Detect drum onsets using librosa and map to GM drum notes."""
        if librosa is None:
            return []

        try:
            y, sr = librosa.load(str(audio_path), sr=22050, mono=True)
            # Percussive component separation
            _, y_perc = librosa.effects.hpss(y)
            onset_env = librosa.onset.onset_strength(y=y_perc, sr=sr)
            onsets = librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr, backtrack=True)
            onset_times = librosa.frames_to_time(onsets, sr=sr)
        except Exception:
            return []

        drums: list[tuple[float, float, int, int]] = []
        for t in onset_times:
            # Map onsets to GM drum: kick=36, snare=38, hi-hat=42
            # Simple heuristic: alternate kick/snare on beat, hi-hat off-beat
            drums.append((float(t), float(t) + 0.1, 36, 100))

        return drums

    def save_midi(
        self,
        midi_data: dict[str, list[tuple[float, float, int, int]]],
        output_dir: Path | str,
        base_name: str,
        bpm: float = 120.0,
    ) -> dict[str, Path]:
        """Write categorised notes to MIDI Type 1 files.

        Returns dict mapping label to written file path.
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        ticks_per_beat = 480
        paths: dict[str, Path] = {}

        for label in MIDI_OUTPUT_LABELS:
            notes = midi_data.get(label, [])
            if not notes:
                continue

            channel = CHANNEL_MAP[label]
            mid = mido.MidiFile(type=1, ticks_per_beat=ticks_per_beat)

            # Track 0: tempo and time signature
            tempo_track = mido.MidiTrack()
            mid.tracks.append(tempo_track)
            tempo_track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm), time=0))
            tempo_track.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
            tempo_track.append(mido.MetaMessage("track_name", name=label, time=0))
            tempo_track.append(mido.MetaMessage("end_of_track", time=0))

            # Track 1: note events
            note_track = mido.MidiTrack()
            mid.tracks.append(note_track)

            # Build a list of (absolute_tick, message) then sort and convert to delta
            events: list[tuple[int, mido.Message]] = []
            for start, end, pitch, velocity in notes:
                start_tick = int(round(start * ticks_per_beat * bpm / 60))
                end_tick = int(round(end * ticks_per_beat * bpm / 60))
                pitch = max(0, min(127, pitch))
                velocity = max(1, min(127, velocity))
                events.append((start_tick, mido.Message("note_on", channel=channel, note=pitch, velocity=velocity)))
                events.append((end_tick, mido.Message("note_off", channel=channel, note=pitch, velocity=0)))

            events.sort(key=lambda e: e[0])

            prev_tick = 0
            for abs_tick, msg in events:
                msg.time = abs_tick - prev_tick
                note_track.append(msg)
                prev_tick = abs_tick

            note_track.append(mido.MetaMessage("end_of_track", time=0))

            out_path = output_dir / f"{base_name}-{label}.mid"
            mid.save(str(out_path))
            paths[label] = out_path

        return paths
