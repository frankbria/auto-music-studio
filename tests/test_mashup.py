"""Tests for the mashup CLI command (US-6.4)."""

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

TASK_ID = "task-mashup-123"
AUDIO_URL = "http://localhost:8001/v1/audio?path=mashup.wav"
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
def workspace_with_two_clips(isolated_db, write_tone):
    """Set up a workspace with two source clips backed by real WAV files."""
    from acemusic.db import create_clip
    from acemusic.workspace import ensure_default_workspace, get_active_workspace, get_workspace_path

    ensure_default_workspace()
    ws = get_active_workspace()
    clips_dir = get_workspace_path(ws.id)
    clips_dir.mkdir(parents=True, exist_ok=True)

    src_one = clips_dir / "source-one.wav"
    src_two = clips_dir / "source-two.wav"
    write_tone(src_one, duration_s=2.0, frequency=440.0)
    write_tone(src_two, duration_s=2.0, frequency=660.0)

    clip_one = Clip(
        workspace_id=ws.id,
        file_path=str(src_one),
        created_at=datetime.now(timezone.utc).isoformat(),
        title="Clip One",
        format="wav",
        duration=2.0,
        bpm=120,
        key="C major",
        style_tags="ambient",
        generation_mode="generate",
    )
    clip_two = Clip(
        workspace_id=ws.id,
        file_path=str(src_two),
        created_at=datetime.now(timezone.utc).isoformat(),
        title="Clip Two",
        format="wav",
        duration=2.0,
        bpm=100,
        key="G major",
        style_tags="rock",
        generation_mode="generate",
    )
    clip_one_id = create_clip(clip_one)
    clip_two_id = create_clip(clip_two)
    return ws, clip_one_id, clip_two_id, src_one, src_two


def _make_client_mock(audio_bytes: bytes | None = None, query_sequence=None):
    if audio_bytes is None:
        audio_bytes = _wav_bytes(2.0)
    client = MagicMock()
    client.submit_task.return_value = TASK_ID
    client.query_result.side_effect = query_sequence or [COMPLETED_RESULT]
    client.download_audio.return_value = audio_bytes
    return client


