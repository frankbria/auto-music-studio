"""Tests for the sample CLI command (US-6.5)."""

from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import soundfile as sf
from typer.testing import CliRunner

from acemusic.cli import app
from acemusic.db import list_clips
from acemusic.models import Clip

runner = CliRunner()

TASK_ID = "task-sample-123"
AUDIO_URL = "http://localhost:8001/v1/audio?path=generated.wav"
COMPLETED_RESULT = {"status": "completed", "audio_urls": [AUDIO_URL]}
FAILED_RESULT = {"status": "failed", "audio_urls": [], "error": "model overloaded"}


def _wav_bytes(duration_s: float, sample_rate: int = 44100) -> bytes:
    """Return bytes of a stereo sine-wave WAV at the requested duration."""
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
    """Set up a workspace with a single source clip backed by a real 5s WAV."""
    from acemusic.db import create_clip
    from acemusic.workspace import ensure_default_workspace, get_active_workspace, get_workspace_path

    ensure_default_workspace()
    ws = get_active_workspace()
    clips_dir = get_workspace_path(ws.id)
    clips_dir.mkdir(parents=True, exist_ok=True)

    src_wav = clips_dir / "source.wav"
    write_tone(src_wav, duration_s=5.0)

    clip = Clip(
        workspace_id=ws.id,
        file_path=str(src_wav),
        created_at=datetime.now(timezone.utc).isoformat(),
        title="Morning Theme",
        format="wav",
        duration=5.0,
        bpm=120,
        key="C major",
        style_tags="ambient",
        generation_mode="generate",
    )
    clip_id = create_clip(clip)
    return ws, clip_id, src_wav


def _make_client_mock(audio_bytes: bytes | None = None, query_sequence=None):
    """Return a MagicMock AceStepClient that returns a 6s generated WAV."""
    if audio_bytes is None:
        audio_bytes = _wav_bytes(6.0)
    client = MagicMock()
    client.submit_task.return_value = TASK_ID
    client.query_result.side_effect = query_sequence or [COMPLETED_RESULT]
    client.download_audio.return_value = audio_bytes
    return client


def _make_el_mock(audio_bytes: bytes | None = None):
    """Return a MagicMock ElevenLabsClient that returns a 6s generated WAV."""
    if audio_bytes is None:
        audio_bytes = _wav_bytes(6.0)
    client = MagicMock()
    client.generate.return_value = audio_bytes
    return client


class TestSampleCommandBasics:
    """Basic happy-path and lineage tests for `acemusic sample`."""

    def test_default_succeeds(self, workspace_with_clip):
        ws, clip_id, _src = workspace_with_clip
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                [
                    "sample",
                    str(clip_id),
                    "--start",
                    "1s",
                    "--end",
                    "3s",
                    "--role",
                    "loop-bed",
                    "--prompt",
                    "build a chill track around this",
                ],
            )
        assert result.exit_code == 0, result.output

    def test_creates_child_clip_with_lineage(self, workspace_with_clip):
        """Acceptance: new clip has parent_clip_id=source and generation_mode='sample'."""
        ws, clip_id, _src = workspace_with_clip
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                [
                    "sample",
                    str(clip_id),
                    "--start",
                    "1s",
                    "--end",
                    "3s",
                    "--role",
                    "loop-bed",
                    "--prompt",
                    "chill track",
                ],
            )
        assert result.exit_code == 0, result.output

        clips = list_clips(ws.id)
        sampled = [c for c in clips if c.generation_mode == "sample"]
        assert len(sampled) == 1
        assert sampled[0].parent_clip_id == clip_id

    def test_output_file_exists(self, workspace_with_clip):

        ws, clip_id, _src = workspace_with_clip
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                [
                    "sample",
                    str(clip_id),
                    "--start",
                    "1s",
                    "--end",
                    "3s",
                    "--role",
                    "loop-bed",
                    "--prompt",
                    "chill track",
                ],
            )
        assert result.exit_code == 0, result.output

        sampled = [c for c in list_clips(ws.id) if c.generation_mode == "sample"]
        assert Path(sampled[0].file_path).exists()


