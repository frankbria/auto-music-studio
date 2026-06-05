"""Tests for the mashup CLI command (US-6.4)."""

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
from acemusic.client import AceStepError
from acemusic.models import Clip
from tests.helpers_elevenlabs import FAKE_EL_MP3, _el_config, _make_elevenlabs_client_mock

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
        assert mashups[0].title is not None
        assert "Clip One" in mashups[0].title
        assert "Clip Two" in mashups[0].title

    def test_bpm_alignment_invoked_when_bpms_differ(self, workspace_with_two_clips):
        """Acceptance criterion: BPM alignment is attempted when source tempos differ.

        Fixture state: clip1.bpm=120, clip2.bpm=100. Expected stretch rate is
        target_bpm / original_bpm = 120 / 100 = 1.2; ``time_stretch_audio`` is
        called positionally as (input_path, output_path, rate).
        """
        ws, clip1, clip2, _src1, _src2 = workspace_with_two_clips
        client = _make_client_mock()
        with (
            patch("acemusic.cli.AceStepClient", return_value=client),
            patch("acemusic.cli.time_stretch_audio") as stretch_mock,
        ):
            result = runner.invoke(app, ["mashup", str(clip1), str(clip2)])
        assert result.exit_code == 0, result.output
        stretch_mock.assert_called_once()
        call_kwargs = stretch_mock.call_args
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
        tags = {token.strip().lower() for token in (mashups[0].style_tags or "").split(",") if token.strip()}
        assert tags == {"ambient", "electronic", "dub"}

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

    def test_ace_step_records_parent_clip_ids(self, workspace_with_two_clips):
        """The ACE-Step mashup result records both sources in parent_clip_ids (#99)."""
        import json

        ws, clip1, clip2, _src1, _src2 = workspace_with_two_clips
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(app, ["mashup", str(clip1), str(clip2)])
        assert result.exit_code == 0, result.output

        from acemusic.db import list_clips

        mashups = [c for c in list_clips(ws.id) if c.generation_mode == "mashup"]
        assert json.loads(mashups[0].parent_clip_ids) == [clip1, clip2]

    def test_ace_step_three_clips_errors(self, workspace_with_three_long_clips):
        """The ACE-Step path supports exactly two clips and says so."""
        ws, ids, _paths = workspace_with_three_long_clips
        client = _make_client_mock()
        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(app, ["mashup", *[str(i) for i in ids]])
        assert result.exit_code == 1
        assert "exactly two" in result.output.lower()
        assert "--backend elevenlabs" in result.output
        client.submit_task.assert_not_called()


# ---------------------------------------------------------------------------
# ElevenLabs backend (#99)
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace_with_three_long_clips(isolated_db, write_tone):
    """Workspace + three source WAVs long enough for ElevenLabs sections (>=3s)."""
    from acemusic.db import create_clip
    from acemusic.workspace import ensure_default_workspace, get_active_workspace, get_workspace_path

    ensure_default_workspace()
    ws = get_active_workspace()
    clips_dir = get_workspace_path(ws.id)
    clips_dir.mkdir(parents=True, exist_ok=True)

    ids: list[int] = []
    paths: list[Path] = []
    for index, (duration_s, freq, title, tags) in enumerate(
        [(12.0, 440.0, "Track A", "ambient"), (8.0, 550.0, "Track B", "rock"), (6.0, 660.0, "Track C", "jazz")],
        start=1,
    ):
        src = clips_dir / f"long-{index}.wav"
        write_tone(src, duration_s=duration_s, frequency=freq)
        clip_id = create_clip(
            Clip(
                workspace_id=ws.id,
                file_path=str(src),
                created_at=datetime.now(timezone.utc).isoformat(),
                title=title,
                format="wav",
                duration=duration_s,
                style_tags=tags,
                model="acestep-v1",
                generation_mode="generate",
            )
        )
        ids.append(clip_id)
        paths.append(src)
    return ws, ids, paths


