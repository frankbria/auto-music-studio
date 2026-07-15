"""Tests for the studio mixdown engine and DAW bundle assembly (US-19.6, issue #212).

These are pure and CI-safe: the mixdown/stem-render helpers take WAV in and write
WAV out (pydub uses the stdlib ``wave`` module for WAV, so no ffmpeg is needed),
and ``assemble_studio_bundle`` only copies already-WAV stems and writes JSON.
``export_mix``'s WAV/FLAC delivery goes through libsndfile so it's CI-safe too;
only its MP3 branch needs ffmpeg. The job handlers that drive all of this are
exercised in ``tests/test_studio_tasks.py`` under the ``integration`` marker.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from acemusic.studio_mixdown import (
    PlacementMix,
    StudioTrackFile,
    TrackMix,
    arrangement_duration,
    assemble_studio_bundle,
    export_mix,
    mixdown_arrangement,
    render_track_timeline,
)


def _write_tone(path: Path, duration_s: float = 1.0, freq: float = 220.0, sample_rate: int = 48000) -> Path:
    t = np.linspace(0, duration_s, int(sample_rate * duration_s), endpoint=False)
    mono = (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    sf.write(str(path), np.column_stack([mono, mono]), sample_rate, format="WAV")
    return path


def _read_wav(path: Path):
    data, sr = sf.read(str(path), always_2d=True)
    return data, sr


def _rms(data) -> float:
    return float(np.sqrt(np.mean(np.square(data))))


# ---------------------------------------------------------------------------
# arrangement_duration
# ---------------------------------------------------------------------------


class TestArrangementDuration:
    def test_spans_latest_placement_end(self, tmp_path) -> None:
        a = _write_tone(tmp_path / "a.wav", duration_s=1.0)
        b = _write_tone(tmp_path / "b.wav", duration_s=1.0)
        tracks = [
            TrackMix(placements=[PlacementMix(audio_path=a, start_sec=0.0)]),
            TrackMix(placements=[PlacementMix(audio_path=b, start_sec=2.0)]),
        ]
        # Latest placement starts at 2s with a 1s clip -> 3s arrangement.
        assert arrangement_duration(tracks) == pytest.approx(3.0, abs=0.05)

    def test_honours_duration_sec_trim(self, tmp_path) -> None:
        a = _write_tone(tmp_path / "a.wav", duration_s=4.0)
        tracks = [TrackMix(placements=[PlacementMix(audio_path=a, start_sec=1.0, duration_sec=0.5)])]
        assert arrangement_duration(tracks) == pytest.approx(1.5, abs=0.05)

    def test_empty_arrangement_is_zero(self) -> None:
        assert arrangement_duration([]) == 0.0
        assert arrangement_duration([TrackMix(placements=[])]) == 0.0


# ---------------------------------------------------------------------------
# mixdown_arrangement
# ---------------------------------------------------------------------------


class TestMixdown:
    def test_produces_readable_stereo_wav(self, tmp_path) -> None:
        a = _write_tone(tmp_path / "a.wav", duration_s=1.0)
        out = tmp_path / "mix.wav"
        tracks = [TrackMix(placements=[PlacementMix(audio_path=a, start_sec=0.0)])]
        mixdown_arrangement(tracks, output_path=out)
        data, sr = _read_wav(out)
        assert sr == 48000
        assert data.shape[1] == 2
        assert _rms(data) > 0.0

    def test_placement_positioned_at_start_offset(self, tmp_path) -> None:
        a = _write_tone(tmp_path / "a.wav", duration_s=1.0)
        out = tmp_path / "mix.wav"
        tracks = [TrackMix(placements=[PlacementMix(audio_path=a, start_sec=1.0)])]
        mixdown_arrangement(tracks, output_path=out)
        data, sr = _read_wav(out)
        # First half-second is silence (clip starts at 1.0s), second second is tone.
        head = data[: int(sr * 0.5)]
        body = data[int(sr * 1.0) : int(sr * 1.5)]
        assert _rms(head) < 1e-4
        assert _rms(body) > 0.01

    def test_muted_track_is_silent(self, tmp_path) -> None:
        a = _write_tone(tmp_path / "a.wav", duration_s=1.0)
        out = tmp_path / "mix.wav"
        tracks = [TrackMix(placements=[PlacementMix(audio_path=a, start_sec=0.0)], muted=True)]
        mixdown_arrangement(tracks, output_path=out)
        data, _ = _read_wav(out)
        assert _rms(data) < 1e-4

    def test_solo_silences_non_solo_tracks(self, tmp_path) -> None:
        a = _write_tone(tmp_path / "a.wav", duration_s=1.0, freq=220.0)
        b = _write_tone(tmp_path / "b.wav", duration_s=1.0, freq=440.0)
        solo_only = tmp_path / "solo.wav"
        both = tmp_path / "both.wav"
        # Only the solo track should sound.
        mixdown_arrangement(
            [
                TrackMix(placements=[PlacementMix(audio_path=a, start_sec=0.0)], solo=True),
                TrackMix(placements=[PlacementMix(audio_path=b, start_sec=0.0)]),
            ],
            output_path=solo_only,
        )
        mixdown_arrangement(
            [
                TrackMix(placements=[PlacementMix(audio_path=a, start_sec=0.0)]),
            ],
            output_path=both,
        )
        solo_data, _ = _read_wav(solo_only)
        a_only, _ = _read_wav(both)
        # Soloing track A yields the same signal as mixing track A alone.
        n = min(len(solo_data), len(a_only))
        assert _rms(solo_data[:n] - a_only[:n]) < 1e-3

    def test_muted_solo_track_falls_back_to_all_unmuted(self, tmp_path) -> None:
        a = _write_tone(tmp_path / "a.wav", duration_s=1.0)
        b = _write_tone(tmp_path / "b.wav", duration_s=1.0)
        out = tmp_path / "mix.wav"
        # Mute beats solo: with the only soloed track muted, track B still sounds
        # (a naive has_solo check would silence the whole mix).
        mixdown_arrangement(
            [
                TrackMix(placements=[PlacementMix(audio_path=a, start_sec=0.0)], solo=True, muted=True),
                TrackMix(placements=[PlacementMix(audio_path=b, start_sec=0.0)]),
            ],
            output_path=out,
        )
        data, _ = _read_wav(out)
        assert _rms(data) > 0.01

    def test_volume_db_attenuates(self, tmp_path) -> None:
        a = _write_tone(tmp_path / "a.wav", duration_s=1.0)
        loud = tmp_path / "loud.wav"
        quiet = tmp_path / "quiet.wav"
        mixdown_arrangement([TrackMix(placements=[PlacementMix(audio_path=a, start_sec=0.0)])], output_path=loud)
        mixdown_arrangement(
            [TrackMix(placements=[PlacementMix(audio_path=a, start_sec=0.0)], volume_db=-20.0)],
            output_path=quiet,
        )
        assert _rms(_read_wav(quiet)[0]) < _rms(_read_wav(loud)[0])

    def test_duration_sec_trims_segment(self, tmp_path) -> None:
        a = _write_tone(tmp_path / "a.wav", duration_s=4.0)
        out = tmp_path / "mix.wav"
        mixdown_arrangement(
            [TrackMix(placements=[PlacementMix(audio_path=a, start_sec=0.0, duration_sec=1.0)])],
            output_path=out,
        )
        data, sr = _read_wav(out)
        # Trimmed to ~1s rather than the full 4s clip.
        assert len(data) / sr == pytest.approx(1.0, abs=0.1)

    def test_pan_hard_right_silences_left(self, tmp_path) -> None:
        a = _write_tone(tmp_path / "a.wav", duration_s=1.0)
        out = tmp_path / "mix.wav"
        mixdown_arrangement(
            [TrackMix(placements=[PlacementMix(audio_path=a, start_sec=0.0)], pan=1.0)],
            output_path=out,
        )
        data, _ = _read_wav(out)
        left_rms = _rms(data[:, 0])
        right_rms = _rms(data[:, 1])
        assert left_rms < right_rms
        assert left_rms < 1e-3

    def test_empty_arrangement_writes_silent_file(self, tmp_path) -> None:
        out = tmp_path / "mix.wav"
        mixdown_arrangement([], output_path=out, total_duration_sec=1.0)
        data, sr = _read_wav(out)
        assert sr == 48000
        assert _rms(data) < 1e-4


# ---------------------------------------------------------------------------
# render_track_timeline (DAW stems)
# ---------------------------------------------------------------------------


class TestRenderTrackTimeline:
    def test_silence_padded_from_zero(self, tmp_path) -> None:
        a = _write_tone(tmp_path / "a.wav", duration_s=1.0)
        out = tmp_path / "stem.wav"
        render_track_timeline(
            [PlacementMix(audio_path=a, start_sec=2.0)],
            output_path=out,
            total_duration_sec=3.0,
        )
        data, sr = _read_wav(out)
        # Stem starts at 0 and is padded to the full arrangement length (3s).
        assert len(data) / sr == pytest.approx(3.0, abs=0.05)
        assert _rms(data[: int(sr * 1.0)]) < 1e-4
        assert _rms(data[int(sr * 2.0) :]) > 0.01

    def test_no_volume_or_pan_baked_in(self, tmp_path) -> None:
        # render_track_timeline takes no volume/pan; it is a faithful placement
        # bounce so the DAW re-applies gain/pan from project.json.
        a = _write_tone(tmp_path / "a.wav", duration_s=1.0)
        out = tmp_path / "stem.wav"
        render_track_timeline([PlacementMix(audio_path=a, start_sec=0.0)], output_path=out, total_duration_sec=1.0)
        stem, _ = _read_wav(out)
        src, _ = _read_wav(Path(a))
        n = min(len(stem), len(src))
        assert _rms(stem[:n] - src[:n]) < 1e-3


# ---------------------------------------------------------------------------
# assemble_studio_bundle (DAW ZIP)
# ---------------------------------------------------------------------------


class TestAssembleStudioBundle:
    def test_zip_layout_and_project_json(self, tmp_path) -> None:
        drums = _write_tone(tmp_path / "drums.wav", duration_s=1.0)
        bass = _write_tone(tmp_path / "bass.wav", duration_s=1.0)
        out = tmp_path / "bundle.zip"
        assemble_studio_bundle(
            project_name="My Studio Song",
            bpm=128.0,
            duration_seconds=12.5,
            tracks=[
                StudioTrackFile(name="Drums", audio_path=drums, volume_db=-3.0, pan=0.0, muted=True),
                StudioTrackFile(name="Bass", audio_path=bass, volume_db=0.0, pan=-0.25, solo=True),
            ],
            markers=[{"name": "Verse", "time_sec": 4.0}],
            output_path=out,
        )
        with zipfile.ZipFile(out) as zf:
            names = set(zf.namelist())
            root = "my-studio-song_Export"
            assert f"{root}/project.json" in names
            assert f"{root}/audio/drums.wav" in names
            assert f"{root}/audio/bass.wav" in names
            meta = json.loads(zf.read(f"{root}/project.json"))
        assert meta["project_name"] == "My Studio Song"
        assert meta["bpm"] == 128.0
        assert meta["duration_seconds"] == 12.5
        assert {t["name"]: t["file"] for t in meta["tracks"]} == {
            "Drums": "audio/drums.wav",
            "Bass": "audio/bass.wav",
        }
        assert {t["name"]: t["volume_db"] for t in meta["tracks"]} == {"Drums": -3.0, "Bass": 0.0}
        assert {t["name"]: t["pan"] for t in meta["tracks"]} == {"Drums": 0.0, "Bass": -0.25}
        # Mute/solo intent rides along so a DAW can reconstruct the session state.
        assert {t["name"]: t["muted"] for t in meta["tracks"]} == {"Drums": True, "Bass": False}
        assert {t["name"]: t["solo"] for t in meta["tracks"]} == {"Drums": False, "Bass": True}
        assert meta["markers"] == [{"name": "Verse", "time": 4.0}]

    def test_duplicate_track_names_get_unique_files(self, tmp_path) -> None:
        one = _write_tone(tmp_path / "one.wav", duration_s=0.5)
        two = _write_tone(tmp_path / "two.wav", duration_s=0.5)
        out = tmp_path / "bundle.zip"
        assemble_studio_bundle(
            project_name="Dupes",
            bpm=None,
            duration_seconds=1.0,
            tracks=[
                StudioTrackFile(name="Synth", audio_path=one, volume_db=0.0, pan=0.0),
                StudioTrackFile(name="Synth", audio_path=two, volume_db=0.0, pan=0.0),
            ],
            markers=[],
            output_path=out,
        )
        with zipfile.ZipFile(out) as zf:
            audio = sorted(n for n in zf.namelist() if n.endswith(".wav"))
            meta = json.loads(zf.read("dupes_Export/project.json"))
        # Two distinct files despite the shared display name.
        assert len(audio) == 2
        files = {t["file"] for t in meta["tracks"]}
        assert len(files) == 2

    def test_bytes_roundtrip_readable(self, tmp_path) -> None:
        drums = _write_tone(tmp_path / "drums.wav", duration_s=1.0)
        out = tmp_path / "bundle.zip"
        assemble_studio_bundle(
            project_name="Readable",
            bpm=120.0,
            duration_seconds=1.0,
            tracks=[StudioTrackFile(name="Drums", audio_path=drums, volume_db=0.0, pan=0.0)],
            markers=[],
            output_path=out,
        )
        with zipfile.ZipFile(out) as zf:
            wav_bytes = zf.read("readable_Export/audio/drums.wav")
        data, sr = sf.read(io.BytesIO(wav_bytes), always_2d=True)
        assert sr == 48000
        assert data.shape[1] == 2


# ---------------------------------------------------------------------------
# export_mix — wav/flac are libsndfile-native so they run in CI (no ffmpeg)
# ---------------------------------------------------------------------------


class TestExportMix:
    def test_wav_is_48k_24bit(self, tmp_path) -> None:
        raw = _write_tone(tmp_path / "raw.wav", duration_s=0.5)
        out = export_mix(raw, tmp_path / "mix.wav", "wav")
        info = sf.info(str(out))
        assert info.samplerate == 48000
        assert info.subtype == "PCM_24"
        audio, _ = sf.read(str(out), always_2d=True)
        assert np.sqrt(np.mean(np.square(audio))) > 1e-3

    def test_flac_round_trips(self, tmp_path) -> None:
        raw = _write_tone(tmp_path / "raw.wav", duration_s=0.5)
        out = export_mix(raw, tmp_path / "mix.flac", "flac")
        info = sf.info(str(out))
        assert info.format == "FLAC"
        audio, sr = sf.read(str(out), always_2d=True)
        assert sr == 48000
        assert np.sqrt(np.mean(np.square(audio))) > 1e-3
