"""Tests for the repaint CLI command and audio stitching (US-6.3)."""

from __future__ import annotations

import io
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import soundfile as sf
from typer.testing import CliRunner

from acemusic.cli import app
from acemusic.models import Clip
from tests.helpers_elevenlabs import FAKE_EL_MP3, _el_config, _make_elevenlabs_client_mock

runner = CliRunner()

TASK_ID = "task-repaint-123"
AUDIO_URL = "http://localhost:8001/v1/audio?path=repainted.wav"
COMPLETED_RESULT = {"status": "completed", "audio_urls": [AUDIO_URL]}
FAILED_RESULT = {"status": "failed", "audio_urls": [], "error": "model overloaded"}


def _wav_bytes(duration_s: float, sample_rate: int = 44100, frequency: float = 880.0) -> bytes:
    buf = io.BytesIO()
    t = np.linspace(0, duration_s, int(sample_rate * duration_s), endpoint=False)
    mono = (0.3 * np.sin(2 * np.pi * frequency * t)).astype(np.float32)
    stereo = np.column_stack([mono, mono])
    sf.write(buf, stereo, sample_rate, format="WAV")
    return buf.getvalue()


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    import acemusic.db as _db

    monkeypatch.setattr(_db, "DB_DIR", tmp_path / ".acemusic")
    monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
    return tmp_path


@pytest.fixture
def workspace_with_clip(isolated_db, write_tone):
    """Workspace + 4-second source WAV clip registered in the DB."""
    from acemusic.db import create_clip
    from acemusic.workspace import ensure_default_workspace, get_active_workspace, get_workspace_path

    ensure_default_workspace()
    ws = get_active_workspace()
    clips_dir = get_workspace_path(ws.id)
    clips_dir.mkdir(parents=True, exist_ok=True)

    src_wav = clips_dir / "source.wav"
    write_tone(src_wav, duration_s=4.0, frequency=440.0)

    clip = Clip(
        workspace_id=ws.id,
        file_path=str(src_wav),
        created_at=datetime.now(timezone.utc).isoformat(),
        format="wav",
        duration=4.0,
        bpm=120,
        key="C major",
        style_tags="ambient",
        generation_mode="generate",
    )
    clip_id = create_clip(clip)
    return ws, clip_id, src_wav


def _make_client_mock(audio_bytes: bytes | None = None, query_sequence=None):
    """MagicMock AceStepClient with a happy-path default.

    Default model output is a 4.0s WAV (matching the source duration in the
    fixture). The model is expected to return a full-length clip with the
    section regenerated; the CLI then stitches only that section into the
    original.
    """
    if audio_bytes is None:
        audio_bytes = _wav_bytes(4.0, frequency=880.0)
    client = MagicMock()
    client.submit_task.return_value = TASK_ID
    client.query_result.side_effect = query_sequence or [COMPLETED_RESULT]
    client.download_audio.return_value = audio_bytes
    return client