class TestMashupElevenLabsBackend:
    """Tests for `mashup --backend elevenlabs` (#99)."""

    def test_two_clips_create_mp3_with_full_lineage(self, workspace_with_three_long_clips, monkeypatch):
        """Happy path: one combined MP3 child clip recording all sources."""
        import json

        ws, ids, _paths = workspace_with_three_long_clips
        _el_config(monkeypatch)
        el = _make_elevenlabs_client_mock()

        with patch("acemusic.cli.ElevenLabsClient", return_value=el):
            result = runner.invoke(
                app,
                ["mashup", str(ids[0]), str(ids[1]), "--backend", "elevenlabs"],
            )

        assert result.exit_code == 0, result.output

        from acemusic.db import list_clips

        mashups = [c for c in list_clips(ws.id) if c.generation_mode == "mashup"]
        assert len(mashups) == 1
        child = mashups[0]
        assert child.model == "elevenlabs"
        assert child.format == "mp3"
        assert child.parent_clip_id == ids[0]
        assert json.loads(child.parent_clip_ids) == [ids[0], ids[1]]
        assert Path(child.file_path).read_bytes() == FAKE_EL_MP3

    def test_three_clips_uploaded_in_order(self, workspace_with_three_long_clips, monkeypatch):
        """Variadic sources: every clip is uploaded, plan references them in CLI order."""
        ws, ids, paths = workspace_with_three_long_clips
        _el_config(monkeypatch)
        el = _make_elevenlabs_client_mock()
        el.upload_for_inpainting.side_effect = ["song-1", "song-2", "song-3"]

        with patch("acemusic.cli.ElevenLabsClient", return_value=el):
            result = runner.invoke(
                app,
                ["mashup", *[str(i) for i in ids], "--backend", "elevenlabs"],
            )

        assert result.exit_code == 0, result.output
        uploaded = [str(c.args[0]) for c in el.upload_for_inpainting.call_args_list]
        assert uploaded == [str(p) for p in paths]

        plan = el.generate_from_plan.call_args.args[0]
        song_ids = [s["source_from"]["song_id"] for s in plan["sections"]]
        assert song_ids == ["song-1", "song-2", "song-3"]

    def test_style_lands_in_global_styles(self, workspace_with_three_long_clips, monkeypatch):
        ws, ids, _paths = workspace_with_three_long_clips
        _el_config(monkeypatch)
        el = _make_elevenlabs_client_mock()

        with patch("acemusic.cli.ElevenLabsClient", return_value=el):
            result = runner.invoke(
                app,
                ["mashup", str(ids[0]), str(ids[1]), "--style", "lo-fi hip hop", "--backend", "elevenlabs"],
            )

        assert result.exit_code == 0, result.output
        plan = el.generate_from_plan.call_args.args[0]
        assert "lo-fi hip hop" in plan["positive_global_styles"]

    def test_combined_too_long_fails_before_any_upload(self, workspace_with_three_long_clips, monkeypatch):
        """Sources whose metadata totals over 600s exit before spending a single upload."""
        ws, ids, _paths = workspace_with_three_long_clips
        _el_config(monkeypatch)
        el = _make_elevenlabs_client_mock()

        from acemusic.db import get_db

        with get_db() as conn:
            conn.execute("UPDATE clips SET duration = 400.0 WHERE id IN (?, ?)", (ids[0], ids[1]))

        with patch("acemusic.cli.ElevenLabsClient", return_value=el):
            result = runner.invoke(
                app,
                ["mashup", str(ids[0]), str(ids[1]), "--backend", "elevenlabs"],
            )

        assert result.exit_code == 1
        assert "600" in result.output
        el.upload_for_inpainting.assert_not_called()

    def test_too_short_source_fails_before_upload_naming_the_clip(self, workspace_with_three_long_clips, monkeypatch):
        """A source under 3s exits with the offending clip named, before any upload."""
        ws, ids, _paths = workspace_with_three_long_clips
        _el_config(monkeypatch)
        el = _make_elevenlabs_client_mock()

        from acemusic.db import get_db

        with get_db() as conn:
            conn.execute("UPDATE clips SET duration = 2.0 WHERE id = ?", (ids[1],))

        with patch("acemusic.cli.ElevenLabsClient", return_value=el):
            result = runner.invoke(
                app,
                ["mashup", str(ids[0]), str(ids[1]), "--backend", "elevenlabs"],
            )

        assert result.exit_code == 1
        assert f"clip {ids[1]}" in result.output
        el.upload_for_inpainting.assert_not_called()

    def test_upload_failure_names_the_failing_clip(self, workspace_with_three_long_clips, monkeypatch):
        """A mid-batch upload failure exits cleanly and names the clip that failed."""
        from acemusic.elevenlabs_client import ElevenLabsError

        ws, ids, _paths = workspace_with_three_long_clips
        _el_config(monkeypatch)
        el = _make_elevenlabs_client_mock()
        el.upload_for_inpainting.side_effect = [
            "song-1",
            ElevenLabsError("ElevenLabs upload failed: 403 — enterprise plan"),
        ]

        with patch("acemusic.cli.ElevenLabsClient", return_value=el):
            result = runner.invoke(
                app,
                ["mashup", str(ids[0]), str(ids[1]), "--backend", "elevenlabs"],
            )

        assert result.exit_code == 1
        assert f"clip {ids[1]}" in result.output
        assert "enterprise plan" in result.output

    def test_blend_is_ignored_with_warning(self, workspace_with_three_long_clips, monkeypatch):
        """--blend is ACE-Step-only; the elevenlabs path warns and proceeds."""
        ws, ids, _paths = workspace_with_three_long_clips
        _el_config(monkeypatch)
        el = _make_elevenlabs_client_mock()

        with patch("acemusic.cli.ElevenLabsClient", return_value=el):
            result = runner.invoke(
                app,
                ["mashup", str(ids[0]), str(ids[1]), "--blend", "sequential", "--backend", "elevenlabs"],
            )

        assert result.exit_code == 0, result.output
        assert "blend" in result.output.lower()
        assert "ignor" in result.output.lower()

    def test_missing_api_key_errors(self, workspace_with_three_long_clips, monkeypatch):
        ws, ids, _paths = workspace_with_three_long_clips
        _el_config(monkeypatch, api_key=None)

        result = runner.invoke(
            app,
            ["mashup", str(ids[0]), str(ids[1]), "--backend", "elevenlabs"],
        )

        assert result.exit_code == 1
        assert "elevenlabs_api_key" in result.output.lower()

    def test_works_without_ace_step_url(self, workspace_with_three_long_clips, monkeypatch):
        """--backend elevenlabs works in an ElevenLabs-only setup (no ACEMUSIC_BASE_URL)."""
        from acemusic.config import AceConfig

        ws, ids, _paths = workspace_with_three_long_clips
        monkeypatch.setattr(
            "acemusic.cli.load_config",
            lambda: AceConfig(api_url=None, api_key=None, elevenlabs_api_key="test-key"),
        )
        el = _make_elevenlabs_client_mock()

        with patch("acemusic.cli.ElevenLabsClient", return_value=el):
            result = runner.invoke(
                app,
                ["mashup", str(ids[0]), str(ids[1]), "--backend", "elevenlabs"],
            )

        assert result.exit_code == 0, result.output
        el.generate_from_plan.assert_called_once()

    def test_ace_step_path_without_url_suggests_elevenlabs(self, workspace_with_three_long_clips, monkeypatch):
        """The ACE-Step path still requires a URL and hints at --backend elevenlabs."""
        from acemusic.config import AceConfig

        ws, ids, _paths = workspace_with_three_long_clips
        monkeypatch.setattr(
            "acemusic.cli.load_config",
            lambda: AceConfig(api_url=None, api_key=None, elevenlabs_api_key="test-key"),
        )

        result = runner.invoke(app, ["mashup", str(ids[0]), str(ids[1])])

        assert result.exit_code == 1
        assert "not configured" in result.output
        assert "--backend elevenlabs" in result.output

    def test_invalid_backend_errors(self, workspace_with_three_long_clips, monkeypatch):
        ws, ids, _paths = workspace_with_three_long_clips
        _el_config(monkeypatch)

        result = runner.invoke(
            app,
            ["mashup", str(ids[0]), str(ids[1]), "--backend", "suno"],
        )

        assert result.exit_code == 1
        assert "Invalid backend" in result.output

    def test_single_clip_id_errors(self, workspace_with_three_long_clips, monkeypatch):
        """Fewer than two clip IDs is rejected up front."""
        ws, ids, _paths = workspace_with_three_long_clips
        _el_config(monkeypatch)

        result = runner.invoke(app, ["mashup", str(ids[0]), "--backend", "elevenlabs"])

        assert result.exit_code == 1
        assert "at least two" in result.output.lower()

    def test_compose_error_surfaces_as_friendly_message(self, workspace_with_three_long_clips, monkeypatch):
        """An ElevenLabsError during composition exits 1 with the error message."""
        from acemusic.elevenlabs_client import ElevenLabsError

        ws, ids, _paths = workspace_with_three_long_clips
        _el_config(monkeypatch)
        el = _make_elevenlabs_client_mock()
        el.generate_from_plan.side_effect = ElevenLabsError("ElevenLabs plan generation failed: 500")

        with patch("acemusic.cli.ElevenLabsClient", return_value=el):
            result = runner.invoke(
                app,
                ["mashup", str(ids[0]), str(ids[1]), "--backend", "elevenlabs"],
            )

        assert result.exit_code == 1
        assert "500" in result.output

    def test_write_failure_exits_cleanly(self, workspace_with_three_long_clips, monkeypatch):
        """A disk write failure exits 1 without a traceback."""
        ws, ids, _paths = workspace_with_three_long_clips
        _el_config(monkeypatch)
        el = _make_elevenlabs_client_mock()

        with (
            patch("acemusic.cli.ElevenLabsClient", return_value=el),
            patch("acemusic.cli.Path.write_bytes", side_effect=OSError("read-only file system")),
        ):
            result = runner.invoke(
                app,
                ["mashup", str(ids[0]), str(ids[1]), "--backend", "elevenlabs"],
            )

        assert result.exit_code == 1
        assert "read-only file system" in result.output

    def test_duration_probed_when_metadata_missing(self, workspace_with_three_long_clips, monkeypatch):
        """A source without duration metadata is probed from the file."""
        ws, ids, _paths = workspace_with_three_long_clips
        _el_config(monkeypatch)
        el = _make_elevenlabs_client_mock()

        from acemusic.db import get_db

        with get_db() as conn:
            conn.execute("UPDATE clips SET duration = NULL WHERE id = ?", (ids[0],))

        with patch("acemusic.cli.ElevenLabsClient", return_value=el):
            result = runner.invoke(
                app,
                ["mashup", str(ids[0]), str(ids[1]), "--backend", "elevenlabs"],
            )

        assert result.exit_code == 0, result.output
        plan = el.generate_from_plan.call_args.args[0]
        # Probed from the real 12s WAV on disk.
        assert plan["sections"][0]["duration_ms"] == pytest.approx(12_000, abs=100)