class TestSampleValidation:
    """Input validation tests."""

    def test_missing_clip_exits_one(self, isolated_db):
        from acemusic.workspace import ensure_default_workspace

        ensure_default_workspace()
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                [
                    "sample",
                    "9999",
                    "--start",
                    "0s",
                    "--end",
                    "2s",
                    "--role",
                    "loop-bed",
                    "--prompt",
                    "x",
                ],
            )
        assert result.exit_code != 0
        client.submit_task.assert_not_called()

    def test_invalid_role_exits_one(self, workspace_with_clip):
        ws, clip_id, _src = workspace_with_clip
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                [
                    "sample",
                    str(clip_id),
                    "--start",
                    "1s",
                    "--end",
                    "2s",
                    "--role",
                    "bogus-role",
                    "--prompt",
                    "x",
                ],
            )
        assert result.exit_code != 0
        client.submit_task.assert_not_called()

    def test_end_past_duration_exits_one(self, workspace_with_clip):
        ws, clip_id, _src = workspace_with_clip
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                [
                    "sample",
                    str(clip_id),
                    "--start",
                    "1s",
                    "--end",
                    "60s",
                    "--role",
                    "loop-bed",
                    "--prompt",
                    "x",
                ],
            )
        assert result.exit_code != 0
        client.submit_task.assert_not_called()

    def test_end_before_start_exits_one(self, workspace_with_clip):
        ws, clip_id, _src = workspace_with_clip
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                [
                    "sample",
                    str(clip_id),
                    "--start",
                    "3s",
                    "--end",
                    "1s",
                    "--role",
                    "loop-bed",
                    "--prompt",
                    "x",
                ],
            )
        assert result.exit_code != 0
        client.submit_task.assert_not_called()

    def test_invalid_time_format_exits_one(self, workspace_with_clip):
        ws, clip_id, _src = workspace_with_clip
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                [
                    "sample",
                    str(clip_id),
                    "--start",
                    "bogus",
                    "--end",
                    "2s",
                    "--role",
                    "loop-bed",
                    "--prompt",
                    "x",
                ],
            )
        assert result.exit_code != 0
        client.submit_task.assert_not_called()


class TestSampleRoles:
    """Acceptance: different roles produce different placements of the sample."""

    @pytest.mark.parametrize("role", ["loop-bed", "intro-outro", "rhythmic-element", "melodic-hook"])
    def test_each_role_succeeds(self, workspace_with_clip, role):
        ws, clip_id, _src = workspace_with_clip
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                [
                    "sample",
                    str(clip_id),
                    "--start",
                    "1s",
                    "--end",
                    "3s",
                    "--role",
                    role,
                    "--prompt",
                    "chill track",
                ],
            )
        assert result.exit_code == 0, result.output

    def test_role_appears_in_prompt(self, workspace_with_clip):
        """The role should color the prompt passed to the backend."""
        ws, clip_id, _src = workspace_with_clip
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                [
                    "sample",
                    str(clip_id),
                    "--start",
                    "1s",
                    "--end",
                    "3s",
                    "--role",
                    "loop-bed",
                    "--prompt",
                    "lo-fi chill",
                ],
            )
        assert result.exit_code == 0, result.output
        kwargs = client.submit_task.call_args.kwargs
        assert "lo-fi chill" in kwargs["prompt"]
        assert "loop" in kwargs["prompt"].lower()

    def test_roles_produce_different_output_audio(self, workspace_with_clip, tmp_path):
        """Acceptance criterion: different roles produce different placements."""

        ws, clip_id, _src = workspace_with_clip

        outputs: dict[str, bytes] = {}
        for role in ("loop-bed", "intro-outro", "rhythmic-element", "melodic-hook"):
            out_dir = tmp_path / role
            out_dir.mkdir()
            client = _make_client_mock()
            with patch("acemusic.cli.AceStepClient", return_value=client):
                result = runner.invoke(
                    app,
                    [
                        "sample",
                        str(clip_id),
                        "--start",
                        "1s",
                        "--end",
                        "3s",
                        "--role",
                        role,
                        "--prompt",
                        "track",
                        "--output",
                        str(out_dir),
                    ],
                )
            assert result.exit_code == 0, result.output
            files = list(out_dir.glob("*.wav"))
            assert len(files) >= 1
            outputs[role] = Path(files[0]).read_bytes()

        unique = {hash(v) for v in outputs.values()}
        assert len(unique) == 4, "Each role should produce a distinct combination"


