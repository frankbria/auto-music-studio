"""Tests for the repaint CLI command and audio stitching (US-6.3)."""

from __future__ import annotations

import io
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import soundfile as sf
from typer.testing import CliRunner

from acemusic.cli import app
from acemusic.models import Clip

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
        """Repaint output should have the same overall duration as the source.

        The stitched result is original[0:start] + repaint[start:end] + original[end:],
        which sums to the original duration regardless of crossfade overlap.
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
