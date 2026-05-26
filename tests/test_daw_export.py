"""Tests for the DAW bundle export feature (US-7.2).

Covers the daw_export module dataclasses, placeholder artwork generation,
the build_daw_bundle orchestration function, and the `export --format daw`
CLI path.
"""

from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import mido
import pytest
from typer.testing import CliRunner

from acemusic.cli import app
from acemusic.daw_export import (
    Marker,
    MidiReference,
    ProjectMetadata,
    StemReference,
    _existing_children,
    build_daw_bundle,
    make_placeholder_artwork,
)
from acemusic.midi_client import CHANNEL_MAP, MIDI_OUTPUT_LABELS
from acemusic.models import Clip
from acemusic.stems_client import STEM_LABELS

runner = CliRunner()


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    import acemusic.db as _db

    monkeypatch.setattr(_db, "DB_DIR", tmp_path / ".acemusic")
    return tmp_path


@pytest.fixture
def workspace(isolated_db):
    from acemusic.workspace import ensure_default_workspace, get_active_workspace, get_workspace_path

    ensure_default_workspace()
    ws = get_active_workspace()
    clips_dir = get_workspace_path(ws.id)
    clips_dir.mkdir(parents=True, exist_ok=True)
    return ws


@pytest.fixture
def full_mix_clip(workspace, write_tone):
    """Create a full-mix clip on disk with rich metadata."""
    from acemusic.db import create_clip
    from acemusic.workspace import get_workspace_path

    clips_dir = get_workspace_path(workspace.id)
    src = clips_dir / "fullmix.wav"
    write_tone(src, duration_s=1.0)

    clip = Clip(
        workspace_id=workspace.id,
        file_path=str(src),
        created_at=datetime.now(timezone.utc).isoformat(),
        title="My Cool Track",
        format="wav",
        duration=1.0,
        bpm=128,
        key="C major",
        style_tags="lofi, chill",
        lyrics="la la la",
        model="ace-step-v1",
        seed=4242,
    )
    clip_id = create_clip(clip)
    return workspace, clip_id, src


# Stem-label aliasing: build_daw_bundle maps the demucs labels onto the canonical
# bundle slots, so the writer just needs to emit one wav per STEM_LABEL.
_STEM_FRAMES = 44100  # equal-length stems


def _write_real_wav(path: Path, frames: int = _STEM_FRAMES, sample_rate: int = 44100) -> None:
    import numpy as np
    import soundfile as sf

    data = np.zeros((frames, 2), dtype=np.float32)
    sf.write(str(path), data, sample_rate)


def _make_stems_client_factory():
    """Return a factory producing a mock StemsClient that writes real WAV stems."""
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
            _write_real_wav(p)
            paths[label] = p
        return paths

    instance.save_stems.side_effect = _save
    factory = MagicMock(return_value=instance)
    factory.instance = instance
    return factory


def _make_midi_client_factory():
    """Return a factory producing a mock MidiClient that writes real Type-1 MIDI."""
    from acemusic.midi_client import MidiClient

    instance = MagicMock()
    midi_data = {
        "melody": [(0.0, 0.5, 72, 100), (0.5, 1.0, 74, 90)],
        "chords": [(0.0, 1.0, 60, 80)],
        "drums": [(0.0, 0.1, 36, 127), (0.5, 0.6, 38, 100)],
        "bass": [(0.0, 1.0, 40, 100)],
    }
    instance.extract.return_value = midi_data
    # Use the real save_midi so the output is genuine Type-1 with channels.
    real = MidiClient()
    instance.save_midi.side_effect = lambda data, out_dir, base, **kw: real.save_midi(data, out_dir, base, **kw)
    factory = MagicMock(return_value=instance)
    factory.instance = instance
    return factory


