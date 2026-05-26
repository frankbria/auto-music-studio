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
from pathlib import Path
from typing import Callable, Optional

from acemusic.db import create_clip, list_clips
from acemusic.midi_client import CHANNEL_MAP, MIDI_OUTPUT_LABELS, MidiClient
from acemusic.models import Clip
from acemusic.stems_client import STEM_LABELS, StemsClient
from acemusic.utils import get_duration, make_slug

# Canonical stem slots in the bundle (file basenames under audio/).
CANONICAL_STEMS: tuple[str, ...] = ("vocals", "drums", "bass", "other")

# Minimal valid baseline 1x1 black JPEG. Used so the bundle always ships a
# real, importable artwork file without adding an image-encoding dependency.
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


# ---------------------------------------------------------------------------
# Metadata dataclasses
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Artwork
# ---------------------------------------------------------------------------


def make_placeholder_artwork(path: Path) -> Path:
    """Write a minimal valid JPEG to ``path`` and return it.

    Embeds a tiny baseline 1x1 JPEG so the bundle always carries a real,
    importable image without depending on an image-encoding library.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_PLACEHOLDER_JPEG)
    return path


# ---------------------------------------------------------------------------
# Stem / MIDI resolution
# ---------------------------------------------------------------------------


def _existing_children(clip: Clip, generation_mode: str) -> dict[str, Clip]:
    """Return child clips of ``clip`` for a generation mode, keyed by title."""
    if clip.id is None:
        return {}
    children = {}
    for child in list_clips(clip.workspace_id):
        if child.parent_clip_id == clip.id and child.generation_mode == generation_mode:
            if child.title:
                children[child.title] = child
    return children


def _resolve_stems(
    clip: Clip,
    work_dir: Path,
    stems_client_factory: Callable[[], StemsClient],
    reuse_existing: bool,
) -> dict[str, Path]:
    """Resolve the four stem files, reusing existing child clips when possible.

    Returns a dict keyed by demucs stem label (``STEM_LABELS``) → file path.
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

    client = stems_client_factory()
    stem_data = client.separate(clip.file_path)
    base_name = Path(clip.file_path).stem
    sample_rate = getattr(client, "model_samplerate", 44100)
    stem_paths = client.save_stems(stem_data, work_dir, base_name, sample_rate=sample_rate, output_format="wav")

    # Register each stem as a child clip so future exports can reuse them.
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
    work_dir: Path,
    midi_client_factory: Callable[[], MidiClient],
    reuse_existing: bool,
) -> dict[str, Path]:
    """Resolve the four MIDI files, reusing existing child clips when possible.

    Returns a dict keyed by MIDI label (``MIDI_OUTPUT_LABELS``) → file path.
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

    client = midi_client_factory()
    extracted = client.extract(clip.file_path)
    base_name = Path(clip.file_path).stem
    tempo = float(clip.bpm) if clip.bpm else 120.0
    midi_paths = client.save_midi(extracted, work_dir, base_name, bpm=tempo)

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
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _project_slug(clip: Clip) -> str:
    if clip.title:
        slug = make_slug(clip.title)
        if slug:
            return slug
    return f"clip-{clip.id}"


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
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    slug = _project_slug(clip)
    root_name = f"{slug}_Export"

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        tree = work / root_name
        audio_dir = tree / "audio"
        midi_dir = tree / "midi"
        audio_dir.mkdir(parents=True, exist_ok=True)
        midi_dir.mkdir(parents=True, exist_ok=True)

        # Resolve stems and MIDI into a scratch dir, then copy to canonical names.
        scratch = work / "_scratch"
        scratch.mkdir(parents=True, exist_ok=True)

        stem_paths = _resolve_stems(clip, scratch, stems_client_factory, reuse_existing)
        midi_paths = _resolve_midi(clip, scratch, midi_client_factory, reuse_existing)

        # Full mix
        shutil.copyfile(clip.file_path, audio_dir / "full_mix.wav")

        # Stems → canonical names (vocals/drums/bass/other).
        stem_refs: list[StemReference] = []
        for label in CANONICAL_STEMS:
            src = stem_paths.get(label)
            if src is None or not Path(src).exists():
                continue
            dest = audio_dir / f"{label}.wav"
            shutil.copyfile(src, dest)
            stem_refs.append(StemReference(name=label, file=f"audio/{label}.wav"))

        # MIDI → canonical names with channel assignments.
        midi_refs: list[MidiReference] = []
        for label in MIDI_OUTPUT_LABELS:
            src = midi_paths.get(label)
            if src is None or not Path(src).exists():
                continue
            dest = midi_dir / f"{label}.mid"
            shutil.copyfile(src, dest)
            midi_refs.append(MidiReference(name=label, file=f"midi/{label}.mid", channel=CHANNEL_MAP[label]))

        metadata = ProjectMetadata(
            project_name=slug,
            bpm=clip.bpm,
            key=clip.key,
            time_signature=getattr(clip, "time_signature", None),
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

        # Package the tree into a ZIP rooted at <Slug>_Export/.
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(tree.rglob("*")):
                if path.is_file():
                    arcname = f"{root_name}/{path.relative_to(tree).as_posix()}"
                    zf.write(path, arcname)

    return output_path