class TestRepaintCommand:
    """Tests for the `acemusic repaint` CLI command (US-6.3)."""

    def test_default_succeeds(self, workspace_with_clip):
        ws, clip_id, src_wav = workspace_with_clip
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                ["repaint", str(clip_id), "--start", "1s", "--end", "2s", "--prompt", "add a guitar solo"],
            )
        assert result.exit_code == 0, result.output

    def test_creates_child_clip_with_lineage(self, workspace_with_clip):
        ws, clip_id, src_wav = workspace_with_clip
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                ["repaint", str(clip_id), "--start", "1s", "--end", "2s", "--prompt", "guitar solo"],
            )
        assert result.exit_code == 0, result.output

        from acemusic.db import list_clips

        repainted = [c for c in list_clips(ws.id) if c.generation_mode == "repaint"]
        assert len(repainted) == 1
        assert repainted[0].parent_clip_id == clip_id

    def test_submits_repaint_task_with_correct_params(self, workspace_with_clip):
        ws, clip_id, src_wav = workspace_with_clip
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                ["repaint", str(clip_id), "--start", "1s", "--end", "2s", "--prompt", "guitar solo"],
            )
        assert result.exit_code == 0, result.output
        client.submit_task.assert_called_once()
        kwargs = client.submit_task.call_args.kwargs
        assert kwargs["task_type"] == "repaint"
        assert kwargs["src_audio_path"] == str(src_wav.resolve())
        assert kwargs["repainting_start"] == pytest.approx(1.0, abs=0.01)
        assert kwargs["repainting_end"] == pytest.approx(2.0, abs=0.01)
        assert kwargs["prompt"] == "guitar solo"

    def test_passes_style_when_provided(self, workspace_with_clip):
        ws, clip_id, src_wav = workspace_with_clip
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                [
                    "repaint",
                    str(clip_id),
                    "--start",
                    "1s",
                    "--end",
                    "2s",
                    "--prompt",
                    "solo",
                    "--style",
                    "jazz piano",
                ],
            )
        assert result.exit_code == 0, result.output
        assert client.submit_task.call_args.kwargs["style"] == "jazz piano"

    def test_invalid_time_range_exits(self, workspace_with_clip):
        ws, clip_id, src_wav = workspace_with_clip
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                ["repaint", str(clip_id), "--start", "2s", "--end", "1s", "--prompt", "x"],
            )
        assert result.exit_code != 0
        assert "start" in result.output.lower()

    def test_end_exceeds_duration_exits(self, workspace_with_clip):
        ws, clip_id, src_wav = workspace_with_clip
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                ["repaint", str(clip_id), "--start", "1s", "--end", "10s", "--prompt", "x"],
            )
        assert result.exit_code != 0
        assert "duration" in result.output.lower()

    def test_missing_clip_exits(self, isolated_db):
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                ["repaint", "9999", "--start", "1s", "--end", "2s", "--prompt", "x"],
            )
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_truncated_model_output_exits(self, workspace_with_clip):
        """If ACE-Step returns audio shorter than the repaint window, exit with error."""
        ws, clip_id, src_wav = workspace_with_clip
        # Window is 1s–2s but model returns only 1.5s of audio
        client = _make_client_mock(audio_bytes=_wav_bytes(1.5, frequency=880.0))
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                ["repaint", str(clip_id), "--start", "1s", "--end", "2s", "--prompt", "x"],
            )
        assert result.exit_code != 0
        assert "truncated" in result.output.lower()

    def test_failed_task_exits(self, workspace_with_clip):
        ws, clip_id, src_wav = workspace_with_clip
        client = _make_client_mock(query_sequence=[FAILED_RESULT])
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                ["repaint", str(clip_id), "--start", "1s", "--end", "2s", "--prompt", "x"],
            )
        assert result.exit_code != 0
        assert "failed" in result.output.lower()

    def test_output_preserves_total_duration(self, workspace_with_clip):
        """Repaint output duration ≈ source duration − 2 × crossfade_ms.

        For the default 50ms crossfade, a 4.0s source yields a ~3.9s output;
        the 0.2s tolerance covers both the fade subtraction and encode rounding.
        """
        from acemusic.utils import get_duration

        ws, clip_id, src_wav = workspace_with_clip
        client = _make_client_mock(audio_bytes=_wav_bytes(4.0, frequency=880.0))
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                ["repaint", str(clip_id), "--start", "1s", "--end", "2s", "--prompt", "x"],
            )
        assert result.exit_code == 0, result.output

        from acemusic.db import list_clips

        repainted = [c for c in list_clips(ws.id) if c.generation_mode == "repaint"]
        assert len(repainted) == 1
        new_dur = get_duration(repainted[0].file_path)
        assert new_dur == pytest.approx(4.0, abs=0.2)

    def test_output_directory_overrides_default(self, workspace_with_clip, tmp_path):
        ws, clip_id, src_wav = workspace_with_clip
        custom_dir = tmp_path / "custom-out"
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                [
                    "repaint",
                    str(clip_id),
                    "--start",
                    "1s",
                    "--end",
                    "2s",
                    "--prompt",
                    "x",
                    "--output",
                    str(custom_dir),
                ],
            )
        assert result.exit_code == 0, result.output
        assert custom_dir.exists()
        produced = list(custom_dir.glob("*.wav"))
        assert len(produced) == 1

    def test_outside_region_preserved_from_source(self, workspace_with_clip):
        """Samples outside [start, end] (minus the crossfade overlap) should match the source.

        The source clip is a 440Hz tone; the model output is an 880Hz tone. After
        stitching, the audio at t < start (minus a 50ms fade) should be ~440Hz.
        """
        from acemusic.db import list_clips

        ws, clip_id, src_wav = workspace_with_clip
        client = _make_client_mock(audio_bytes=_wav_bytes(4.0, frequency=880.0))
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                ["repaint", str(clip_id), "--start", "1s", "--end", "2s", "--prompt", "x"],
            )
        assert result.exit_code == 0, result.output

        repainted = [c for c in list_clips(ws.id) if c.generation_mode == "repaint"]
        assert len(repainted) == 1

        data, sr = sf.read(repainted[0].file_path)
        # Take a clearly-before-crossfade window: 0.0–0.5s
        head = data[: int(0.5 * sr)]
        # Take a clearly-after-crossfade window: 2.5–3.5s
        tail = data[int(2.5 * sr) : int(3.5 * sr)]
        # Source samples for those windows
        src_data, src_sr = sf.read(str(src_wav))
        src_head = src_data[: int(0.5 * src_sr)]
        src_tail = src_data[int(2.5 * src_sr) : int(3.5 * src_sr)]

        # The head and tail should closely match the source (RMS difference small).
        head_rms = np.sqrt(np.mean((head - src_head) ** 2))
        tail_rms = np.sqrt(np.mean((tail - src_tail) ** 2))
        # Tones at 0.3 amplitude => any drift > 0.05 RMS means the model output bled through.
        assert head_rms < 0.01, f"Head RMS drift {head_rms} too high — outside region not preserved"
        assert tail_rms < 0.01, f"Tail RMS drift {tail_rms} too high — outside region not preserved"


