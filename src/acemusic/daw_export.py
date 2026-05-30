"""DAW bundle export (US-7.2).

Packages a clip and its derived stems and MIDI into a ZIP archive laid out for
import into a digital audio workstation:

    <Slug>_Export/
      audio/full_mix.wav
      audio/vocals.wav  audio/drums.wav  audio/bass.wav  audio/other.wav
      midi/melody.mid   midi/chords.mid  midi/drums.mid   midi/bass.mid
      project.json
      artwork.jpg

Stems and MIDI are reused from existing child clips when their files are
present; otherwise they are generated on demand via the stems/MIDI clients,
following the same flow as the `stems` and `midi` CLI commands.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from acemusic.audio import export_audio
from acemusic.db import create_clip, list_clips
from acemusic.midi_client import CHANNEL_MAP, MIDI_OUTPUT_LABELS, MidiClient
from acemusic.models import Clip
from acemusic.stems_client import STEM_LABELS, StemsClient
from acemusic.utils import get_duration, make_slug

CANONICAL_STEMS: tuple[str, ...] = ("vocals", "drums", "bass", "other")

_PLACEHOLDER_JPEG: bytes = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14"
    b"\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.'"
    b" \",#\x1c\x1c(7),01444\x1f'9=82<.342\xff\xdb\x00C\x01\t\t\t\x0c\x0b\x0c\x18"
    b"\r\r\x182!\x1c!2222222222222222222222222222222222222222222222222222"
    b'\xff\xc0\x00\x11\x08\x00\x01\x00\x01\x03\x01"\x00\x02\x11\x01\x03\x11\x01'
    b"\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xc4\x00\xb5\x10\x00"
    b"\x02\x01\x03\x03\x02\x04\x03\x05\x05\x04\x04\x00\x00\x01}\x01\x02\x03\x00\x04"
    b'\x11\x05\x12!1A\x06\x13Qa\x07"q\x142\x81\x91\xa1\x08#B\xb1\xc1\x15R\xd1\xf0'
    b"$3br\x82\t\n\x16\x17\x18\x19\x1a%&'()*456789:CDEFGHIJSTUVWXYZcdefghijstuvwxyz"
    b"\x83\x84\x85\x86\x87\x88\x89\x8a\x92\x93\x94\x95\x96\x97\x98\x99\x9a\xa2\xa3"
    b"\xa4\xa5\xa6\xa7\xa8\xa9\xaa\xb2\xb3\xb4\xb5\xb6\xb7\xb8\xb9\xba\xc2\xc3\xc4"
    b"\xc5\xc6\xc7\xc8\xc9\xca\xd2\xd3\xd4\xd5\xd6\xd7\xd8\xd9\xda\xe1\xe2\xe3\xe4"
    b"\xe5\xe6\xe7\xe8\xe9\xea\xf1\xf2\xf3\xf4\xf5\xf6\xf7\xf8\xf9\xfa\xff\xc4\x00"
    b"\x1f\x01\x00\x03\x01\x01\x01\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00"
    b"\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xc4\x00\xb5\x11\x00\x02\x01\x02"
    b"\x04\x04\x03\x04\x07\x05\x04\x04\x00\x01\x02w\x00\x01\x02\x03\x11\x04\x05!1"
    b'\x06\x12AQ\x07aq\x13"2\x81\x08\x14B\x91\xa1\xb1\xc1\t#3R\xf0\x15br\xd1\n\x16'
    b"$4\xe1%\xf1\x17\x18\x19\x1a&'()*56789:CDEFGHIJSTUVWXYZcdefghijstuvwxyz\x82\x83"
    b"\x84\x85\x86\x87\x88\x89\x8a\x92\x93\x94\x95\x96\x97\x98\x99\x9a\xa2\xa3\xa4"
    b"\xa5\xa6\xa7\xa8\xa9\xaa\xb2\xb3\xb4\xb5\xb6\xb7\xb8\xb9\xba\xc2\xc3\xc4\xc5"
    b"\xc6\xc7\xc8\xc9\xca\xd2\xd3\xd4\xd5\xd6\xd7\xd8\xd9\xda\xe2\xe3\xe4\xe5\xe6"
    b"\xe7\xe8\xe9\xea\xf2\xf3\xf4\xf5\xf6\xf7\xf8\xf9\xfa\xff\xda\x00\x0c\x03\x01"
    b"\x00\x02\x11\x03\x11\x00?\x00\xf9\xfe\x8a(\xa0\x0f\xff\xd9"
)


@dataclass
class Marker:
    """A named position in the timeline (seconds)."""

    name: str
    time: float

    def to_dict(self) -> dict:
        return {"name": self.name, "time": self.time}


@dataclass
class StemReference:
    """Reference to an audio stem file inside the bundle."""

    name: str
    file: str

    def to_dict(self) -> dict:
        return {"name": self.name, "file": self.file}


@dataclass
class MidiReference:
    """Reference to a MIDI file inside the bundle, with its MIDI channel."""

    name: str
    file: str
    channel: int

    def to_dict(self) -> dict:
        return {"name": self.name, "file": self.file, "channel": self.channel}


@dataclass
class ProjectMetadata:
    """Project-level metadata written to ``project.json`` in the bundle."""

    project_name: str
    bpm: Optional[int]
    key: Optional[str]
    time_signature: Optional[str]
    duration_seconds: Optional[float]
    stems: list[StemReference] = field(default_factory=list)
    midi_files: list[MidiReference] = field(default_factory=list)
    markers: list[Marker] = field(default_factory=list)
    lyrics: Optional[str] = None
    style_tags: Optional[str] = None
    source_model: Optional[str] = None
    generation_seed: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "project_name": self.project_name,
            "bpm": self.bpm,
            "key": self.key,
            "time_signature": self.time_signature,
            "duration_seconds": self.duration_seconds,
            "stems": [s.to_dict() for s in self.stems],
            "midi_files": [m.to_dict() for m in self.midi_files],
            "markers": [m.to_dict() for m in self.markers],
            "lyrics": self.lyrics,
            "style_tags": self.style_tags,
            "source_model": self.source_model,
            "generation_seed": self.generation_seed,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


def make_placeholder_artwork(path: Path) -> Path:
    """Write a minimal valid JPEG to ``path`` and return it.

    Embeds a tiny baseline 1x1 JPEG so the bundle always carries a real,
    importable image without depending on an image-encoding library.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_PLACEHOLDER_JPEG)
    return path