class TestDataclasses:
    def test_marker_to_dict(self):
        m = Marker(name="verse", time=12.5)
        assert m.to_dict() == {"name": "verse", "time": 12.5}

    def test_stem_reference_to_dict(self):
        s = StemReference(name="vocals", file="audio/vocals.wav")
        assert s.to_dict() == {"name": "vocals", "file": "audio/vocals.wav"}

    def test_midi_reference_to_dict(self):
        r = MidiReference(name="melody", file="midi/melody.mid", channel=0)
        assert r.to_dict() == {"name": "melody", "file": "midi/melody.mid", "channel": 0}

    def test_project_metadata_to_dict_and_json(self):
        meta = ProjectMetadata(
            project_name="my-track",
            bpm=120,
            key="C major",
            time_signature="4/4",
            duration_seconds=42.0,
            stems=[StemReference("vocals", "audio/vocals.wav")],
            midi_files=[MidiReference("melody", "midi/melody.mid", 0)],
            markers=[Marker("intro", 0.0)],
            lyrics="hello",
            style_tags="rock",
            source_model="ace-step",
            generation_seed=7,
        )
        d = meta.to_dict()
        assert d["project_name"] == "my-track"
        assert d["stems"] == [{"name": "vocals", "file": "audio/vocals.wav"}]
        assert d["midi_files"] == [{"name": "melody", "file": "midi/melody.mid", "channel": 0}]
        assert d["markers"] == [{"name": "intro", "time": 0.0}]

        text = meta.to_json()
        parsed = json.loads(text)
        assert parsed == d
        assert "\n" in text  # indent=2 → multiline

    def test_project_metadata_unavailable_fields_serialize_to_null(self):
        meta = ProjectMetadata(
            project_name="x",
            bpm=None,
            key=None,
            time_signature=None,
            duration_seconds=None,
            stems=[],
            midi_files=[],
            markers=[],
            lyrics=None,
            style_tags=None,
            source_model=None,
            generation_seed=None,
        )
        parsed = json.loads(meta.to_json())
        assert parsed["bpm"] is None
        assert parsed["key"] is None
        assert parsed["lyrics"] is None
        assert parsed["generation_seed"] is None


class TestPlaceholderArtwork:
    def test_writes_valid_jpeg(self, tmp_path):
        out = tmp_path / "artwork.jpg"
        result = make_placeholder_artwork(out)
        assert result == out
        assert out.exists()
        data = out.read_bytes()
        assert data[:2] == b"\xff\xd8"  # JPEG SOI magic
        assert data[-2:] == b"\xff\xd9"  # JPEG EOI marker


EXPECTED_FILES = {
    "audio/full_mix.wav",
    "audio/vocals.wav",
    "audio/drums.wav",
    "audio/bass.wav",
    "audio/other.wav",
    "midi/melody.mid",
    "midi/chords.mid",
    "midi/drums.mid",
    "midi/bass.mid",
    "project.json",
    "artwork.jpg",
}


def _build(full_mix_clip, tmp_path, **kw):
    from acemusic.db import get_clip

    ws, clip_id, _ = full_mix_clip
    clip = get_clip(clip_id)
    dest = tmp_path / "bundle.zip"
    stems_factory = kw.pop("stems_client_factory", None) or _make_stems_client_factory()
    midi_factory = kw.pop("midi_client_factory", None) or _make_midi_client_factory()
    out = build_daw_bundle(
        clip,
        output_path=dest,
        stems_client_factory=stems_factory,
        midi_client_factory=midi_factory,
        **kw,
    )
    return out, stems_factory, midi_factory


