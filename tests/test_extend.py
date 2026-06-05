"""Tests for the extend CLI command (US-6.1)."""

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

runner = CliRunner()

TASK_ID = "task-ext-123"
AUDIO_URL = "http://localhost:8001/v1/audio?path=extended.wav"
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
        generation_mode="generate",
    )
    clip_id = create_clip(clip)
    return ws, clip_id, src_wav


def _make_client_mock(audio_bytes: bytes | None = None, query_sequence=None):
    """Return a MagicMock AceStepClient with happy-path defaults.

    Default audio output is a 3.0s WAV — matching a 2.0s source clip extended
    by 1.0s, which is the standard fixture scenario.
    """
    if audio_bytes is None:
        audio_bytes = _wav_bytes(3.0)

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

    def test_extended_clip_inherits_title(self, isolated_db, write_tone):
        """When the source has a title, the extended clip derives a title from it."""
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
            result = runner.invoke(app, ["extend", str(clip_id), "--duration", "1s"])
        assert result.exit_code == 0, result.output

        extended = [c for c in list_clips(ws.id) if c.generation_mode == "extend"]
        assert len(extended) == 1
        assert extended[0].title == "Morning Theme (extended)"

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
        client2 = _make_client_mock(audio_bytes=_wav_bytes(4.0))
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

    def test_from_zero_returns_error(self, workspace_with_clip):
        """--from 0s is below the minimum boundary (must be > 0)."""
        ws, clip_id, src_wav = workspace_with_clip
        result = runner.invoke(app, ["extend", str(clip_id), "--duration", "1s", "--from", "0s"])
        assert result.exit_code == 1

    def test_from_exactly_at_clip_end_succeeds(self, workspace_with_clip):
        """--from <source_duration> should succeed (same as --from end)."""
        ws, clip_id, src_wav = workspace_with_clip
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(app, ["extend", str(clip_id), "--duration", "1s", "--from", "2s"])
        assert result.exit_code == 0, result.output
        kwargs = client.submit_task.call_args.kwargs
        assert kwargs["repainting_start"] == pytest.approx(2.0, abs=0.01)

    def test_api_failure_returns_error(self, workspace_with_clip):
        ws, clip_id, src_wav = workspace_with_clip
        client = _make_client_mock(query_sequence=[FAILED_RESULT])
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(app, ["extend", str(clip_id), "--duration", "1s"])
        assert result.exit_code == 1
        assert "fail" in result.output.lower() or "error" in result.output.lower()


# ---------------------------------------------------------------------------
# ElevenLabs backend (#98)
# ---------------------------------------------------------------------------

FAKE_EL_MP3 = b"ID3" + b"\x00" * 200


def _el_config(monkeypatch, api_key="test-key", output_format="mp3_44100_128"):
    """Point load_config at an ElevenLabs-enabled config."""
    from acemusic.config import AceConfig

    monkeypatch.setattr(
        "acemusic.cli.load_config",
        lambda: AceConfig(
            api_url="http://localhost:8001",
            api_key=None,
            elevenlabs_api_key=api_key,
            elevenlabs_output_format=output_format,
        ),
    )


def _make_elevenlabs_client_mock(audio_bytes: bytes = FAKE_EL_MP3, song_id: str = "song-123"):
    """MagicMock ElevenLabsClient with a happy-path upload→plan→compose default."""
    el = MagicMock()
    el.upload_for_inpainting.return_value = song_id
    el.generate_from_plan.return_value = audio_bytes
    return el


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
    write_tone(src_wav, duration_s=12.0)

    clip = Clip(
        workspace_id=ws.id,
        file_path=str(src_wav),
        created_at=datetime.now(timezone.utc).isoformat(),
        format="wav",
        duration=12.0,
        bpm=120,
        key="C major",
        style_tags="ambient",
        lyrics="og lyric",
        model="acestep-v1",
        seed=4242,
        generation_mode="generate",
    )
    clip_id = create_clip(clip)
    return ws, clip_id, src_wav