def _existing_children(clip: Clip, generation_mode: str) -> dict[str, Clip]:
    """Return child clips of ``clip`` for a generation mode, keyed by title.

    When several children share a title (e.g. ``stems`` was rerun), the newest
    wins. ``list_clips`` returns rows newest-first, so the first one seen for a
    given title is the newest and later (older) duplicates are ignored.
    """
    if clip.id is None:
        return {}
    children: dict[str, Clip] = {}
    for child in list_clips(clip.workspace_id):
        if child.parent_clip_id == clip.id and child.generation_mode == generation_mode:
            if child.title and child.title not in children:
                children[child.title] = child
    return children


def _resolve_stems(
    clip: Clip,
    stems_client_factory: Callable[[], StemsClient],
    reuse_existing: bool,
) -> dict[str, Path]:
    """Resolve the four stem files, reusing existing child clips when possible.

    Returns a dict keyed by demucs stem label (``STEM_LABELS``) → file path.

    When stems must be generated, they are written to a persistent ``stems/``
    directory beside the source clip (matching the ``stems`` CLI command), so
    the registered child clips remain valid for reuse by later exports.
    """
    if reuse_existing:
        existing = _existing_children(clip, "stems")
        reused = {
            label: Path(existing[label].file_path)
            for label in STEM_LABELS
            if label in existing and Path(existing[label].file_path).exists()
        }
        if len(reused) == len(STEM_LABELS):
            return reused

    out_dir = Path(clip.file_path).parent / "stems"
    out_dir.mkdir(parents=True, exist_ok=True)
    client = stems_client_factory()
    stem_data = client.separate(clip.file_path)
    base_name = Path(clip.file_path).stem
    sample_rate = getattr(client, "model_samplerate", 44100)
    stem_paths = client.save_stems(stem_data, out_dir, base_name, sample_rate=sample_rate, output_format="wav")

    if clip.id is not None:
        for label, stem_path in stem_paths.items():
            create_clip(
                Clip(
                    workspace_id=clip.workspace_id,
                    file_path=str(Path(stem_path).resolve()),
                    created_at=_now(),
                    format="wav",
                    duration=get_duration(stem_path),
                    bpm=clip.bpm,
                    key=clip.key,
                    title=label,
                    parent_clip_id=clip.id,
                    generation_mode="stems",
                )
            )
    return {label: Path(p) for label, p in stem_paths.items()}


