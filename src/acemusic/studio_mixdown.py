"""Studio arrangement mixdown and DAW bundle assembly (US-19.6).

The Studio (US-19.1–19.5) has no backend arrangement persistence, so an export
request carries the whole arrangement — tracks, each with placements (a clip on
the timeline at a start offset, optionally trimmed) plus per-track volume, pan,
mute and solo. This module turns that arrangement into audio two ways:

* :func:`mixdown_arrangement` renders a single mixed stereo file — the timeline
  with every audible placement overlaid, per-track gain and pan baked in, muted
  tracks dropped, and (when any track is soloed) only the soloed tracks sounding.
* :func:`render_track_timeline` bounces one track to a silence-padded stem that
  starts at 0, *without* baking in gain or pan, so a DAW can re-apply them from
  ``project.json``. :func:`assemble_studio_bundle` packs those stems plus the
  metadata into a ``<Slug>_Export/`` ZIP.

The pydub overlay idiom mirrors :func:`acemusic.audio.combine_sample`: segments
are normalised to a 48 kHz stereo timeline and positioned by millisecond offset.
WAV in / WAV out uses the stdlib ``wave`` module (no ffmpeg), so the mix and stem
renders are CI-safe; :func:`export_mix` converts the mix to its delivery format
(24-bit WAV and FLAC via libsndfile — still no ffmpeg — MP3 via
:func:`acemusic.audio.export_audio`).
"""

from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Optional

from acemusic.daw_export import Marker
from acemusic.utils import make_slug

MIX_SAMPLE_RATE = 48000
MIX_CHANNELS = 2


@dataclass
class PlacementMix:
    """A clip placed on the timeline: local WAV, start offset, optional trim."""

    audio_path: Path | str
    start_sec: float
    duration_sec: Optional[float] = None


@dataclass
class TrackMix:
    """A track's placements plus its mix controls (US-19.4)."""

    placements: list[PlacementMix] = field(default_factory=list)
    volume_db: float = 0.0
    pan: float = 0.0
    muted: bool = False
    solo: bool = False


@dataclass
class StudioTrackFile:
    """A rendered stem file destined for the DAW bundle, with its mix metadata."""

    name: str
    audio_path: Path | str
    volume_db: float
    pan: float


def _load_segment(path: Path | str):
    """Load an audio file as a 48 kHz stereo pydub segment (no ffmpeg for WAV)."""
    from pydub import AudioSegment

    suffix = Path(path).suffix.lower().lstrip(".") or "wav"
    seg = AudioSegment.from_file(str(path), format=suffix)
    return seg.set_frame_rate(MIX_SAMPLE_RATE).set_channels(MIX_CHANNELS)


def _placement_segment(placement: PlacementMix):
    """The (optionally trimmed) segment for a placement, at the mix rate."""
    seg = _load_segment(placement.audio_path)
    if placement.duration_sec is not None:
        seg = seg[: max(0, int(placement.duration_sec * 1000))]
    return seg


def _silent(duration_ms: int):
    from pydub import AudioSegment

    return AudioSegment.silent(duration=max(0, duration_ms), frame_rate=MIX_SAMPLE_RATE).set_channels(MIX_CHANNELS)


def arrangement_duration(tracks: list[TrackMix]) -> float:
    """The arrangement length in seconds: the latest placement end across all tracks.

    Every placement (muted or soloed alike) counts, so the exported mix and the
    per-track stems share one length and stay sample-aligned.
    """
    end_ms = 0
    for track in tracks:
        for placement in track.placements:
            seg = _placement_segment(placement)
            end_ms = max(end_ms, int(placement.start_sec * 1000) + len(seg))
    return end_ms / 1000.0


def _audible_tracks(tracks: list[TrackMix]) -> list[TrackMix]:
    """Tracks that should sound: muted dropped, and if any is soloed only solos."""
    has_solo = any(t.solo for t in tracks)
    return [t for t in tracks if not t.muted and (t.solo or not has_solo)]


def _overlay_placements(base, placements: list[PlacementMix]):
    """Overlay each placement onto ``base`` at its start offset; return the result."""
    combined = base
    for placement in placements:
        seg = _placement_segment(placement)
        if len(seg) == 0:
            continue
        combined = combined.overlay(seg, position=max(0, int(placement.start_sec * 1000)))
    return combined


def _timeline_ms(total_duration_sec: Optional[float], fallback_tracks: list[TrackMix]) -> int:
    if total_duration_sec is None:
        total_duration_sec = arrangement_duration(fallback_tracks)
    return int(round(total_duration_sec * 1000))