class TestMashupCommand:
    """Tests for the `acemusic mashup` CLI command (US-6.4)."""

    def test_default_succeeds(self, workspace_with_two_clips):
        ws, clip1, clip2, _src1, _src2 = workspace_with_two_clips
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(app, ["mashup", str(clip1), str(clip2)])
        assert result.exit_code == 0, result.output

    def test_creates_single_new_clip_with_lineage(self, workspace_with_two_clips):
        """Acceptance criterion: mashup of two clips produces a single new clip."""
        ws, clip1, clip2, _src1, _src2 = workspace_with_two_clips
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(app, ["mashup", str(clip1), str(clip2)])
        assert result.exit_code == 0, result.output

        from acemusic.db import list_clips

        clips = list_clips(ws.id)
        mashups = [c for c in clips if c.generation_mode == "mashup"]
        assert len(mashups) == 1
        assert mashups[0].parent_clip_id == clip1

    def test_default_blend_is_layered(self, workspace_with_two_clips):
        ws, clip1, clip2, src1, src2 = workspace_with_two_clips
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(app, ["mashup", str(clip1), str(clip2)])
        assert result.exit_code == 0, result.output
        kwargs = client.submit_task.call_args.kwargs
        assert kwargs["task_type"] == "mashup"
        assert kwargs["blend_mode"] == "layered"
        assert kwargs["src_audio_path"] == str(src1.resolve())
        # ref_audio_path may point to an aligned temp file when BPMs differ
        assert kwargs["ref_audio_path"]

    def test_blend_layered(self, workspace_with_two_clips):
        ws, clip1, clip2, _src1, _src2 = workspace_with_two_clips
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(app, ["mashup", str(clip1), str(clip2), "--blend", "layered"])
        assert result.exit_code == 0, result.output
        assert client.submit_task.call_args.kwargs["blend_mode"] == "layered"

    def test_blend_sequential(self, workspace_with_two_clips):
        ws, clip1, clip2, _src1, _src2 = workspace_with_two_clips
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(app, ["mashup", str(clip1), str(clip2), "--blend", "sequential"])
        assert result.exit_code == 0, result.output
        assert client.submit_task.call_args.kwargs["blend_mode"] == "sequential"

    def test_blend_ai_guided(self, workspace_with_two_clips):
        ws, clip1, clip2, _src1, _src2 = workspace_with_two_clips
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(app, ["mashup", str(clip1), str(clip2), "--blend", "ai-guided"])
        assert result.exit_code == 0, result.output
        assert client.submit_task.call_args.kwargs["blend_mode"] == "ai-guided"

    def test_invalid_blend_mode_exits_one(self, workspace_with_two_clips):
        ws, clip1, clip2, _src1, _src2 = workspace_with_two_clips
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(app, ["mashup", str(clip1), str(clip2), "--blend", "bogus"])
        assert result.exit_code != 0
        # submit_task should not be reached when blend mode is invalid
        client.submit_task.assert_not_called()

    def test_style_option_forwarded(self, workspace_with_two_clips):
        ws, clip1, clip2, _src1, _src2 = workspace_with_two_clips
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(app, ["mashup", str(clip1), str(clip2), "--style", "lo-fi hip hop"])
        assert result.exit_code == 0, result.output
        kwargs = client.submit_task.call_args.kwargs
        assert kwargs["style"] == "lo-fi hip hop"

    def test_missing_clip1_exits_one(self, isolated_db):
        from acemusic.workspace import ensure_default_workspace

        ensure_default_workspace()
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(app, ["mashup", "999", "1000"])
        assert result.exit_code == 1
        assert "999" in result.output
        client.submit_task.assert_not_called()

    def test_missing_clip2_exits_one(self, workspace_with_two_clips):
        ws, clip1, _clip2, _src1, _src2 = workspace_with_two_clips
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(app, ["mashup", str(clip1), "9999"])
        assert result.exit_code == 1
        assert "9999" in result.output
        client.submit_task.assert_not_called()

    def test_missing_source_file_exits_one(self, workspace_with_two_clips):
        ws, clip1, clip2, src1, _src2 = workspace_with_two_clips
        src1.unlink()
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(app, ["mashup", str(clip1), str(clip2)])
        assert result.exit_code == 1
        client.submit_task.assert_not_called()

    def test_api_failure_exits_one(self, workspace_with_two_clips):
        ws, clip1, clip2, _src1, _src2 = workspace_with_two_clips
        client = _make_client_mock(query_sequence=[FAILED_RESULT])
        with patch("acemusic.cli.AceStepClient", return_value=client), patch("acemusic.cli.time.sleep"):
            result = runner.invoke(app, ["mashup", str(clip1), str(clip2)])
        assert result.exit_code == 1
        assert "failed" in result.output.lower()

    def test_submit_error_exits_one(self, workspace_with_two_clips):
        ws, clip1, clip2, _src1, _src2 = workspace_with_two_clips
        client = _make_client_mock()
        client.submit_task.side_effect = AceStepError("connection refused")
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(app, ["mashup", str(clip1), str(clip2)])
        assert result.exit_code == 1
        assert "connection refused" in result.output

    def test_polls_until_complete(self, workspace_with_two_clips):
        ws, clip1, clip2, _src1, _src2 = workspace_with_two_clips
        client = _make_client_mock(query_sequence=[PENDING_RESULT, PENDING_RESULT, COMPLETED_RESULT])
        with patch("acemusic.cli.AceStepClient", return_value=client), patch("acemusic.cli.time.sleep"):
            result = runner.invoke(app, ["mashup", str(clip1), str(clip2)])
        assert result.exit_code == 0, result.output
        assert client.query_result.call_count == 3

    def test_output_directory_overrides_default(self, workspace_with_two_clips, tmp_path):
        ws, clip1, clip2, _src1, _src2 = workspace_with_two_clips
        custom_dir = tmp_path / "custom-mashup-out"
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(app, ["mashup", str(clip1), str(clip2), "--output", str(custom_dir)])
        assert result.exit_code == 0, result.output
        assert custom_dir.exists()
        produced = list(custom_dir.glob("*.wav"))
        assert len(produced) == 1

    def test_name_option_sets_filename_and_title(self, workspace_with_two_clips):
        ws, clip1, clip2, _src1, _src2 = workspace_with_two_clips
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(app, ["mashup", str(clip1), str(clip2), "--name", "My Hybrid Track"])
        assert result.exit_code == 0, result.output

        from acemusic.db import list_clips

        mashups = [c for c in list_clips(ws.id) if c.generation_mode == "mashup"]
        assert len(mashups) == 1
        assert mashups[0].title == "My Hybrid Track"
        assert "my-hybrid-track" in mashups[0].file_path.lower()

    def test_default_title_combines_sources(self, workspace_with_two_clips):
        ws, clip1, clip2, _src1, _src2 = workspace_with_two_clips
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(app, ["mashup", str(clip1), str(clip2)])
        assert result.exit_code == 0, result.output

        from acemusic.db import list_clips

        mashups = [c for c in list_clips(ws.id) if c.generation_mode == "mashup"]
        # Default title should mention both source titles when available
        assert mashups[0].title is not None
        assert "Clip One" in mashups[0].title
        assert "Clip Two" in mashups[0].title

    def test_bpm_alignment_invoked_when_bpms_differ(self, workspace_with_two_clips):
        """Acceptance criterion: BPM/key alignment is attempted (clips at different tempos)."""
        ws, clip1, clip2, _src1, _src2 = workspace_with_two_clips
        # The fixture sets clip1.bpm=120 and clip2.bpm=100, so alignment should occur.
        client = _make_client_mock()
        with (
            patch("acemusic.cli.AceStepClient", return_value=client),
            patch("acemusic.cli.time_stretch_audio") as stretch_mock,
        ):
            result = runner.invoke(app, ["mashup", str(clip1), str(clip2)])
        assert result.exit_code == 0, result.output
        # time_stretch_audio is invoked to align clip2's BPM to clip1's BPM
        stretch_mock.assert_called_once()
        call_kwargs = stretch_mock.call_args
        # rate = target_bpm / original_bpm = 120 / 100 = 1.2
        # Positional arg layout: (input_path, output_path, rate) — check the rate.
        args, kwargs = call_kwargs.args, call_kwargs.kwargs
        rate = kwargs.get("rate", args[2] if len(args) >= 3 else None)
        assert rate is not None
        assert abs(rate - 1.2) < 0.01

    def test_no_alignment_when_bpms_match(self, isolated_db, write_tone):
        from acemusic.db import create_clip
        from acemusic.workspace import ensure_default_workspace, get_active_workspace, get_workspace_path

        ensure_default_workspace()
        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        clips_dir.mkdir(parents=True, exist_ok=True)

        src_a = clips_dir / "a.wav"
        src_b = clips_dir / "b.wav"
        write_tone(src_a, duration_s=2.0)
        write_tone(src_b, duration_s=2.0)

        c_a = create_clip(
            Clip(
                workspace_id=ws.id,
                file_path=str(src_a),
                created_at=datetime.now(timezone.utc).isoformat(),
                format="wav",
                duration=2.0,
                bpm=120,
                generation_mode="generate",
            )
        )
        c_b = create_clip(
            Clip(
                workspace_id=ws.id,
                file_path=str(src_b),
                created_at=datetime.now(timezone.utc).isoformat(),
                format="wav",
                duration=2.0,
                bpm=120,
                generation_mode="generate",
            )
        )

        client = _make_client_mock()
        with (
            patch("acemusic.cli.AceStepClient", return_value=client),
            patch("acemusic.cli.time_stretch_audio") as stretch_mock,
        ):
            result = runner.invoke(app, ["mashup", str(c_a), str(c_b)])
        assert result.exit_code == 0, result.output
        stretch_mock.assert_not_called()
        # Ref audio path remains the original clip2 path
        kwargs = client.submit_task.call_args.kwargs
        assert kwargs["ref_audio_path"] == str(src_b.resolve())

    def test_unsupported_format_exits_one(self, isolated_db, tmp_path):
        from acemusic.db import create_clip
        from acemusic.workspace import ensure_default_workspace, get_active_workspace, get_workspace_path

        ensure_default_workspace()
        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        clips_dir.mkdir(parents=True, exist_ok=True)

        bad = clips_dir / "notes.txt"
        bad.write_text("not audio")
        good = clips_dir / "good.wav"
        good.write_bytes(_wav_bytes(1.0))

        c_bad = create_clip(
            Clip(
                workspace_id=ws.id,
                file_path=str(bad),
                created_at=datetime.now(timezone.utc).isoformat(),
                format="txt",
                duration=None,
                generation_mode="generate",
            )
        )
        c_good = create_clip(
            Clip(
                workspace_id=ws.id,
                file_path=str(good),
                created_at=datetime.now(timezone.utc).isoformat(),
                format="wav",
                duration=1.0,
                generation_mode="generate",
            )
        )

        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(app, ["mashup", str(c_bad), str(c_good)])
        assert result.exit_code == 1
        client.submit_task.assert_not_called()

    def test_identical_clip_ids_rejected(self, workspace_with_two_clips):
        ws, clip1, _clip2, _src1, _src2 = workspace_with_two_clips
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(app, ["mashup", str(clip1), str(clip1)])
        assert result.exit_code == 1
        assert "different" in result.output.lower()
        client.submit_task.assert_not_called()

    def test_zero_or_negative_bpm_skips_alignment(self, isolated_db, write_tone):
        from acemusic.db import create_clip
        from acemusic.workspace import (
            ensure_default_workspace,
            get_active_workspace,
            get_workspace_path,
        )

        ensure_default_workspace()
        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        clips_dir.mkdir(parents=True, exist_ok=True)

        src_a = clips_dir / "zero.wav"
        src_b = clips_dir / "negative.wav"
        write_tone(src_a, duration_s=1.0)
        write_tone(src_b, duration_s=1.0)

        c_a = create_clip(
            Clip(
                workspace_id=ws.id,
                file_path=str(src_a),
                created_at=datetime.now(timezone.utc).isoformat(),
                format="wav",
                duration=1.0,
                bpm=0,
                generation_mode="generate",
            )
        )
        c_b = create_clip(
            Clip(
                workspace_id=ws.id,
                file_path=str(src_b),
                created_at=datetime.now(timezone.utc).isoformat(),
                format="wav",
                duration=1.0,
                bpm=120,
                generation_mode="generate",
            )
        )

        client = _make_client_mock()
        with (
            patch("acemusic.cli.AceStepClient", return_value=client),
            patch("acemusic.cli.time_stretch_audio") as stretch_mock,
        ):
            result = runner.invoke(app, ["mashup", str(c_a), str(c_b)])
        assert result.exit_code == 0, result.output
        stretch_mock.assert_not_called()
        kwargs = client.submit_task.call_args.kwargs
        assert kwargs["ref_audio_path"] == str(src_b.resolve())

    def test_style_option_persisted_to_style_tags(self, workspace_with_two_clips):
        """The --style value is recorded in the merged style_tags column.

        Note: --blend is currently surfaced in console output and threaded to the
        API request, but is not persisted to a dedicated DB column; that can be
        added when the clips table grows a blend_mode field.
        """
        ws, clip1, clip2, _src1, _src2 = workspace_with_two_clips
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(app, ["mashup", str(clip1), str(clip2), "--blend", "sequential", "--style", "jazz"])
        assert result.exit_code == 0, result.output

        from acemusic.db import list_clips

        mashups = [c for c in list_clips(ws.id) if c.generation_mode == "mashup"]
        assert mashups[0].style_tags is not None
        assert "jazz" in mashups[0].style_tags

    def test_style_tags_dedup_across_sources(self, isolated_db, write_tone):
        """When both source clips share a tag, merged style_tags deduplicates it."""
        from acemusic.db import create_clip
        from acemusic.workspace import (
            ensure_default_workspace,
            get_active_workspace,
            get_workspace_path,
        )

        ensure_default_workspace()
        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        clips_dir.mkdir(parents=True, exist_ok=True)

        src_a = clips_dir / "a.wav"
        src_b = clips_dir / "b.wav"
        write_tone(src_a, duration_s=1.0)
        write_tone(src_b, duration_s=1.0)

        c_a = create_clip(
            Clip(
                workspace_id=ws.id,
                file_path=str(src_a),
                created_at=datetime.now(timezone.utc).isoformat(),
                format="wav",
                duration=1.0,
                bpm=120,
                style_tags="ambient, electronic",
                generation_mode="generate",
            )
        )
        c_b = create_clip(
            Clip(
                workspace_id=ws.id,
                file_path=str(src_b),
                created_at=datetime.now(timezone.utc).isoformat(),
                format="wav",
                duration=1.0,
                bpm=120,
                style_tags="ambient, dub",
                generation_mode="generate",
            )
        )

        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(app, ["mashup", str(c_a), str(c_b)])
        assert result.exit_code == 0, result.output

        from acemusic.db import list_clips

        mashups = [c for c in list_clips(ws.id) if c.generation_mode == "mashup"]
        tags = mashups[0].style_tags or ""
        # "ambient" appears in both sources but should only be listed once
        assert tags.lower().count("ambient") == 1
        assert "electronic" in tags
        assert "dub" in tags

    def test_key_mismatch_warns_and_omits_key(self, workspace_with_two_clips):
        """When clip keys differ, the user is warned and submit_task is called with key=None.

        The fixture sets clip1.key='C major' and clip2.key='G major', so the
        mismatch path is exercised on every default invocation against this fixture.
        """
        ws, clip1, clip2, _src1, _src2 = workspace_with_two_clips
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(app, ["mashup", str(clip1), str(clip2)])
        assert result.exit_code == 0, result.output
        assert "Key mismatch" in result.output
        assert "C major" in result.output
        assert "G major" in result.output
        kwargs = client.submit_task.call_args.kwargs
        assert kwargs["key"] is None

        from acemusic.db import list_clips

        mashups = [c for c in list_clips(ws.id) if c.generation_mode == "mashup"]
        # The recorded clip key is None when sources disagreed
        assert mashups[0].key is None

    def test_matching_keys_pass_through(self, isolated_db, write_tone):
        """When both clips share a key, no warning and the key is forwarded to submit_task."""
        from acemusic.db import create_clip
        from acemusic.workspace import (
            ensure_default_workspace,
            get_active_workspace,
            get_workspace_path,
        )

        ensure_default_workspace()
        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        clips_dir.mkdir(parents=True, exist_ok=True)

        src_a = clips_dir / "a.wav"
        src_b = clips_dir / "b.wav"
        write_tone(src_a, duration_s=1.0)
        write_tone(src_b, duration_s=1.0)

        c_a = create_clip(
            Clip(
                workspace_id=ws.id,
                file_path=str(src_a),
                created_at=datetime.now(timezone.utc).isoformat(),
                format="wav",
                duration=1.0,
                bpm=120,
                key="C major",
                generation_mode="generate",
            )
        )
        c_b = create_clip(
            Clip(
                workspace_id=ws.id,
                file_path=str(src_b),
                created_at=datetime.now(timezone.utc).isoformat(),
                format="wav",
                duration=1.0,
                bpm=120,
                key="C major",
                generation_mode="generate",
            )
        )

        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(app, ["mashup", str(c_a), str(c_b)])
        assert result.exit_code == 0, result.output
        assert "Key mismatch" not in result.output
        assert client.submit_task.call_args.kwargs["key"] == "C major"

    def test_bpm_alignment_failure_falls_back_to_original(self, workspace_with_two_clips):
        """When time_stretch_audio raises, the command still succeeds using the original clip."""
        ws, clip1, clip2, _src1, src2 = workspace_with_two_clips
        client = _make_client_mock()
        with (
            patch("acemusic.cli.AceStepClient", return_value=client),
            patch("acemusic.cli.time_stretch_audio", side_effect=RuntimeError("librosa exploded")),
        ):
            result = runner.invoke(app, ["mashup", str(clip1), str(clip2)])
        assert result.exit_code == 0, result.output
        # Fallback: ref_audio_path is the original secondary clip, not an aligned temp file
        kwargs = client.submit_task.call_args.kwargs
        assert kwargs["ref_audio_path"] == str(src2.resolve())