class TestExtendElevenLabsBackend:
    """Tests for `extend --backend elevenlabs` (#98)."""

    def test_append_at_end_creates_mp3_child_clip_with_lineage(self, workspace_with_long_clip, monkeypatch):
        """Default --from end keeps the whole clip and appends a new section."""
        ws, clip_id, src_wav = workspace_with_long_clip
        _el_config(monkeypatch)
        el = _make_elevenlabs_client_mock(song_id="song-ext")

        with patch("acemusic.cli.ElevenLabsClient", return_value=el):
            result = runner.invoke(
                app,
                ["extend", str(clip_id), "--duration", "5s", "--backend", "elevenlabs"],
            )

        assert result.exit_code == 0, result.output

        el.upload_for_inpainting.assert_called_once()
        assert str(el.upload_for_inpainting.call_args.args[0]) == str(src_wav)

        plan = el.generate_from_plan.call_args.args[0]
        sections = plan["sections"]
        assert len(sections) == 2
        assert sections[0]["source_from"] == {
            "song_id": "song-ext",
            "range": {"start_ms": 0, "end_ms": 12000},
        }
        assert "source_from" not in sections[1]
        assert sections[1]["duration_ms"] == 5000

        from acemusic.db import list_clips

        extended = [c for c in list_clips(ws.id) if c.generation_mode == "extend"]
        assert len(extended) == 1
        child = extended[0]
        assert child.parent_clip_id == clip_id
        assert child.model == "elevenlabs"
        assert child.format == "mp3"
        assert Path(child.file_path).read_bytes() == FAKE_EL_MP3

    def test_from_midpoint_keeps_only_audio_before_splice(self, workspace_with_long_clip, monkeypatch):
        """--from 6s keeps [0,6s] and generates [6s,11s]; audio past 6s is replaced."""
        ws, clip_id, src_wav = workspace_with_long_clip
        _el_config(monkeypatch)
        el = _make_elevenlabs_client_mock()

        with patch("acemusic.cli.ElevenLabsClient", return_value=el):
            result = runner.invoke(
                app,
                ["extend", str(clip_id), "--duration", "5s", "--from", "6s", "--backend", "elevenlabs"],
            )

        assert result.exit_code == 0, result.output
        plan = el.generate_from_plan.call_args.args[0]
        sections = plan["sections"]
        assert len(sections) == 2
        assert sections[0]["source_from"]["range"] == {"start_ms": 0, "end_ms": 6000}
        assert "source_from" not in sections[1]
        assert sections[1]["duration_ms"] == 5000

    def test_style_and_lyrics_shape_the_new_section(self, workspace_with_long_clip, monkeypatch):
        """--style and --lyrics land in the new section's styles and lines."""
        ws, clip_id, src_wav = workspace_with_long_clip
        _el_config(monkeypatch)
        el = _make_elevenlabs_client_mock()

        with patch("acemusic.cli.ElevenLabsClient", return_value=el):
            result = runner.invoke(
                app,
                [
                    "extend",
                    str(clip_id),
                    "--duration",
                    "5s",
                    "--style",
                    "epic strings",
                    "--lyrics",
                    "new line one\nnew line two",
                    "--backend",
                    "elevenlabs",
                ],
            )

        assert result.exit_code == 0, result.output
        new_section = el.generate_from_plan.call_args.args[0]["sections"][-1]
        assert "epic strings" in new_section["positive_local_styles"]
        assert new_section["lines"] == ["new line one", "new line two"]
        # --style is an override: the source's old style tags must not be
        # blended in, or the section gets contradictory directions.
        assert "ambient" not in new_section["positive_local_styles"]

    def test_source_style_shapes_the_new_section_without_override(self, workspace_with_long_clip, monkeypatch):
        """Without --style, the source's style tags describe the new section."""
        ws, clip_id, src_wav = workspace_with_long_clip
        _el_config(monkeypatch)
        el = _make_elevenlabs_client_mock()

        with patch("acemusic.cli.ElevenLabsClient", return_value=el):
            result = runner.invoke(
                app,
                ["extend", str(clip_id), "--duration", "5s", "--backend", "elevenlabs"],
            )

        assert result.exit_code == 0, result.output
        new_section = el.generate_from_plan.call_args.args[0]["sections"][-1]
        assert "ambient" in new_section["positive_local_styles"]

    def test_seed_is_threaded_through_and_persisted(self, workspace_with_long_clip, monkeypatch):
        """The source's seed is passed to generate_from_plan and kept on the child clip."""
        ws, clip_id, src_wav = workspace_with_long_clip
        _el_config(monkeypatch)
        el = _make_elevenlabs_client_mock()

        with patch("acemusic.cli.ElevenLabsClient", return_value=el):
            result = runner.invoke(
                app,
                ["extend", str(clip_id), "--duration", "5s", "--backend", "elevenlabs"],
            )

        assert result.exit_code == 0, result.output
        assert el.generate_from_plan.call_args.kwargs.get("seed") == 4242

        from acemusic.db import list_clips

        child = [c for c in list_clips(ws.id) if c.generation_mode == "extend"][0]
        assert child.seed == 4242

    def test_write_failure_exits_cleanly(self, workspace_with_long_clip, monkeypatch):
        """A disk write failure exits 1 without a traceback."""
        ws, clip_id, src_wav = workspace_with_long_clip
        _el_config(monkeypatch)
        el = _make_elevenlabs_client_mock()

        with (
            patch("acemusic.cli.ElevenLabsClient", return_value=el),
            patch("acemusic.cli.Path.write_bytes", side_effect=OSError("read-only file system")),
        ):
            result = runner.invoke(
                app,
                ["extend", str(clip_id), "--duration", "5s", "--backend", "elevenlabs"],
            )

        assert result.exit_code == 1
        assert "read-only file system" in result.output

    def test_too_short_extension_fails_before_upload(self, workspace_with_long_clip, monkeypatch):
        """--duration under 3s exits with guidance without spending an upload."""
        ws, clip_id, src_wav = workspace_with_long_clip
        _el_config(monkeypatch)
        el = _make_elevenlabs_client_mock()

        with patch("acemusic.cli.ElevenLabsClient", return_value=el):
            result = runner.invoke(
                app,
                ["extend", str(clip_id), "--duration", "1s", "--backend", "elevenlabs"],
            )

        assert result.exit_code == 1
        assert "3s" in result.output
        el.upload_for_inpainting.assert_not_called()

    def test_missing_api_key_errors(self, workspace_with_long_clip, monkeypatch):
        """--backend elevenlabs without ELEVENLABS_API_KEY exits 1 with a clear message."""
        ws, clip_id, src_wav = workspace_with_long_clip
        _el_config(monkeypatch, api_key=None)

        result = runner.invoke(
            app,
            ["extend", str(clip_id), "--duration", "5s", "--backend", "elevenlabs"],
        )

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
            result = runner.invoke(
                app,
                ["extend", str(clip_id), "--duration", "5s", "--backend", "elevenlabs"],
            )

        assert result.exit_code == 1
        assert "enterprise plan" in result.output

    def test_invalid_backend_errors(self, workspace_with_long_clip, monkeypatch):
        """An unknown --backend value exits 1 with the valid choices."""
        ws, clip_id, src_wav = workspace_with_long_clip
        _el_config(monkeypatch)

        result = runner.invoke(
            app,
            ["extend", str(clip_id), "--duration", "5s", "--backend", "suno"],
        )

        assert result.exit_code == 1
        assert "Invalid backend" in result.output

    def test_ace_step_path_unchanged_by_default(self, workspace_with_clip):
        """Without --backend, extend still uses the ACE-Step path."""
        ws, clip_id, src_wav = workspace_with_clip
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(app, ["extend", str(clip_id), "--duration", "1s"])
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
            result = runner.invoke(
                app,
                ["extend", str(clip_id), "--duration", "5s", "--backend", "elevenlabs"],
            )

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

        result = runner.invoke(app, ["extend", str(clip_id), "--duration", "5s"])

        assert result.exit_code == 1
        assert "not configured" in result.output
        assert "--backend elevenlabs" in result.output