class TestBuildDawBundle:
    def test_zip_contains_expected_structure(self, full_mix_clip, tmp_path):
        out, _, _ = _build(full_mix_clip, tmp_path)
        assert out.exists()
        with zipfile.ZipFile(out) as zf:
            names = zf.namelist()
        roots = {n.split("/", 1)[0] for n in names}
        assert len(roots) == 1
        root = roots.pop()
        assert root.endswith("_Export")
        rel = {n[len(root) + 1 :] for n in names if not n.endswith("/")}
        assert EXPECTED_FILES.issubset(rel)

    def test_project_json_valid_and_populated(self, full_mix_clip, tmp_path):
        out, _, _ = _build(full_mix_clip, tmp_path)
        with zipfile.ZipFile(out) as zf:
            root = zf.namelist()[0].split("/", 1)[0]
            data = json.loads(zf.read(f"{root}/project.json"))

        assert data["project_name"] == "my-cool-track"
        assert data["bpm"] == 128
        assert data["key"] == "C major"
        assert data["duration_seconds"] == pytest.approx(1.0)
        assert data["lyrics"] == "la la la"
        assert data["style_tags"] == "lofi, chill"
        assert data["source_model"] == "ace-step-v1"
        assert data["generation_seed"] == 4242
        # time_signature not on Clip records → serialized as null
        assert data["time_signature"] is None
        # stems / midi references present
        stem_names = {s["name"] for s in data["stems"]}
        assert stem_names == {"vocals", "drums", "bass", "other"}
        midi_names = {m["name"] for m in data["midi_files"]}
        assert midi_names == set(MIDI_OUTPUT_LABELS)

    def test_midi_files_are_type1_with_correct_channels(self, full_mix_clip, tmp_path):
        out, _, _ = _build(full_mix_clip, tmp_path)
        with zipfile.ZipFile(out) as zf:
            root = zf.namelist()[0].split("/", 1)[0]
            for label in MIDI_OUTPUT_LABELS:
                raw = zf.read(f"{root}/midi/{label}.mid")
                tmp_mid = tmp_path / f"_{label}.mid"
                tmp_mid.write_bytes(raw)
                mid = mido.MidiFile(str(tmp_mid))
                assert mid.type == 1, f"{label} should be Type 1"
                channels = {msg.channel for track in mid.tracks for msg in track if msg.type == "note_on"}
                assert channels == {CHANNEL_MAP[label]}, f"{label} channel mismatch"

    def test_stems_equal_length_and_full_mix_present(self, full_mix_clip, tmp_path):
        import soundfile as sf

        out, _, _ = _build(full_mix_clip, tmp_path)
        extract_dir = tmp_path / "extract"
        with zipfile.ZipFile(out) as zf:
            zf.extractall(extract_dir)
            root = zf.namelist()[0].split("/", 1)[0]

        audio_dir = extract_dir / root / "audio"
        assert (audio_dir / "full_mix.wav").exists()
        frame_counts = set()
        for label in ("vocals", "drums", "bass", "other"):
            info = sf.info(str(audio_dir / f"{label}.wav"))
            frame_counts.add(info.frames)
        assert len(frame_counts) == 1, f"stems differ in length: {frame_counts}"

    def test_reuse_existing_children_skips_clients(self, full_mix_clip, tmp_path):
        """When stem and midi child clips already exist on disk, clients are NOT invoked."""
        from acemusic.db import create_clip, get_clip
        from acemusic.midi_client import MidiClient
        from acemusic.workspace import get_workspace_path

        ws, clip_id, _ = full_mix_clip
        clips_dir = get_workspace_path(ws.id)

        # Pre-create stem child clips with real wav files.
        for label in STEM_LABELS:
            p = clips_dir / f"stem-{label}.wav"
            _write_real_wav(p)
            create_clip(
                Clip(
                    workspace_id=ws.id,
                    file_path=str(p),
                    created_at=datetime.now(timezone.utc).isoformat(),
                    title=label,
                    format="wav",
                    parent_clip_id=clip_id,
                    generation_mode="stems",
                )
            )

        # Pre-create midi child clips with real Type-1 files.
        real = MidiClient()
        midi_paths = real.save_midi(
            {
                "melody": [(0.0, 0.5, 72, 100)],
                "chords": [(0.0, 1.0, 60, 80)],
                "drums": [(0.0, 0.1, 36, 127)],
                "bass": [(0.0, 1.0, 40, 100)],
            },
            clips_dir,
            "seed",
        )
        for label, p in midi_paths.items():
            create_clip(
                Clip(
                    workspace_id=ws.id,
                    file_path=str(p),
                    created_at=datetime.now(timezone.utc).isoformat(),
                    title=f"midi-{label}",
                    format="mid",
                    parent_clip_id=clip_id,
                    generation_mode="midi",
                )
            )

        stems_factory = _make_stems_client_factory()
        midi_factory = _make_midi_client_factory()
        clip = get_clip(clip_id)
        out = build_daw_bundle(
            clip,
            output_path=tmp_path / "reuse.zip",
            stems_client_factory=stems_factory,
            midi_client_factory=midi_factory,
        )
        assert out.exists()
        stems_factory.instance.separate.assert_not_called()
        midi_factory.instance.extract.assert_not_called()
        with zipfile.ZipFile(out) as zf:
            root = zf.namelist()[0].split("/", 1)[0]
            rel = {n[len(root) + 1 :] for n in zf.namelist() if not n.endswith("/")}
        assert EXPECTED_FILES.issubset(rel)

    def test_clients_invoked_when_no_children(self, full_mix_clip, tmp_path):
        stems_factory = _make_stems_client_factory()
        midi_factory = _make_midi_client_factory()
        _build(
            full_mix_clip,
            tmp_path,
            stems_client_factory=stems_factory,
            midi_client_factory=midi_factory,
        )
        stems_factory.instance.separate.assert_called_once()
        midi_factory.instance.extract.assert_called_once()

    def test_generated_children_persist_and_second_export_reuses(self, full_mix_clip, tmp_path):
        """Generated stems/MIDI must persist on disk so a later export reuses them.

        Regression: generating into an ephemeral temp dir left dangling child-clip
        records and forced regeneration on every export.
        """
        from acemusic.db import get_clip, list_clips

        ws, clip_id, _ = full_mix_clip
        clip = get_clip(clip_id)

        # First export generates stems + MIDI.
        first_stems = _make_stems_client_factory()
        first_midi = _make_midi_client_factory()
        build_daw_bundle(
            clip,
            output_path=tmp_path / "first.zip",
            stems_client_factory=first_stems,
            midi_client_factory=first_midi,
        )
        first_stems.instance.separate.assert_called_once()
        first_midi.instance.extract.assert_called_once()

        # Registered child clips must point at files that still exist on disk.
        children = [c for c in list_clips(ws.id) if c.parent_clip_id == clip_id]
        stem_children = [c for c in children if c.generation_mode == "stems"]
        midi_children = [c for c in children if c.generation_mode == "midi"]
        assert len(stem_children) == len(STEM_LABELS)
        assert len(midi_children) == len(MIDI_OUTPUT_LABELS)
        for child in stem_children + midi_children:
            assert Path(child.file_path).exists(), f"dangling child clip: {child.file_path}"

        # Second export with fresh mocks must reuse, not regenerate.
        second_stems = _make_stems_client_factory()
        second_midi = _make_midi_client_factory()
        out = build_daw_bundle(
            clip,
            output_path=tmp_path / "second.zip",
            stems_client_factory=second_stems,
            midi_client_factory=second_midi,
        )
        second_stems.instance.separate.assert_not_called()
        second_midi.instance.extract.assert_not_called()
        with zipfile.ZipFile(out) as zf:
            root = zf.namelist()[0].split("/", 1)[0]
            rel = {n[len(root) + 1 :] for n in zf.namelist() if not n.endswith("/")}
        assert EXPECTED_FILES.issubset(rel)

    def test_existing_children_prefers_newest_duplicate(self, full_mix_clip):
        """When duplicate-title children exist, _existing_children keeps the newest."""
        from acemusic.db import create_clip, get_clip
        from acemusic.workspace import get_workspace_path

        ws, clip_id, _ = full_mix_clip
        clips_dir = get_workspace_path(ws.id)
        clip = get_clip(clip_id)

        old = clips_dir / "old-vocals.wav"
        new = clips_dir / "new-vocals.wav"
        _write_real_wav(old)
        _write_real_wav(new)
        # Older record first, newer record second (created_at controls ordering).
        create_clip(
            Clip(
                workspace_id=ws.id,
                file_path=str(old),
                created_at="2020-01-01T00:00:00+00:00",
                title="vocals",
                generation_mode="stems",
                parent_clip_id=clip_id,
            )
        )
        create_clip(
            Clip(
                workspace_id=ws.id,
                file_path=str(new),
                created_at="2026-01-01T00:00:00+00:00",
                title="vocals",
                generation_mode="stems",
                parent_clip_id=clip_id,
            )
        )

        children = _existing_children(clip, "stems")
        assert Path(children["vocals"].file_path) == new

    def test_incomplete_midi_raises_instead_of_partial_bundle(self, full_mix_clip, tmp_path):
        """If MIDI extraction omits a part, the export fails rather than shipping a partial bundle."""
        from acemusic.db import get_clip
        from acemusic.midi_client import MidiClient

        ws, clip_id, _ = full_mix_clip
        clip = get_clip(clip_id)

        # MIDI factory that emits no bass notes → save_midi writes only 3 files.
        instance = MagicMock()
        instance.extract.return_value = {
            "melody": [(0.0, 0.5, 72, 100)],
            "chords": [(0.0, 1.0, 60, 80)],
            "drums": [(0.0, 0.1, 36, 127)],
            "bass": [],
        }
        real = MidiClient()
        instance.save_midi.side_effect = lambda data, out_dir, base, **kw: real.save_midi(data, out_dir, base, **kw)
        midi_factory = MagicMock(return_value=instance)

        with pytest.raises(ValueError, match="bass"):
            build_daw_bundle(
                clip,
                output_path=tmp_path / "partial.zip",
                stems_client_factory=_make_stems_client_factory(),
                midi_client_factory=midi_factory,
            )

    def test_incomplete_stems_raises_instead_of_partial_bundle(self, full_mix_clip, tmp_path):
        """A stems factory returning only 3 of 4 stems must fail the export."""
        from acemusic.db import get_clip

        ws, clip_id, _ = full_mix_clip
        clip = get_clip(clip_id)

        instance = MagicMock()
        instance.model_samplerate = 44100
        instance.separate.return_value = {label: MagicMock() for label in STEM_LABELS}

        def _save_three(stems, out_dir, base, **kw):
            out_dir = Path(out_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            paths = {}
            for label in ("drums", "bass", "other"):  # 'vocals' omitted
                p = out_dir / f"{base}-{label}.wav"
                _write_real_wav(p)
                paths[label] = p
            return paths

        instance.save_stems.side_effect = _save_three
        stems_factory = MagicMock(return_value=instance)

        with pytest.raises(ValueError, match="vocals"):
            build_daw_bundle(
                clip,
                output_path=tmp_path / "partial.zip",
                stems_client_factory=stems_factory,
                midi_client_factory=_make_midi_client_factory(),
            )

    def test_non_wav_source_is_transcoded_for_full_mix(self, workspace, tmp_path):
        """A non-WAV source clip is transcoded (not byte-copied) into full_mix.wav."""
        import wave

        import numpy as np
        import soundfile as sf

        from acemusic.audio import export_audio
        from acemusic.db import create_clip, get_clip
        from acemusic.workspace import get_workspace_path

        clips_dir = get_workspace_path(workspace.id)
        wav_seed = clips_dir / "tone-src.wav"
        sr = 44100
        sf.write(str(wav_seed), np.zeros((sr, 2), dtype=np.float32), sr)
        flac_src = clips_dir / "song.flac"
        export_audio(wav_seed, flac_src, "flac")

        clip_id = create_clip(
            Clip(
                workspace_id=workspace.id,
                file_path=str(flac_src),
                created_at=datetime.now(timezone.utc).isoformat(),
                title="Flac Song",
                format="flac",
                duration=1.0,
            )
        )
        clip = get_clip(clip_id)
        out = build_daw_bundle(
            clip,
            output_path=tmp_path / "flac.zip",
            stems_client_factory=_make_stems_client_factory(),
            midi_client_factory=_make_midi_client_factory(),
        )
        with zipfile.ZipFile(out) as zf:
            root = zf.namelist()[0].split("/", 1)[0]
            raw = zf.read(f"{root}/audio/full_mix.wav")
        fm = tmp_path / "fm.wav"
        fm.write_bytes(raw)
        # A real WAV is readable by the stdlib wave module; a renamed FLAC is not.
        with wave.open(str(fm)) as w:
            assert w.getnframes() > 0

    def test_reuse_existing_false_forces_regeneration(self, full_mix_clip, tmp_path):
        """reuse_existing=False ignores existing child clips and re-invokes the clients."""
        from acemusic.db import create_clip, get_clip
        from acemusic.midi_client import MidiClient
        from acemusic.workspace import get_workspace_path

        ws, clip_id, _ = full_mix_clip
        clips_dir = get_workspace_path(ws.id)

        for label in STEM_LABELS:
            p = clips_dir / f"stem-{label}.wav"
            _write_real_wav(p)
            create_clip(
                Clip(
                    workspace_id=ws.id,
                    file_path=str(p),
                    created_at=datetime.now(timezone.utc).isoformat(),
                    title=label,
                    format="wav",
                    parent_clip_id=clip_id,
                    generation_mode="stems",
                )
            )
        real = MidiClient()
        for label, p in real.save_midi(
            {lbl: [(0.0, 1.0, 60, 80)] for lbl in MIDI_OUTPUT_LABELS}, clips_dir, "seed"
        ).items():
            create_clip(
                Clip(
                    workspace_id=ws.id,
                    file_path=str(p),
                    created_at=datetime.now(timezone.utc).isoformat(),
                    title=f"midi-{label}",
                    format="mid",
                    parent_clip_id=clip_id,
                    generation_mode="midi",
                )
            )

        stems_factory = _make_stems_client_factory()
        midi_factory = _make_midi_client_factory()
        build_daw_bundle(
            get_clip(clip_id),
            output_path=tmp_path / "regen.zip",
            stems_client_factory=stems_factory,
            midi_client_factory=midi_factory,
            reuse_existing=False,
        )
        stems_factory.instance.separate.assert_called_once()
        midi_factory.instance.extract.assert_called_once()


class TestExportDawCli:
    def test_export_format_daw_produces_zip(self, full_mix_clip, tmp_path, monkeypatch):
        _, clip_id, _ = full_mix_clip
        monkeypatch.chdir(tmp_path)

        with patch("acemusic.cli.StemsClient", _make_stems_client_factory()):
            with patch("acemusic.cli.MidiClient", _make_midi_client_factory()):
                result = runner.invoke(app, ["export", str(clip_id), "--format", "daw"])

        assert result.exit_code == 0, result.output
        zips = list(tmp_path.glob("*.zip"))
        assert len(zips) == 1
        assert zips[0].name == "my-cool-track_Export.zip"

    def test_export_daw_custom_output(self, full_mix_clip, tmp_path):
        _, clip_id, _ = full_mix_clip
        dest = tmp_path / "nested" / "out.zip"

        with patch("acemusic.cli.StemsClient", _make_stems_client_factory()):
            with patch("acemusic.cli.MidiClient", _make_midi_client_factory()):
                result = runner.invoke(app, ["export", str(clip_id), "--format", "daw", "--output", str(dest)])

        assert result.exit_code == 0, result.output
        assert dest.exists()
        assert zipfile.is_zipfile(dest)

    def test_export_daw_invalid_clip_errors(self, isolated_db):
        result = runner.invoke(app, ["export", "99999", "--format", "daw"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_export_invalid_format_errors(self, full_mix_clip):
        _, clip_id, _ = full_mix_clip
        result = runner.invoke(app, ["export", str(clip_id), "--format", "ogg"])
        assert result.exit_code == 1
        assert "format" in result.output.lower()