def _resolve_midi(
    clip: Clip,
    midi_client_factory: Callable[[], MidiClient],
    reuse_existing: bool,
) -> dict[str, Path]:
    """Resolve the four MIDI files, reusing existing child clips when possible.

    Returns a dict keyed by MIDI label (``MIDI_OUTPUT_LABELS``) → file path.

    When MIDI must be generated, it is written to a persistent ``midi/``
    directory beside the source clip (matching the ``midi`` CLI command), so the
    registered child clips remain valid for reuse by later exports.
    """
    if reuse_existing:
        existing = _existing_children(clip, "midi")
        reused = {
            label: Path(existing[f"midi-{label}"].file_path)
            for label in MIDI_OUTPUT_LABELS
            if f"midi-{label}" in existing and Path(existing[f"midi-{label}"].file_path).exists()
        }
        if len(reused) == len(MIDI_OUTPUT_LABELS):
            return reused

    out_dir = Path(clip.file_path).parent / "midi"
    out_dir.mkdir(parents=True, exist_ok=True)
    client = midi_client_factory()
    extracted = client.extract(clip.file_path)
    base_name = Path(clip.file_path).stem
    tempo = float(clip.bpm) if clip.bpm else 120.0
    midi_paths = client.save_midi(extracted, out_dir, base_name, bpm=tempo)

    if clip.id is not None:
        for label, midi_path in midi_paths.items():
            notes = extracted.get(label, [])
            dur = max((n[1] for n in notes), default=0.0) if notes else (clip.duration or 0.0)
            create_clip(
                Clip(
                    workspace_id=clip.workspace_id,
                    file_path=str(Path(midi_path).resolve()),
                    created_at=_now(),
                    format="mid",
                    duration=dur,
                    bpm=int(round(tempo)),
                    key=clip.key,
                    title=f"midi-{label}",
                    parent_clip_id=clip.id,
                    generation_mode="midi",
                )
            )
    return {label: Path(p) for label, p in midi_paths.items()}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def project_slug(clip: Clip) -> str:
    """Filename-safe slug for the bundle root and default output name."""
    if clip.title:
        slug = make_slug(clip.title)
        if slug:
            return slug
    return f"clip-{clip.id}"


def _copy_as_wav(src: Path | str, dest: Path) -> None:
    """Place ``src`` at ``dest`` as a real WAV.

    Reused stems/clips may be FLAC or another format; copying those bytes into a
    ``.wav`` path would mislabel them, so non-WAV sources are transcoded.
    """
    if Path(src).suffix.lower() == ".wav":
        shutil.copyfile(src, dest)
    else:
        export_audio(src, dest, "wav")


