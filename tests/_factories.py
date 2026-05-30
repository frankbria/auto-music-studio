"""Shared mock-client factories for export-related tests.

`StemsClient` / `MidiClient` are mocked so unit tests never run real (slow,
optionally-installed) ML inference. The mocks still write genuine WAV/MIDI files
to disk so downstream copy/validate logic is exercised against real artifacts.
Used by both ``test_daw_export.py`` and ``test_export_cli.py``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from acemusic.stems_client import STEM_LABELS


def write_real_wav(path: Path, frames: int = 44100, sample_rate: int = 44100) -> None:
    """Write a silent but valid stereo WAV so file-format handling is real."""
    import numpy as np
    import soundfile as sf

    data = np.zeros((frames, 2), dtype=np.float32)
    sf.write(str(path), data, sample_rate)


def make_stems_client_factory():
    """Factory producing a mock StemsClient that writes real WAV stems on disk."""
    instance = MagicMock()
    instance.model_samplerate = 44100
    instance.separate.return_value = {label: MagicMock() for label in STEM_LABELS}

    def _save(stems, out_dir, base, **kw):
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        fmt = kw.get("output_format", "wav")
        paths = {}
        for label in STEM_LABELS:
            p = out_dir / f"{base}-{label}.{fmt}"
            write_real_wav(p)
            paths[label] = p
        return paths

    instance.save_stems.side_effect = _save
    factory = MagicMock(return_value=instance)
    factory.instance = instance
    return factory


def make_midi_client_factory():
    """Factory producing a mock MidiClient that writes real Type-1 MIDI on disk.

    ``extract`` is stubbed, but ``save_midi`` delegates to the real ``MidiClient``
    so the files written are genuine Type-1 MIDI with correct channel assignments.
    """
    from acemusic.midi_client import MidiClient

    instance = MagicMock()
    instance.extract.return_value = {
        "melody": [(0.0, 0.5, 72, 100), (0.5, 1.0, 74, 90)],
        "chords": [(0.0, 1.0, 60, 80)],
        "drums": [(0.0, 0.1, 36, 127), (0.5, 0.6, 38, 100)],
        "bass": [(0.0, 1.0, 40, 100)],
    }
    real = MidiClient()
    instance.save_midi.side_effect = lambda data, out_dir, base, **kw: real.save_midi(data, out_dir, base, **kw)
    factory = MagicMock(return_value=instance)
    factory.instance = instance
    return factory