class TestCrossfadeStitchHelper:
    """Tests for the audio.crossfade_stitch utility used by repaint."""

    def test_total_duration_preserved(self):
        from pydub import AudioSegment

        from acemusic.audio import crossfade_stitch

        before = AudioSegment.silent(duration=1000)
        middle = AudioSegment.silent(duration=500)
        after = AudioSegment.silent(duration=1000)

        out = crossfade_stitch(before, middle, after, fade_ms=50)
        # Total = 1000 + 500 + 1000 - 2*50 = 2400 ms
        assert abs(len(out) - 2400) < 5

    def test_fade_zero_yields_concat(self):
        from pydub import AudioSegment

        from acemusic.audio import crossfade_stitch

        before = AudioSegment.silent(duration=500)
        middle = AudioSegment.silent(duration=200)
        after = AudioSegment.silent(duration=300)

        out = crossfade_stitch(before, middle, after, fade_ms=0)
        assert abs(len(out) - 1000) < 5

    def test_short_segments_clamped(self):
        """If fade_ms exceeds segment length, it should clamp instead of erroring."""
        from pydub import AudioSegment

        from acemusic.audio import crossfade_stitch

        before = AudioSegment.silent(duration=20)
        middle = AudioSegment.silent(duration=20)
        after = AudioSegment.silent(duration=20)
        # Should not raise even though fade_ms > segment durations
        out = crossfade_stitch(before, middle, after, fade_ms=100)
        assert len(out) > 0


# ---------------------------------------------------------------------------
# ElevenLabs backend (#98)
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace_with_long_clip(isolated_db, write_tone):
    """Workspace + 12-second ACE-Step-style source WAV (long enough for >=3s sections)."""
    from acemusic.db import create_clip
    from acemusic.workspace import ensure_default_workspace, get_active_workspace, get_workspace_path

    ensure_default_workspace()
    ws = get_active_workspace()
    clips_dir = get_workspace_path(ws.id)
    clips_dir.mkdir(parents=True, exist_ok=True)

    src_wav = clips_dir / "source-long.wav"
    write_tone(src_wav, duration_s=12.0, frequency=440.0)

    clip = Clip(
        workspace_id=ws.id,
        file_path=str(src_wav),
        created_at=datetime.now(timezone.utc).isoformat(),
        format="wav",
        duration=12.0,
        bpm=120,
        key="C major",
        style_tags="ambient",
        model="acestep-v1",
        seed=4242,
        generation_mode="generate",
    )
    clip_id = create_clip(clip)
    return ws, clip_id, src_wav


