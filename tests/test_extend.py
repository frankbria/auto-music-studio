"""Tests for the extend CLI command (US-6.1)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import soundfile as sf
from typer.testing import CliRunner

from acemusic.cli import app
from acemusic.models import Clip

runner = CliRunner()

TASK_ID = "task-ext-123"
AUDIO_URL = "http://localhost:8001/v1/audio?path=extended.wav"
COMPLETED_RESULT = {"status": "completed", "audio_urls": [AUDIO_URL]}
FAILED_RESULT = {"status": "failed", "audio_urls": [], "error": "model overloaded"}


def _write_tone(path, duration_s: float = 1.0, sample_rate: int = 44100):
    """Write a short stereo sine-wave WAV file for use as test source audio."""
    t = np.linspace(0, duration_s, int(sample_rate * duration_s), endpoint=False)
    mono = (0.3 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)
    stereo = np.column_stack([mono, mono])
    sf.write(str(path), stereo, sample_rate)


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    import acemusic.db as _db

    monkeypatch.setattr(_db, "DB_DIR", tmp_path / ".acemusic")
    return tmp_path


@pytest.fixture
def workspace_with_clip(isolated_db):
    """Set up a workspace with a single source clip backed by a real WAV file."""
    from acemusic.db import create_clip
    from acemusic.workspace import ensure_default_workspace, get_active_workspace, get_workspace_path

    ensure_default_workspace()
    ws = get_active_workspace()
    clips_dir = get_workspace_path(ws.id)
    clips_dir.mkdir(parents=True, exist_ok=True)

    src_wav = clips_dir / "source.wav"
    _write_tone(src_wav, duration_s=2.0)

    clip = Clip(
        workspace_id=ws.id,
        file_path=str(src_wav),
        created_at=datetime.now(timezone.utc).isoformat(),
        format="wav",
        duration=2.0,
        bpm=120,
        key="C major",
        style_tags="ambient",
        generation_mode="generate",
    )
    clip_id = create_clip(clip)
    return ws, clip_id, src_wav


def _make_client_mock(audio_bytes: bytes | None = None, query_sequence=None):
    """Return a MagicMock AceStepClient with happy-path defaults."""
    if audio_bytes is None:
        # Generate fresh extended audio with longer duration (3.0s, matches 2.0 src + 1.0 ext)
        import io

        buf = io.BytesIO()
        t = np.linspace(0, 3.0, int(44100 * 3.0), endpoint=False)
        mono = (0.3 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)
        stereo = np.column_stack([mono, mono])
        sf.write(buf, stereo, 44100, format="WAV")
        audio_bytes = buf.getvalue()

    client = MagicMock()
    client.submit_task.return_value = TASK_ID
    client.query_result.side_effect = query_sequence or [COMPLETED_RESULT]
    client.download_audio.return_value = audio_bytes
    return client


class TestExtendCommand:
    """Tests for the `acemusic extend` CLI command (US-6.1)."""

    def test_default_from_end_succeeds(self, workspace_with_clip):
        ws, clip_id, src_wav = workspace_with_clip
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(app, ["extend", str(clip_id), "--duration", "1s"])

        assert result.exit_code == 0, result.output

    def test_creates_child_clip_with_lineage(self, workspace_with_clip):
        ws, clip_id, src_wav = workspace_with_clip
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(app, ["extend", str(clip_id), "--duration", "1s"])

        assert result.exit_code == 0, result.output

        from acemusic.db import list_clips

        clips = list_clips(ws.id)
        extended = [c for c in clips if c.generation_mode == "extend"]
        assert len(extended) == 1
        assert extended[0].parent_clip_id == clip_id

    def test_submits_repaint_task_with_correct_params(self, workspace_with_clip):
        ws, clip_id, src_wav = workspace_with_clip
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(app, ["extend", str(clip_id), "--duration", "1s"])

        assert result.exit_code == 0, result.output
        client.submit_task.assert_called_once()
        kwargs = client.submit_task.call_args.kwargs
        assert kwargs["task_type"] == "repaint"
        assert kwargs["src_audio_path"] == str(src_wav)
        # --from end ⇒ repainting_start at source duration (2.0)
        assert kwargs["repainting_start"] == pytest.approx(2.0, abs=0.01)
        # repainting_end = source duration + extend duration
        assert kwargs["repainting_end"] == pytest.approx(3.0, abs=0.01)

    def test_from_timestamp_overrides_repaint_start(self, workspace_with_clip):
        ws, clip_id, src_wav = workspace_with_clip
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(app, ["extend", str(clip_id), "--duration", "1s", "--from", "1.5s"])

        assert result.exit_code == 0, result.output
        kwargs = client.submit_task.call_args.kwargs
        assert kwargs["repainting_start"] == pytest.approx(1.5, abs=0.01)
        assert kwargs["repainting_end"] == pytest.approx(2.5, abs=0.01)

    def test_style_override_passed_to_api(self, workspace_with_clip):
        ws, clip_id, src_wav = workspace_with_clip
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                ["extend", str(clip_id), "--duration", "1s", "--style", "add a bridge feel"],
            )

        assert result.exit_code == 0, result.output
        kwargs = client.submit_task.call_args.kwargs
        assert kwargs["style"] == "add a bridge feel"

    def test_lyrics_override_passed_to_api(self, workspace_with_clip):
        ws, clip_id, src_wav = workspace_with_clip
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                ["extend", str(clip_id), "--duration", "1s", "--lyrics", "[Bridge]\nWe cross the river"],
            )

        assert result.exit_code == 0, result.output
        kwargs = client.submit_task.call_args.kwargs
        assert "Bridge" in kwargs["lyrics"]

    def test_output_clip_longer_than_original(self, workspace_with_clip):
        """Acceptance: extended clip duration is approximately source + requested duration."""
        ws, clip_id, src_wav = workspace_with_clip
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(app, ["extend", str(clip_id), "--duration", "1s"])

        assert result.exit_code == 0, result.output

        from acemusic.db import list_clips

        clips = list_clips(ws.id)
        extended = [c for c in clips if c.generation_mode == "extend"]
        assert len(extended) == 1
        # Extended duration should be ~3.0s (2.0 source + 1.0 extension)
        assert extended[0].duration is not None
        assert extended[0].duration > 2.0

    def test_chained_extend_uses_new_clip_as_source(self, workspace_with_clip):
        """Acceptance: chaining two extends produces a valid, longer clip."""
        ws, clip_id, src_wav = workspace_with_clip

        client1 = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client1):
            r1 = runner.invoke(app, ["extend", str(clip_id), "--duration", "1s"])
        assert r1.exit_code == 0, r1.output

        from acemusic.db import list_clips

        clips = list_clips(ws.id)
        extended = [c for c in clips if c.generation_mode == "extend"]
        assert len(extended) == 1
        first_extend_id = extended[0].id

        # Second extend on the first extended clip — produce a longer (4s) clip
        import io

        buf = io.BytesIO()
        t = np.linspace(0, 4.0, int(44100 * 4.0), endpoint=False)
        mono = (0.3 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)
        stereo = np.column_stack([mono, mono])
        sf.write(buf, stereo, 44100, format="WAV")

        client2 = _make_client_mock(audio_bytes=buf.getvalue())
        with patch("acemusic.cli.AceStepClient", return_value=client2):
            r2 = runner.invoke(app, ["extend", str(first_extend_id), "--duration", "1s"])
        assert r2.exit_code == 0, r2.output

        clips = list_clips(ws.id)
        extended = sorted(
            [c for c in clips if c.generation_mode == "extend"],
            key=lambda c: c.id,
        )
        assert len(extended) == 2
        assert extended[1].parent_clip_id == first_extend_id


class TestExtendValidation:
    """Tests for input validation of the extend command."""

    def test_nonexistent_clip_returns_error(self, isolated_db):
        from acemusic.workspace import ensure_default_workspace

        ensure_default_workspace()
        result = runner.invoke(app, ["extend", "99999", "--duration", "60s"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_missing_source_file_returns_error(self, isolated_db):
        from acemusic.db import create_clip
        from acemusic.workspace import ensure_default_workspace, get_active_workspace

        ensure_default_workspace()
        ws = get_active_workspace()
        clip = Clip(
            workspace_id=ws.id,
            file_path="/nonexistent/missing.wav",
            created_at=datetime.now(timezone.utc).isoformat(),
            format="wav",
            duration=10.0,
            generation_mode="generate",
        )
        clip_id = create_clip(clip)

        result = runner.invoke(app, ["extend", str(clip_id), "--duration", "60s"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower() or "exist" in result.output.lower()

    def test_invalid_duration_returns_error(self, workspace_with_clip):
        ws, clip_id, src_wav = workspace_with_clip
        result = runner.invoke(app, ["extend", str(clip_id), "--duration", "0s"])
        assert result.exit_code == 1

    def test_negative_duration_returns_error(self, workspace_with_clip):
        ws, clip_id, src_wav = workspace_with_clip
        # parse_time_string rejects '-5s' as invalid format
        result = runner.invoke(app, ["extend", str(clip_id), "--duration", "-5s"])
        assert result.exit_code == 1

    def test_from_timestamp_at_or_past_clip_end_returns_error(self, workspace_with_clip):
        ws, clip_id, src_wav = workspace_with_clip
        # source is 2.0s; --from 5s exceeds duration
        result = runner.invoke(app, ["extend", str(clip_id), "--duration", "1s", "--from", "5s"])
        assert result.exit_code == 1

    def test_api_failure_returns_error(self, workspace_with_clip):
        ws, clip_id, src_wav = workspace_with_clip
        client = _make_client_mock(query_sequence=[FAILED_RESULT])
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(app, ["extend", str(clip_id), "--duration", "1s"])
        assert result.exit_code == 1
        assert "fail" in result.output.lower() or "error" in result.output.lower()