def mixdown_arrangement(
    tracks: list[TrackMix],
    *,
    output_path: Path | str,
    total_duration_sec: Optional[float] = None,
    sample_rate: int = MIX_SAMPLE_RATE,
) -> Path:
    """Render ``tracks`` to a single mixed stereo WAV at ``output_path``.

    Builds a silent 48 kHz stereo timeline the length of the arrangement, then for
    each audible track (muted dropped; when any track is soloed only soloed tracks
    sound) overlays its placements, applies the track's gain (dB) and pan, and
    overlays the track onto the master. WAV out uses the stdlib ``wave`` writer.
    """
    output_path = Path(output_path)
    timeline_ms = _timeline_ms(total_duration_sec, tracks)
    master = _silent(timeline_ms)

    for track in _audible_tracks(tracks):
        rendered = _overlay_placements(_silent(timeline_ms), track.placements)
        if track.volume_db:
            rendered = rendered + track.volume_db
        if track.pan:
            rendered = rendered.pan(max(-1.0, min(1.0, track.pan)))
        master = master.overlay(rendered)

    master = master.set_frame_rate(sample_rate).set_channels(MIX_CHANNELS)
    master.export(str(output_path), format="wav")
    return output_path


def render_track_timeline(
    placements: list[PlacementMix],
    *,
    output_path: Path | str,
    total_duration_sec: float,
    sample_rate: int = MIX_SAMPLE_RATE,
) -> Path:
    """Bounce a single track's placements to a silence-padded stem WAV.

    The stem starts at 0 and runs the full arrangement length, so every stem in a
    DAW bundle lines up. Gain and pan are *not* baked in — they ride in
    ``project.json`` for the DAW to re-apply.
    """
    output_path = Path(output_path)
    timeline_ms = int(round(total_duration_sec * 1000))
    stem = _overlay_placements(_silent(timeline_ms), placements)
    stem = stem.set_frame_rate(sample_rate).set_channels(MIX_CHANNELS)
    stem.export(str(output_path), format="wav")
    return output_path


def export_mix(raw_wav: Path | str, dest_path: Path | str, fmt: str) -> Path:
    """Convert the rendered mix WAV to its delivery format.

    ``wav`` (48 kHz / 24-bit PCM) and ``flac`` go through libsndfile so the two
    primary formats work on hosts without ffmpeg (CI included); only ``mp3`` needs
    :func:`acemusic.audio.export_audio`'s ffmpeg pipeline.
    """
    import soundfile as sf

    dest_path = Path(dest_path)
    if fmt == "wav":
        data, sr = sf.read(str(raw_wav), always_2d=True)
        sf.write(str(dest_path), data, sr, subtype="PCM_24")
    elif fmt == "flac":
        data, sr = sf.read(str(raw_wav), always_2d=True)
        sf.write(str(dest_path), data, sr, format="FLAC")
    else:
        from acemusic.audio import export_audio

        export_audio(raw_wav, dest_path, fmt)
    return dest_path


def _project_slug(project_name: str) -> str:
    """Filename-safe slug for the bundle root (falls back when the name is empty)."""
    return make_slug(project_name) or "studio-export"


def _unique_track_filenames(tracks: list[StudioTrackFile]) -> list[str]:
    """A ``<slug>.wav`` per track, de-duplicated so shared display names don't clash."""
    used: set[str] = set()
    filenames: list[str] = []
    for index, track in enumerate(tracks):
        base = make_slug(track.name) or f"track-{index + 1}"
        candidate = base
        suffix = 2
        while candidate in used:
            candidate = f"{base}-{suffix}"
            suffix += 1
        used.add(candidate)
        filenames.append(f"{candidate}.wav")
    return filenames


def assemble_studio_bundle(
    *,
    project_name: str,
    bpm: Optional[float],
    duration_seconds: Optional[float],
    tracks: list[StudioTrackFile],
    markers: list[dict],
    output_path: Path | str,
) -> Path:
    """Assemble a DAW bundle ZIP from already-rendered per-track WAV stems.

    Lays out ``<Slug>_Export/audio/<track>.wav`` for each stem plus a
    ``project.json`` carrying ``project_name``, ``bpm``, ``duration_seconds``, the
    per-track ``{name, file, volume_db, pan}`` and the ``{name, time}`` markers.
    Track stems are assumed to be WAV already (copied verbatim, not transcoded).
    ``markers`` entries use ``time_sec`` (the request shape); they are written as
    ``time`` via :class:`~acemusic.daw_export.Marker`.
    """
    import shutil

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    slug = _project_slug(project_name)
    root_name = f"{slug}_Export"
    filenames = _unique_track_filenames(tracks)

    with TemporaryDirectory(prefix="acemusic-studio-") as tmp:
        work = Path(tmp)
        tree = work / root_name
        audio_dir = tree / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)

        track_meta: list[dict] = []
        for track, filename in zip(tracks, filenames):
            shutil.copyfile(track.audio_path, audio_dir / filename)
            track_meta.append(
                {
                    "name": track.name,
                    "file": f"audio/{filename}",
                    "volume_db": track.volume_db,
                    "pan": track.pan,
                }
            )

        marker_objs = [Marker(name=m["name"], time=m.get("time_sec", m.get("time"))) for m in markers]
        metadata = {
            "project_name": project_name,
            "bpm": bpm,
            "duration_seconds": duration_seconds,
            "tracks": track_meta,
            "markers": [m.to_dict() for m in marker_objs],
        }
        (tree / "project.json").write_text(json.dumps(metadata, indent=2))

        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(tree.rglob("*")):
                if path.is_file():
                    arcname = f"{root_name}/{path.relative_to(tree).as_posix()}"
                    zf.write(path, arcname)

    return output_path