class TestRepaintElevenLabsBackend:
    """Tests for `repaint --backend elevenlabs` (#98)."""

    def _invoke(self, clip_id, *extra):
        return runner.invoke(
            app,
            [
                "repaint",
                str(clip_id),
                "--start",
                "3s",
                "--end",
                "6s",
                "--prompt",
                "add a guitar solo",
                "--backend",
                "elevenlabs",
                *extra,
            ],
        )

    def test_succeeds_and_creates_mp3_child_clip_with_lineage(self, workspace_with_long_clip, monkeypatch):
        """An ACE-Step WAV source yields an MP3 child clip with full lineage."""
        ws, clip_id, src_wav = workspace_with_long_clip
        _el_config(monkeypatch)
        el = _make_elevenlabs_client_mock()

        with patch("acemusic.cli.ElevenLabsClient", return_value=el):
            result = self._invoke(clip_id)

        assert result.exit_code == 0, result.output

        from acemusic.db import list_clips

        repainted = [c for c in list_clips(ws.id) if c.generation_mode == "repaint"]
        assert len(repainted) == 1
        child = repainted[0]
        assert child.parent_clip_id == clip_id
        assert child.model == "elevenlabs"
        assert child.format == "mp3"
        assert child.file_path.endswith(".mp3")
        assert Path(child.file_path).read_bytes() == FAKE_EL_MP3

    def test_uploads_source_clip_for_inpainting(self, workspace_with_long_clip, monkeypatch):
        """The source file is uploaded to obtain a song_id."""
        ws, clip_id, src_wav = workspace_with_long_clip
        _el_config(monkeypatch)
        el = _make_elevenlabs_client_mock()

        with patch("acemusic.cli.ElevenLabsClient", return_value=el):
            result = self._invoke(clip_id)

        assert result.exit_code == 0, result.output
        el.upload_for_inpainting.assert_called_once()
        uploaded = str(el.upload_for_inpainting.call_args.args[0])
        assert uploaded == str(src_wav)

    def test_plan_keeps_surrounding_audio_and_regenerates_target(self, workspace_with_long_clip, monkeypatch):
        """The composition plan keeps [0,start] + [end,duration] and regenerates [start,end]."""
        ws, clip_id, src_wav = workspace_with_long_clip
        _el_config(monkeypatch)
        el = _make_elevenlabs_client_mock(song_id="song-xyz")

        with patch("acemusic.cli.ElevenLabsClient", return_value=el):
            result = self._invoke(clip_id)

        assert result.exit_code == 0, result.output
        el.generate_from_plan.assert_called_once()
        plan = el.generate_from_plan.call_args.args[0]
        sections = plan["sections"]
        assert len(sections) == 3
        assert sections[0]["source_from"] == {
            "song_id": "song-xyz",
            "range": {"start_ms": 0, "end_ms": 3000},
        }
        assert "source_from" not in sections[1]
        assert sections[1]["duration_ms"] == 3000
        assert "add a guitar solo" in sections[1]["positive_local_styles"]
        assert sections[2]["source_from"] == {
            "song_id": "song-xyz",
            "range": {"start_ms": 6000, "end_ms": 12000},
        }

    def test_repaint_from_zero_omits_leading_keep_section(self, workspace_with_long_clip, monkeypatch):
        """--start 0s produces a plan with no keep section before the regenerated one."""
        ws, clip_id, src_wav = workspace_with_long_clip
        _el_config(monkeypatch)
        el = _make_elevenlabs_client_mock()

        with patch("acemusic.cli.ElevenLabsClient", return_value=el):
            result = runner.invoke(
                app,
                [
                    "repaint",
                    str(clip_id),
                    "--start",
                    "0s",
                    "--end",
                    "4s",
                    "--prompt",
                    "new intro",
                    "--backend",
                    "elevenlabs",
                ],
            )

        assert result.exit_code == 0, result.output
        plan = el.generate_from_plan.call_args.args[0]
        sections = plan["sections"]
        assert len(sections) == 2
        assert "source_from" not in sections[0]
        assert sections[1]["source_from"]["range"] == {"start_ms": 4000, "end_ms": 12000}

    def test_too_narrow_keep_margin_fails_before_upload(self, workspace_with_long_clip, monkeypatch):
        """A keep range under 3s exits with guidance without spending an upload."""
        ws, clip_id, src_wav = workspace_with_long_clip
        _el_config(monkeypatch)
        el = _make_elevenlabs_client_mock()

        with patch("acemusic.cli.ElevenLabsClient", return_value=el):
            result = runner.invoke(
                app,
                [
                    "repaint",
                    str(clip_id),
                    "--start",
                    "1s",
                    "--end",
                    "5s",
                    "--prompt",
                    "solo",
                    "--backend",
                    "elevenlabs",
                ],
            )

        assert result.exit_code == 1
        assert "3s" in result.output
        el.upload_for_inpainting.assert_not_called()

    def test_missing_api_key_errors(self, workspace_with_long_clip, monkeypatch):
        """--backend elevenlabs without ELEVENLABS_API_KEY exits 1 with a clear message."""
        ws, clip_id, src_wav = workspace_with_long_clip
        _el_config(monkeypatch, api_key=None)

        result = self._invoke(clip_id)

        assert result.exit_code == 1
        assert "elevenlabs_api_key" in result.output.lower()

    def test_upload_error_surfaces_as_friendly_message(self, workspace_with_long_clip, monkeypatch):
        """An ElevenLabsError during upload exits 1 with the error message."""
        from acemusic.elevenlabs_client import ElevenLabsError

        ws, clip_id, src_wav = workspace_with_long_clip
        _el_config(monkeypatch)
        el = _make_elevenlabs_client_mock()
        el.upload_for_inpainting.side_effect = ElevenLabsError("ElevenLabs upload failed: 403 — enterprise plan")

        with patch("acemusic.cli.ElevenLabsClient", return_value=el):
            result = self._invoke(clip_id)

        assert result.exit_code == 1
        assert "enterprise plan" in result.output

    def test_generation_error_surfaces_as_friendly_message(self, workspace_with_long_clip, monkeypatch):
        """An ElevenLabsError during plan generation exits 1 with the error message."""
        from acemusic.elevenlabs_client import ElevenLabsError

        ws, clip_id, src_wav = workspace_with_long_clip
        _el_config(monkeypatch)
        el = _make_elevenlabs_client_mock()
        el.generate_from_plan.side_effect = ElevenLabsError("ElevenLabs plan generation failed: 500")

        with patch("acemusic.cli.ElevenLabsClient", return_value=el):
            result = self._invoke(clip_id)

        assert result.exit_code == 1
        assert "500" in result.output

    def test_warns_crossfade_is_ignored(self, workspace_with_long_clip, monkeypatch):
        """A non-default --crossfade-ms triggers an 'ignored' warning on the elevenlabs path."""
        ws, clip_id, src_wav = workspace_with_long_clip
        _el_config(monkeypatch)
        el = _make_elevenlabs_client_mock()

        with patch("acemusic.cli.ElevenLabsClient", return_value=el):
            result = self._invoke(clip_id, "--crossfade-ms", "100")

        assert result.exit_code == 0, result.output
        assert "crossfade" in result.output.lower()
        assert "ignor" in result.output.lower()

    def test_invalid_backend_errors(self, workspace_with_long_clip, monkeypatch):
        """An unknown --backend value exits 1 with the valid choices."""
        ws, clip_id, src_wav = workspace_with_long_clip
        _el_config(monkeypatch)

        result = runner.invoke(
            app,
            [
                "repaint",
                str(clip_id),
                "--start",
                "3s",
                "--end",
                "6s",
                "--prompt",
                "solo",
                "--backend",
                "suno",
            ],
        )

        assert result.exit_code == 1
        assert "Invalid backend" in result.output

    def test_ace_step_path_unchanged_by_default(self, workspace_with_clip):
        """Without --backend, repaint still uses the ACE-Step path."""
        ws, clip_id, src_wav = workspace_with_clip
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                ["repaint", str(clip_id), "--start", "1s", "--end", "2s", "--prompt", "guitar solo"],
            )
        assert result.exit_code == 0, result.output
        client.submit_task.assert_called_once()

    def test_works_without_ace_step_url(self, workspace_with_long_clip, monkeypatch):
        """--backend elevenlabs works in an ElevenLabs-only setup (no ACEMUSIC_BASE_URL)."""
        from acemusic.config import AceConfig

        ws, clip_id, src_wav = workspace_with_long_clip
        monkeypatch.setattr(
            "acemusic.cli.load_config",
            lambda: AceConfig(api_url=None, api_key=None, elevenlabs_api_key="test-key"),
        )
        el = _make_elevenlabs_client_mock()

        with patch("acemusic.cli.ElevenLabsClient", return_value=el):
            result = self._invoke(clip_id)

        assert result.exit_code == 0, result.output
        el.generate_from_plan.assert_called_once()

    def test_ace_step_path_without_url_suggests_elevenlabs(self, workspace_with_long_clip, monkeypatch):
        """The ACE-Step path still requires a URL and hints at --backend elevenlabs."""
        from acemusic.config import AceConfig

        ws, clip_id, src_wav = workspace_with_long_clip
        monkeypatch.setattr(
            "acemusic.cli.load_config",
            lambda: AceConfig(api_url=None, api_key=None, elevenlabs_api_key="test-key"),
        )

        result = runner.invoke(
            app,
            ["repaint", str(clip_id), "--start", "3s", "--end", "6s", "--prompt", "solo"],
        )

        assert result.exit_code == 1
        assert "not configured" in result.output
        assert "--backend elevenlabs" in result.output

    def test_seed_is_threaded_through_and_persisted(self, workspace_with_long_clip, monkeypatch):
        """The source's seed is passed to generate_from_plan and kept on the child clip."""
        ws, clip_id, src_wav = workspace_with_long_clip
        _el_config(monkeypatch)
        el = _make_elevenlabs_client_mock()

        with patch("acemusic.cli.ElevenLabsClient", return_value=el):
            result = self._invoke(clip_id)

        assert result.exit_code == 0, result.output
        assert el.generate_from_plan.call_args.kwargs.get("seed") == 4242

        from acemusic.db import list_clips

        child = [c for c in list_clips(ws.id) if c.generation_mode == "repaint"][0]
        assert child.seed == 4242

    def test_write_failure_exits_cleanly(self, workspace_with_long_clip, monkeypatch):
        """A disk write failure (e.g. read-only --output) exits 1 without a traceback."""
        ws, clip_id, src_wav = workspace_with_long_clip
        _el_config(monkeypatch)
        el = _make_elevenlabs_client_mock()

        with (
            patch("acemusic.cli.ElevenLabsClient", return_value=el),
            patch("acemusic.cli.Path.write_bytes", side_effect=OSError("read-only file system")),
        ):
            result = self._invoke(clip_id)

        assert result.exit_code == 1
        assert "read-only file system" in result.output

    def test_oversized_total_duration_fails_before_upload(self, workspace_with_long_clip, monkeypatch):
        """A source clip over the 600s track limit exits with guidance, never uploading."""
        ws, clip_id, src_wav = workspace_with_long_clip
        _el_config(monkeypatch)
        el = _make_elevenlabs_client_mock()

        # Fake an 11-minute source via metadata (file content is irrelevant here:
        # validation must trip before any upload happens).
        from acemusic.db import get_db

        with get_db() as conn:
            conn.execute("UPDATE clips SET duration = 660.0 WHERE id = ?", (clip_id,))

        with patch("acemusic.cli.ElevenLabsClient", return_value=el):
            result = runner.invoke(
                app,
                [
                    "repaint",
                    str(clip_id),
                    "--start",
                    "60s",
                    "--end",
                    "70s",
                    "--prompt",
                    "new bridge",
                    "--backend",
                    "elevenlabs",
                ],
            )

        assert result.exit_code == 1
        assert "600" in result.output
        el.upload_for_inpainting.assert_not_called()
