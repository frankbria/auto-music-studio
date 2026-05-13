"""Tests for the cover CLI command (US-6.2)."""

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

TASK_ID = "task-cover-123"
AUDIO_URL = "http://localhost:8001/v1/audio?path=cover.wav"
COMPLETED_RESULT = {"status": "completed", "audio_urls": [AUDIO_URL]}
PENDING_RESULT = {"status": "pending", "audio_urls": []}
FAILED_RESULT = {"status": "failed", "audio_urls": [], "error": "model overloaded"}


def _wav_bytes(duration_s: float, sample_rate: int = 44100) -> bytes:
    buf = io.BytesIO()
    t = np.linspace(0, duration_s, int(sample_rate * duration_s), endpoint=False)
    mono = (0.3 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)
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
    """Set up a workspace with a single source clip backed by a real WAV file."""
    from acemusic.db import create_clip
    from acemusic.workspace import ensure_default_workspace, get_active_workspace, get_workspace_path

    ensure_default_workspace()
    ws = get_active_workspace()
    clips_dir = get_workspace_path(ws.id)
    clips_dir.mkdir(parents=True, exist_ok=True)

    src_wav = clips_dir / "source.wav"
    write_tone(src_wav, duration_s=2.0)

    clip = Clip(
        workspace_id=ws.id,
        file_path=str(src_wav),
        created_at=datetime.now(timezone.utc).isoformat(),
        format="wav",
        duration=2.0,
        bpm=120,
        key="C major",
        style_tags="ambient",
        lyrics="[Verse]\nOriginal words",
        generation_mode="generate",
    )
    clip_id = create_clip(clip)
    return ws, clip_id, src_wav


def _make_client_mock(audio_bytes: bytes | None = None, query_sequence=None):
    if audio_bytes is None:
        audio_bytes = _wav_bytes(2.0)
    client = MagicMock()
    client.submit_task.return_value = TASK_ID
    client.query_result.side_effect = query_sequence or [COMPLETED_RESULT]
    client.download_audio.return_value = audio_bytes
    return client


class TestCoverCommand:
    """Tests for the `acemusic cover` CLI command (US-6.2)."""

    def test_default_succeeds(self, workspace_with_clip):
        ws, clip_id, src_wav = workspace_with_clip
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(app, ["cover", str(clip_id), "--style", "jazz piano trio"])

        assert result.exit_code == 0, result.output

    def test_creates_child_clip_with_lineage(self, workspace_with_clip):
        ws, clip_id, src_wav = workspace_with_clip
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(app, ["cover", str(clip_id), "--style", "jazz piano trio"])

        assert result.exit_code == 0, result.output

        from acemusic.db import list_clips

        clips = list_clips(ws.id)
        covers = [c for c in clips if c.generation_mode == "cover"]
        assert len(covers) == 1
        assert covers[0].parent_clip_id == clip_id

    def test_cover_clip_records_new_style(self, workspace_with_clip):
        ws, clip_id, src_wav = workspace_with_clip
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(app, ["cover", str(clip_id), "--style", "jazz piano trio"])
        assert result.exit_code == 0, result.output

        from acemusic.db import list_clips

        covers = [c for c in list_clips(ws.id) if c.generation_mode == "cover"]
        assert covers[0].style_tags == "jazz piano trio"

    def test_cover_inherits_title(self, isolated_db, write_tone):
        from acemusic.db import create_clip, list_clips
        from acemusic.workspace import ensure_default_workspace, get_active_workspace, get_workspace_path

        ensure_default_workspace()
        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        clips_dir.mkdir(parents=True, exist_ok=True)
        src_wav = clips_dir / "source.wav"
        write_tone(src_wav, duration_s=2.0)

        clip = Clip(
            workspace_id=ws.id,
            file_path=str(src_wav),
            created_at=datetime.now(timezone.utc).isoformat(),
            title="Morning Theme",
            format="wav",
            duration=2.0,
            generation_mode="generate",
        )
        clip_id = create_clip(clip)

        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(app, ["cover", str(clip_id), "--style", "jazz piano trio"])
        assert result.exit_code == 0, result.output

        covers = [c for c in list_clips(ws.id) if c.generation_mode == "cover"]
        assert len(covers) == 1
        assert covers[0].title == "Morning Theme (cover)"

    def test_submits_cover_task_with_correct_params(self, workspace_with_clip):
        ws, clip_id, src_wav = workspace_with_clip
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(app, ["cover", str(clip_id), "--style", "jazz piano trio"])

        assert result.exit_code == 0, result.output
        client.submit_task.assert_called_once()
        kwargs = client.submit_task.call_args.kwargs
        assert kwargs["task_type"] == "cover"
        assert kwargs["src_audio_path"] == str(src_wav.resolve())
        assert kwargs["style"] == "jazz piano trio"
        assert kwargs["prompt"] == "jazz piano trio"

    def test_output_directory_overrides_default(self, workspace_with_clip, tmp_path):
        ws, clip_id, src_wav = workspace_with_clip
        custom_dir = tmp_path / "custom-out"
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                ["cover", str(clip_id), "--style", "jazz", "--output", str(custom_dir)],
            )
        assert result.exit_code == 0, result.output
        assert custom_dir.exists()
        produced = list(custom_dir.glob("*.wav"))
        assert len(produced) == 1

    def test_name_option_sets_filename_and_title(self, workspace_with_clip):
        ws, clip_id, src_wav = workspace_with_clip
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                ["cover", str(clip_id), "--style", "jazz", "--name", "My Jazz Take"],
            )
        assert result.exit_code == 0, result.output

        from acemusic.db import list_clips

        covers = [c for c in list_clips(ws.id) if c.generation_mode == "cover"]
        assert len(covers) == 1
        assert covers[0].title == "My Jazz Take"
        assert "my-jazz-take" in covers[0].file_path.lower()

    def test_lyrics_override_passed_to_api(self, workspace_with_clip):
        ws, clip_id, src_wav = workspace_with_clip
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                ["cover", str(clip_id), "--style", "jazz piano trio", "--lyrics", "[Verse]\nNew words"],
            )

        assert result.exit_code == 0, result.output
        kwargs = client.submit_task.call_args.kwargs
        assert "New words" in kwargs["lyrics"]

    def test_voice_flag_shows_placeholder_message(self, workspace_with_clip):
        ws, clip_id, src_wav = workspace_with_clip
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                ["cover", str(clip_id), "--style", "jazz piano trio", "--voice", "voice-1"],
            )
        assert result.exit_code == 0, result.output
        assert "Stage 25" in result.output

    def test_polls_until_complete(self, workspace_with_clip):
        ws, clip_id, src_wav = workspace_with_clip
        client = _make_client_mock(query_sequence=[PENDING_RESULT, COMPLETED_RESULT])
        with patch("acemusic.cli.AceStepClient", return_value=client), patch("acemusic.cli.time.sleep"):
            result = runner.invoke(app, ["cover", str(clip_id), "--style", "jazz piano trio"])
        assert result.exit_code == 0, result.output
        assert client.query_result.call_count == 2


