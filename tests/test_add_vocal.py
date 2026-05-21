"""Tests for the add-vocal CLI command (US-6.6)."""

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

TASK_ID = "task-add-vocal-123"
AUDIO_URL = "http://localhost:8001/v1/audio?path=add-vocal.wav"
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
    """Workspace + 2-second instrumental source WAV clip registered in the DB."""
    from acemusic.db import create_clip
    from acemusic.workspace import ensure_default_workspace, get_active_workspace, get_workspace_path

    ensure_default_workspace()
    ws = get_active_workspace()
    clips_dir = get_workspace_path(ws.id)
    clips_dir.mkdir(parents=True, exist_ok=True)

    src_wav = clips_dir / "instrumental.wav"
    write_tone(src_wav, duration_s=2.0, frequency=440.0)

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
    if audio_bytes is None:
        audio_bytes = _wav_bytes(2.0)
    client = MagicMock()
    client.submit_task.return_value = TASK_ID
    client.query_result.side_effect = query_sequence or [COMPLETED_RESULT]
    client.download_audio.return_value = audio_bytes
    return client


class TestAddVocalCommand:
    """Tests for the `acemusic add-vocal` CLI command (US-6.6)."""

    def test_default_succeeds(self, workspace_with_clip):
        ws, clip_id, src_wav = workspace_with_clip
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                ["add-vocal", str(clip_id), "--lyrics", "[Verse]\nHello world"],
            )
        assert result.exit_code == 0, result.output

    def test_creates_child_clip_with_lineage(self, workspace_with_clip):
        ws, clip_id, src_wav = workspace_with_clip
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                ["add-vocal", str(clip_id), "--lyrics", "[Verse]\nHello world"],
            )
        assert result.exit_code == 0, result.output

        from acemusic.db import list_clips

        children = [c for c in list_clips(ws.id) if c.generation_mode == "add_vocal"]
        assert len(children) == 1
        assert children[0].parent_clip_id == clip_id

    def test_submits_complete_task_with_correct_params(self, workspace_with_clip):
        ws, clip_id, src_wav = workspace_with_clip
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                [
                    "add-vocal",
                    str(clip_id),
                    "--lyrics",
                    "[Verse]\nHello world",
                    "--voice",
                    "soulful",
                    "--style",
                    "breathy, soulful",
                ],
            )
        assert result.exit_code == 0, result.output
        client.submit_task.assert_called_once()
        kwargs = client.submit_task.call_args.kwargs
        assert kwargs["task_type"] == "complete"
        assert kwargs["src_audio_path"] == str(src_wav.resolve())
        assert kwargs["lyrics"] == "[Verse]\nHello world"
        assert kwargs["style"] == "breathy, soulful"
        # The prompt describes the instrumental backdrop (from source.style_tags),
        # not the vocal style — those are separate concepts.
        assert kwargs["prompt"] == "ambient"
        assert kwargs["prompt"] != kwargs["style"]

    def test_lyrics_required(self, workspace_with_clip):
        ws, clip_id, src_wav = workspace_with_clip
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(app, ["add-vocal", str(clip_id)])
        assert result.exit_code != 0

    def test_missing_clip_exits(self, isolated_db):
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                ["add-vocal", "9999", "--lyrics", "hi"],
            )
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_default_voice_suppresses_stage_25_warning(self, workspace_with_clip):
        """When --voice is left at its default, the Stage 25 stub warning should not fire."""
        ws, clip_id, src_wav = workspace_with_clip
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                ["add-vocal", str(clip_id), "--lyrics", "[Verse]\nHi"],
            )
        assert result.exit_code == 0, result.output
        assert "Stage 25" not in result.output

    def test_non_default_voice_emits_stage_25_warning(self, workspace_with_clip):
        """When --voice is set to something other than default, the user should see the stub warning."""
        ws, clip_id, src_wav = workspace_with_clip
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                ["add-vocal", str(clip_id), "--lyrics", "[Verse]\nHi", "--voice", "soulful"],
            )
        assert result.exit_code == 0, result.output
        assert "Stage 25" in result.output

    def test_failed_task_exits(self, workspace_with_clip):
        ws, clip_id, src_wav = workspace_with_clip
        client = _make_client_mock(query_sequence=[FAILED_RESULT])
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                ["add-vocal", str(clip_id), "--lyrics", "hi"],
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
                ["add-vocal", str(clip_id), "--lyrics", "hi"],
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
                    "add-vocal",
                    str(clip_id),
                    "--lyrics",
                    "hi",
                    "--output",
                    str(custom_dir),
                ],
            )
        assert result.exit_code == 0, result.output
        assert custom_dir.exists()
        produced = list(custom_dir.glob("*.wav"))
        assert len(produced) == 1

    def test_name_overrides_filename_prefix(self, workspace_with_clip):
        ws, clip_id, src_wav = workspace_with_clip
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                [
                    "add-vocal",
                    str(clip_id),
                    "--lyrics",
                    "hi",
                    "--name",
                    "my-song",
                ],
            )
        assert result.exit_code == 0, result.output
        from acemusic.db import list_clips

        children = [c for c in list_clips(ws.id) if c.generation_mode == "add_vocal"]
        assert len(children) == 1
        assert "my-song" in children[0].file_path

    def test_falls_back_to_probing_when_duration_missing(self, isolated_db, write_tone):
        """When source.duration is None, add-vocal should probe the file via get_duration()."""
        from acemusic.db import create_clip, list_clips
        from acemusic.workspace import ensure_default_workspace, get_active_workspace, get_workspace_path

        ensure_default_workspace()
        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        clips_dir.mkdir(parents=True, exist_ok=True)

        src_wav = clips_dir / "no-duration.wav"
        write_tone(src_wav, duration_s=2.0, frequency=440.0)

        clip = Clip(
            workspace_id=ws.id,
            file_path=str(src_wav),
            created_at=datetime.now(timezone.utc).isoformat(),
            format="wav",
            duration=None,
            generation_mode="generate",
        )
        clip_id = create_clip(clip)

        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                ["add-vocal", str(clip_id), "--lyrics", "hi"],
            )
        assert result.exit_code == 0, result.output

        # The audio_duration kwarg should be ~2.0s — derived from the probed file.
        kwargs = client.submit_task.call_args.kwargs
        assert kwargs["audio_duration"] == pytest.approx(2.0, abs=0.1)

        children = [c for c in list_clips(ws.id) if c.generation_mode == "add_vocal"]
        assert len(children) == 1

    def test_records_lyrics_on_new_clip(self, workspace_with_clip):
        ws, clip_id, src_wav = workspace_with_clip
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                ["add-vocal", str(clip_id), "--lyrics", "[Verse]\nHello world"],
            )
        assert result.exit_code == 0, result.output

        from acemusic.db import list_clips

        children = [c for c in list_clips(ws.id) if c.generation_mode == "add_vocal"]
        assert children[0].lyrics == "[Verse]\nHello world"