class TestSampleMetadata:
    """Acceptance: metadata includes attribution to the source clip and time range."""

    def test_metadata_sidecar_written(self, workspace_with_clip, tmp_path):

        ws, clip_id, src_wav = workspace_with_clip
        out_dir = tmp_path / "samples"
        out_dir.mkdir()
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                [
                    "sample",
                    str(clip_id),
                    "--start",
                    "1s",
                    "--end",
                    "3s",
                    "--role",
                    "loop-bed",
                    "--prompt",
                    "chill track",
                    "--output",
                    str(out_dir),
                ],
            )
        assert result.exit_code == 0, result.output

        meta_files = list(out_dir.glob("*.meta.json"))
        assert len(meta_files) == 1, f"Expected 1 metadata file, got {meta_files}"
        data = json.loads(Path(meta_files[0]).read_text())
        assert data["source_clip_id"] == clip_id
        assert data["source_file"] == str(src_wav)
        assert data["start_ms"] == 1000
        assert data["end_ms"] == 3000
        assert data["role"] == "loop-bed"
        assert data["prompt"] == "chill track"
        assert data["backend"] == "ace-step"
        assert "created_at" in data

    def test_metadata_sidecar_for_elevenlabs(self, workspace_with_clip, monkeypatch, tmp_path):

        from acemusic.config import AceConfig

        monkeypatch.setattr(
            "acemusic.cli.load_config",
            lambda: AceConfig(
                api_url="http://localhost:8001",
                api_key=None,
                elevenlabs_api_key="test-key",
                elevenlabs_output_format="pcm_44100",
            ),
        )

        ws, clip_id, _src = workspace_with_clip
        out_dir = tmp_path / "samples"
        out_dir.mkdir()
        # ElevenLabs returns MP3 bytes — use real WAV for pydub combine to work
        el_client = _make_el_mock(audio_bytes=_wav_bytes(6.0))
        with patch("acemusic.cli.ElevenLabsClient", return_value=el_client):
            result = runner.invoke(
                app,
                [
                    "sample",
                    str(clip_id),
                    "--start",
                    "1s",
                    "--end",
                    "3s",
                    "--role",
                    "loop-bed",
                    "--prompt",
                    "chill",
                    "--backend",
                    "elevenlabs",
                    "--output",
                    str(out_dir),
                ],
            )
        assert result.exit_code == 0, result.output

        meta_files = list(out_dir.glob("*.meta.json"))
        assert len(meta_files) == 1
        data = json.loads(Path(meta_files[0]).read_text())
        assert data["backend"] == "elevenlabs"


class TestSampleBackendRouting:
    """--backend flag routes to the correct generation backend."""

    def test_elevenlabs_backend_routes(self, workspace_with_clip, monkeypatch):
        from acemusic.config import AceConfig

        monkeypatch.setattr(
            "acemusic.cli.load_config",
            lambda: AceConfig(
                api_url="http://localhost:8001",
                api_key=None,
                elevenlabs_api_key="test-key",
                elevenlabs_output_format="pcm_44100",
            ),
        )

        ws, clip_id, _src = workspace_with_clip
        # Need a WAV so pydub.combine_sample can decode generated audio
        el_client = _make_el_mock(audio_bytes=_wav_bytes(6.0))
        ace_client = _make_client_mock()
        with (
            patch("acemusic.cli.ElevenLabsClient", return_value=el_client),
            patch("acemusic.cli.AceStepClient", return_value=ace_client),
        ):
            result = runner.invoke(
                app,
                [
                    "sample",
                    str(clip_id),
                    "--start",
                    "1s",
                    "--end",
                    "3s",
                    "--role",
                    "loop-bed",
                    "--prompt",
                    "chill",
                    "--backend",
                    "elevenlabs",
                ],
            )
        assert result.exit_code == 0, result.output
        el_client.generate.assert_called_once()
        ace_client.submit_task.assert_not_called()

    def test_unknown_backend_exits_one(self, workspace_with_clip):
        ws, clip_id, _src = workspace_with_clip
        result = runner.invoke(
            app,
            [
                "sample",
                str(clip_id),
                "--start",
                "1s",
                "--end",
                "3s",
                "--role",
                "loop-bed",
                "--prompt",
                "x",
                "--backend",
                "nope",
            ],
        )
        assert result.exit_code != 0


class TestSampleOutput:
    """--output flag controls where files land."""

    def test_custom_output_dir(self, workspace_with_clip, tmp_path):
        ws, clip_id, _src = workspace_with_clip
        out_dir = tmp_path / "custom"
        out_dir.mkdir()
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(
                app,
                [
                    "sample",
                    str(clip_id),
                    "--start",
                    "1s",
                    "--end",
                    "3s",
                    "--role",
                    "loop-bed",
                    "--prompt",
                    "x",
                    "--output",
                    str(out_dir),
                ],
            )
        assert result.exit_code == 0, result.output
        wavs = list(out_dir.glob("*.wav"))
        metas = list(out_dir.glob("*.meta.json"))
        assert len(wavs) == 1
        assert len(metas) == 1