def export_stems(
    clip: Clip,
    output_dir: Path | str,
    *,
    stems_client_factory: Callable[[], StemsClient] = StemsClient,
    reuse_existing: bool = True,
) -> dict[str, Path]:
    """Export only the four stems for ``clip`` into ``output_dir`` as WAV files (US-7.4).

    Reuses existing stem child clips when present, otherwise runs separation on
    demand (the same flow as the ``stems`` command and DAW bundle). Writes
    ``vocals.wav``, ``drums.wav``, ``bass.wav`` and ``other.wav`` — no MIDI, no
    ZIP. Returns the written paths keyed by stem name.

    Raises ``ValueError`` if separation yields an incomplete set of stems, rather
    than silently exporting a partial set.
    """
    output_dir = Path(output_dir)
    stem_paths = _resolve_stems(clip, stems_client_factory, reuse_existing)

    missing = [s for s in CANONICAL_STEMS if not (stem_paths.get(s) and Path(stem_paths[s]).exists())]
    if missing:
        raise ValueError(
            "Cannot export stems — missing " + ", ".join(missing) + ". "
            "Re-run stem separation or check the source clip."
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for label in CANONICAL_STEMS:
        dest = output_dir / f"{label}.wav"
        _copy_as_wav(stem_paths[label], dest)
        written[label] = dest
    return written


def export_midi(
    clip: Clip,
    output_dir: Path | str,
    *,
    midi_client_factory: Callable[[], MidiClient] = MidiClient,
    reuse_existing: bool = True,
) -> dict[str, Path]:
    """Export only the four MIDI files for ``clip`` into ``output_dir`` (US-7.4).

    Reuses existing MIDI child clips when present, otherwise runs extraction on
    demand. Writes ``melody.mid``, ``chords.mid``, ``drums.mid`` and ``bass.mid``
    — no audio, no ZIP. Returns the written paths keyed by name.

    Raises ``ValueError`` if extraction yields an incomplete set of MIDI files.
    """
    output_dir = Path(output_dir)
    midi_paths = _resolve_midi(clip, midi_client_factory, reuse_existing)

    missing = [m for m in MIDI_OUTPUT_LABELS if not (midi_paths.get(m) and Path(midi_paths[m]).exists())]
    if missing:
        raise ValueError(
            "Cannot export MIDI — missing " + ", ".join(missing) + ". "
            "Re-run MIDI extraction or check the source clip."
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for label in MIDI_OUTPUT_LABELS:
        dest = output_dir / f"{label}.mid"
        shutil.copyfile(midi_paths[label], dest)
        written[label] = dest
    return written


def build_daw_bundle(
    clip: Clip,
    *,
    output_path: Path,
    stems_client_factory: Callable[[], StemsClient] = StemsClient,
    midi_client_factory: Callable[[], MidiClient] = MidiClient,
    reuse_existing: bool = True,
) -> Path:
    """Build a DAW-importable ZIP bundle for ``clip`` at ``output_path``.

    Resolves (reusing existing child clips, else generating) the four stems and
    four MIDI files, assembles the canonical directory tree, writes
    ``project.json`` and a placeholder ``artwork.jpg``, then packages everything
    into a ZIP rooted at ``<Slug>_Export/``.

    Raises ``ValueError`` if resolution yields an incomplete set of stems or MIDI
    files, rather than shipping a partial bundle. ``time_signature`` is always
    null because clip records do not persist meter (deferred to US-4.2); bundled
    MIDI therefore uses ``save_midi``'s default 4/4 map.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    slug = project_slug(clip)
    root_name = f"{slug}_Export"

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        tree = work / root_name
        audio_dir = tree / "audio"
        midi_dir = tree / "midi"
        audio_dir.mkdir(parents=True, exist_ok=True)
        midi_dir.mkdir(parents=True, exist_ok=True)

        stem_paths = _resolve_stems(clip, stems_client_factory, reuse_existing)
        midi_paths = _resolve_midi(clip, midi_client_factory, reuse_existing)

        missing_stems = [s for s in CANONICAL_STEMS if not (stem_paths.get(s) and Path(stem_paths[s]).exists())]
        missing_midi = [m for m in MIDI_OUTPUT_LABELS if not (midi_paths.get(m) and Path(midi_paths[m]).exists())]
        if missing_stems or missing_midi:
            parts = []
            if missing_stems:
                parts.append(f"stems ({', '.join(missing_stems)})")
            if missing_midi:
                parts.append(f"MIDI ({', '.join(missing_midi)})")
            raise ValueError(
                "Cannot build a complete DAW bundle — missing " + " and ".join(parts) + ". "
                "Re-run stem separation / MIDI extraction or check the source clip."
            )

        _copy_as_wav(clip.file_path, audio_dir / "full_mix.wav")

        stem_refs: list[StemReference] = []
        for label in CANONICAL_STEMS:
            _copy_as_wav(stem_paths[label], audio_dir / f"{label}.wav")
            stem_refs.append(StemReference(name=label, file=f"audio/{label}.wav"))

        midi_refs: list[MidiReference] = []
        for label in MIDI_OUTPUT_LABELS:
            shutil.copyfile(midi_paths[label], midi_dir / f"{label}.mid")
            midi_refs.append(MidiReference(name=label, file=f"midi/{label}.mid", channel=CHANNEL_MAP[label]))

        metadata = ProjectMetadata(
            project_name=slug,
            bpm=clip.bpm,
            key=clip.key,
            time_signature=None,
            duration_seconds=clip.duration,
            stems=stem_refs,
            midi_files=midi_refs,
            markers=[],
            lyrics=clip.lyrics,
            style_tags=clip.style_tags,
            source_model=clip.model,
            generation_seed=clip.seed,
        )
        (tree / "project.json").write_text(metadata.to_json())

        make_placeholder_artwork(tree / "artwork.jpg")

        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(tree.rglob("*")):
                if path.is_file():
                    arcname = f"{root_name}/{path.relative_to(tree).as_posix()}"
                    zf.write(path, arcname)

    return output_path