class TestCoverValidation:
    """Tests for input validation and error handling of the cover command."""

    def test_nonexistent_clip_returns_error(self, isolated_db):
        from acemusic.workspace import ensure_default_workspace

        ensure_default_workspace()
        result = runner.invoke(app, ["cover", "99999", "--style", "jazz piano trio"])
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

        result = runner.invoke(app, ["cover", str(clip_id), "--style", "jazz piano trio"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower() or "exist" in result.output.lower()

    def test_missing_style_returns_error(self, workspace_with_clip):
        ws, clip_id, src_wav = workspace_with_clip
        result = runner.invoke(app, ["cover", str(clip_id)])
        assert result.exit_code != 0

    def test_api_failure_returns_error(self, workspace_with_clip):
        ws, clip_id, src_wav = workspace_with_clip
        client = _make_client_mock(query_sequence=[FAILED_RESULT])
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(app, ["cover", str(clip_id), "--style", "jazz piano trio"])
        assert result.exit_code == 1
        assert "fail" in result.output.lower() or "error" in result.output.lower()

    def test_connection_error_returns_error(self, workspace_with_clip):
        ws, clip_id, src_wav = workspace_with_clip
        client = MagicMock()
        client.submit_task.side_effect = AceStepError("connection refused")
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(app, ["cover", str(clip_id), "--style", "jazz piano trio"])
        assert result.exit_code == 1
        assert "error" in result.output.lower()


@pytest.mark.integration
class TestCoverIntegration:
    """Integration tests for cover against a live ACE-Step server."""

    def test_cover_live_server(self, integration_url, isolated_db, write_tone):
        from acemusic.db import create_clip
        from acemusic.workspace import ensure_default_workspace, get_active_workspace, get_workspace_path

        ensure_default_workspace()
        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        clips_dir.mkdir(parents=True, exist_ok=True)
        src_wav = clips_dir / "source.wav"
        write_tone(src_wav, duration_s=30.0)

        clip = Clip(
            workspace_id=ws.id,
            file_path=str(src_wav.resolve()),
            created_at=datetime.now(timezone.utc).isoformat(),
            format="wav",
            duration=30.0,
            generation_mode="generate",
        )
        clip_id = create_clip(clip)

        result = runner.invoke(
            app,
            ["cover", str(clip_id), "--style", "jazz piano trio"],
            env={"ACEMUSIC_BASE_URL": integration_url},
        )
        assert result.exit_code == 0, result.output

        from acemusic.db import list_clips

        covers = [c for c in list_clips(ws.id) if c.generation_mode == "cover"]
        assert len(covers) == 1
        out_path = covers[0].file_path
        with open(out_path, "rb") as f:
            header = f.read(4)
        assert header == b"RIFF"
