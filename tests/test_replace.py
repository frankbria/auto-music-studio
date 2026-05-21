"""Tests for the replace CLI command (US-6.6)."""

from __future__ import annotations

import io
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import soundfile as sf
from typer.testing import CliRunner

from acemusic.cli import app
from acemusic.client import AceStepError
from acemusic.models import Clip

runner = CliRunner()

TASK_ID = "task-replace-123"
AUDIO_URL = "http://localhost:8001/v1/audio?path=replaced.wav"
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
    if audio_bytes is None:
        audio_bytes = _wav_bytes(4.0, frequency=880.0)
    client = MagicMock()
    client.submit_task.return_value = TASK_ID
    client.query_result.side_effect = query_sequence or [COMPLETED_RESULT]
    client.download_audio.return_value = audio_bytes
    return client


class TestReplaceCommand:
    """Tests for the `acemusic replace` CLI command (US-6.6)."""

    def test_default_succeeds(self, workspace_with_clip):
        ws, clip_id, src_wav = workspace_with_clip
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                [
                    "replace",
                    str(clip_id),
                    "--start",
                    "1s",
                    "--end",
                    "2s",
                    "--prompt",
                    "make this section more energetic",
                ],
            )
        assert result.exit_code == 0, result.output

    def test_creates_child_clip_with_lineage(self, workspace_with_clip):
        ws, clip_id, src_wav = workspace_with_clip
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                [
                    "replace",
                    str(clip_id),
                    "--start",
                    "1s",
                    "--end",
                    "2s",
                    "--prompt",
                    "energetic",
                ],
            )
        assert result.exit_code == 0, result.output

        from acemusic.db import list_clips

        children = [c for c in list_clips(ws.id) if c.generation_mode == "replace"]
        assert len(children) == 1
        assert children[0].parent_clip_id == clip_id

    def test_submits_repaint_task_with_correct_params(self, workspace_with_clip):
        ws, clip_id, src_wav = workspace_with_clip
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                [
                    "replace",
                    str(clip_id),
                    "--start",
                    "1s",
                    "--end",
                    "2s",
                    "--prompt",
                    "energetic",
                ],
            )
        assert result.exit_code == 0, result.output
        client.submit_task.assert_called_once()
        kwargs = client.submit_task.call_args.kwargs
        assert kwargs["task_type"] == "repaint"
        assert kwargs["src_audio_path"] == str(src_wav.resolve())
        assert kwargs["repainting_start"] == pytest.approx(1.0, abs=0.01)
        assert kwargs["repainting_end"] == pytest.approx(2.0, abs=0.01)
        assert kwargs["prompt"] == "energetic"

    def test_lock_context_default_is_on(self, workspace_with_clip):
        """When --lock-context is on (default), output preserves total duration via crossfade stitch."""
        from acemusic.db import list_clips
        from acemusic.utils import get_duration

        ws, clip_id, src_wav = workspace_with_clip
        client = _make_client_mock(audio_bytes=_wav_bytes(4.0, frequency=880.0))
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                [
                    "replace",
                    str(clip_id),
                    "--start",
                    "1s",
                    "--end",
                    "2s",
                    "--prompt",
                    "x",
                ],
            )
        assert result.exit_code == 0, result.output

        children = [c for c in list_clips(ws.id) if c.generation_mode == "replace"]
        assert len(children) == 1
        new_dur = get_duration(children[0].file_path)
        # With lock_context (default), the output preserves the source duration (~4.0s).
        assert new_dur == pytest.approx(4.0, abs=0.2)

    def test_no_lock_context_writes_model_output_as_is(self, workspace_with_clip):
        """--no-lock-context bypasses stitching and uses the model output directly."""
        from acemusic.db import list_clips
        from acemusic.utils import get_duration

        ws, clip_id, src_wav = workspace_with_clip
        # Model returns a 3.0s clip; with --no-lock-context, this is the final duration.
        client = _make_client_mock(audio_bytes=_wav_bytes(3.0, frequency=880.0))
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                [
                    "replace",
                    str(clip_id),
                    "--start",
                    "1s",
                    "--end",
                    "2s",
                    "--prompt",
                    "x",
                    "--no-lock-context",
                ],
            )
        assert result.exit_code == 0, result.output

        children = [c for c in list_clips(ws.id) if c.generation_mode == "replace"]
        assert len(children) == 1
        new_dur = get_duration(children[0].file_path)
        # No stitching: duration matches the model's output, not the source's 4.0s.
        assert new_dur == pytest.approx(3.0, abs=0.2)

    def test_outside_region_preserved_when_locked(self, workspace_with_clip):
        """With --lock-context on, samples outside [start, end] should match the source."""
        from acemusic.db import list_clips

        ws, clip_id, src_wav = workspace_with_clip
        client = _make_client_mock(audio_bytes=_wav_bytes(4.0, frequency=880.0))
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                [
                    "replace",
                    str(clip_id),
                    "--start",
                    "1s",
                    "--end",
                    "2s",
                    "--prompt",
                    "x",
                ],
            )
        assert result.exit_code == 0, result.output

        children = [c for c in list_clips(ws.id) if c.generation_mode == "replace"]
        data, sr = sf.read(children[0].file_path)
        # Clearly-before-crossfade window: 0.0–0.5s
        head = data[: int(0.5 * sr)]
        src_data, src_sr = sf.read(str(src_wav))
        src_head = src_data[: int(0.5 * src_sr)]

        head_rms = np.sqrt(np.mean((head - src_head) ** 2))
        assert head_rms < 0.01, f"Head RMS drift {head_rms} too high — outside region not preserved"

    def test_invalid_time_range_exits(self, workspace_with_clip):
        ws, clip_id, src_wav = workspace_with_clip
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                [
                    "replace",
                    str(clip_id),
                    "--start",
                    "2s",
                    "--end",
                    "1s",
                    "--prompt",
                    "x",
                ],
            )
        assert result.exit_code != 0
        assert "start" in result.output.lower()

    def test_end_exceeds_duration_exits(self, workspace_with_clip):
        ws, clip_id, src_wav = workspace_with_clip
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                [
                    "replace",
                    str(clip_id),
                    "--start",
                    "1s",
                    "--end",
                    "10s",
                    "--prompt",
                    "x",
                ],
            )
        assert result.exit_code != 0
        assert "duration" in result.output.lower()

    def test_missing_clip_exits(self, isolated_db):
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                ["replace", "9999", "--start", "1s", "--end", "2s", "--prompt", "x"],
            )
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_passes_style_when_provided(self, workspace_with_clip):
        ws, clip_id, src_wav = workspace_with_clip
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                [
                    "replace",
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

    def test_failed_task_exits(self, workspace_with_clip):
        ws, clip_id, src_wav = workspace_with_clip
        client = _make_client_mock(query_sequence=[FAILED_RESULT])
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                [
                    "replace",
                    str(clip_id),
                    "--start",
                    "1s",
                    "--end",
                    "2s",
                    "--prompt",
                    "x",
                ],
            )
        assert result.exit_code != 0
        assert "failed" in result.output.lower()

    def test_submit_error_exits(self, workspace_with_clip):
        ws, clip_id, src_wav = workspace_with_clip
        client = MagicMock()
        client.submit_task.side_effect = AceStepError("network down")
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                [
                    "replace",
                    str(clip_id),
                    "--start",
                    "1s",
                    "--end",
                    "2s",
                    "--prompt",
                    "x",
                ],
            )
        assert result.exit_code != 0
        assert "error" in result.output.lower()

    def test_output_directory_overrides_default(self, workspace_with_clip, tmp_path):
        ws, clip_id, src_wav = workspace_with_clip
        custom_dir = tmp_path / "custom-out"
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                [
                    "replace",
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
