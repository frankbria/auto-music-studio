"""Tests for the full-song auto-extend CLI command (US-6.7)."""

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

TASK_ID = "task-fs-{}"
AUDIO_URL = "http://localhost:8001/v1/audio?path=section-{}.wav"
FAILED_RESULT = {"status": "failed", "audio_urls": [], "error": "model overloaded"}


def _wav_bytes(duration_s: float, sample_rate: int = 44100) -> bytes:
    buf = io.BytesIO()
    t = np.linspace(0, duration_s, int(sample_rate * duration_s), endpoint=False)
    mono = (0.3 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)
    stereo = np.column_stack([mono, mono])
    sf.write(buf, stereo, sample_rate, format="WAV")
    return buf.getvalue()


def _completed(url: str) -> dict:
    return {"status": "completed", "audio_urls": [url]}


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    import acemusic.db as _db

    monkeypatch.setattr(_db, "DB_DIR", tmp_path / ".acemusic")
    monkeypatch.setenv("ACEMUSIC_BASE_URL", "http://localhost:8001")
    return tmp_path


@pytest.fixture
def workspace_with_seed(isolated_db, write_tone):
    """Seed clip: 30s 'ambient' track in the active workspace."""
    from acemusic.db import create_clip
    from acemusic.workspace import ensure_default_workspace, get_active_workspace, get_workspace_path

    ensure_default_workspace()
    ws = get_active_workspace()
    clips_dir = get_workspace_path(ws.id)
    clips_dir.mkdir(parents=True, exist_ok=True)

    src_wav = clips_dir / "seed.wav"
    write_tone(src_wav, duration_s=30.0)

    clip = Clip(
        workspace_id=ws.id,
        file_path=str(src_wav),
        created_at=datetime.now(timezone.utc).isoformat(),
        title="Seed Song",
        format="wav",
        duration=30.0,
        bpm=120,
        key="C major",
        style_tags="ambient",
        generation_mode="generate",
    )
    clip_id = create_clip(clip)
    return ws, clip_id, src_wav


def _make_full_song_client(seed_duration: float, section_durations: list[float]) -> MagicMock:
    """Mock AceStepClient that returns audio whose duration grows by each section.

    Each call to submit_task gets a unique task id; download_audio returns a WAV
    whose length equals the cumulative duration after that section.
    """
    client = MagicMock()
    cumulative = seed_duration
    cumulative_durations = []
    for d in section_durations:
        cumulative += d
        cumulative_durations.append(cumulative)

    task_ids = [TASK_ID.format(i) for i in range(len(section_durations))]
    urls = [AUDIO_URL.format(i) for i in range(len(section_durations))]

    client.submit_task.side_effect = task_ids
    client.query_result.side_effect = [_completed(u) for u in urls]
    client.download_audio.side_effect = [_wav_bytes(d) for d in cumulative_durations]
    return client


class TestFullSongCommand:
    """Tests for `acemusic full-song`."""

    def test_auto_mode_generates_seven_sections(self, workspace_with_seed):
        ws, clip_id, _src = workspace_with_seed
        from acemusic.song_structure import plan_sections

        plan = plan_sections(seed_duration=30.0, target_duration=210)
        client = _make_full_song_client(30.0, [s.duration_s for s in plan])

        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(app, ["full-song", str(clip_id), "--auto"])

        assert result.exit_code == 0, result.output
        assert client.submit_task.call_count == 7

        from acemusic.db import list_clips

        clips = list_clips(ws.id)
        full_song_clips = [c for c in clips if c.generation_mode == "full-song"]
        assert len(full_song_clips) == 7

    def test_lineage_chains_seed_through_sections(self, workspace_with_seed):
        ws, clip_id, _src = workspace_with_seed
        from acemusic.song_structure import plan_sections

        plan = plan_sections(seed_duration=30.0, target_duration=210)
        client = _make_full_song_client(30.0, [s.duration_s for s in plan])

        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(app, ["full-song", str(clip_id), "--auto"])
        assert result.exit_code == 0, result.output

        from acemusic.db import list_clips

        sections = sorted(
            [c for c in list_clips(ws.id) if c.generation_mode == "full-song"],
            key=lambda c: c.id,
        )
        # First section parents the seed
        assert sections[0].parent_clip_id == clip_id
        # Subsequent sections parent the previous section (chained extends)
        for prev, curr in zip(sections, sections[1:]):
            assert curr.parent_clip_id == prev.id

    def test_each_section_passes_distinct_style_hint(self, workspace_with_seed):
        ws, clip_id, _src = workspace_with_seed
        from acemusic.song_structure import SONG_STRUCTURE, plan_sections

        plan = plan_sections(seed_duration=30.0, target_duration=210)
        client = _make_full_song_client(30.0, [s.duration_s for s in plan])

        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(app, ["full-song", str(clip_id), "--auto"])
        assert result.exit_code == 0, result.output

        # Each submit_task should carry a style mentioning the section name.
        for call, section_name in zip(client.submit_task.call_args_list, SONG_STRUCTURE):
            style_arg = call.kwargs.get("style") or ""
            assert (
                section_name in style_arg.lower()
            ), f"Expected style for section {section_name!r} to mention the section, got {style_arg!r}"

    def test_style_anchors_to_seed_not_previous_section(self, workspace_with_seed):
        """Each section's style references the seed style + its own hint only.

        Regression: previously the style was pulled from ``source.style_tags``
        (the most recently extended clip), so each section accumulated prior
        section hints (e.g. by section 4 the style read
        ``"ambient, intro..., verse..., chorus..."``). Later sections should
        only mention their own section hint, not earlier ones.
        """
        ws, clip_id, _src = workspace_with_seed
        from acemusic.song_structure import SONG_STRUCTURE, plan_sections

        plan = plan_sections(seed_duration=30.0, target_duration=210)
        client = _make_full_song_client(30.0, [s.duration_s for s in plan])

        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(app, ["full-song", str(clip_id), "--auto"])
        assert result.exit_code == 0, result.output

        # Section 4 is the second chorus; its style must not mention earlier sections.
        section_4_style = (client.submit_task.call_args_list[3].kwargs.get("style") or "").lower()
        for earlier in SONG_STRUCTURE[:3]:  # intro, verse, chorus(1)
            # Allow the section's own name if it repeats (chorus appears twice).
            if earlier == SONG_STRUCTURE[3]:
                continue
            assert (
                earlier not in section_4_style
            ), f"Section 4 style {section_4_style!r} unexpectedly contains earlier hint {earlier!r}"

    def test_final_clip_duration_approximates_target(self, workspace_with_seed):
        ws, clip_id, _src = workspace_with_seed
        from acemusic.song_structure import plan_sections

        target = 210
        plan = plan_sections(seed_duration=30.0, target_duration=target)
        client = _make_full_song_client(30.0, [s.duration_s for s in plan])

        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(app, ["full-song", str(clip_id), "--auto"])
        assert result.exit_code == 0, result.output

        from acemusic.db import list_clips

        sections = sorted(
            [c for c in list_clips(ws.id) if c.generation_mode == "full-song"],
            key=lambda c: c.id,
        )
        final = sections[-1]
        assert final.duration is not None
        # Final clip should be at least 80% of target duration
        assert final.duration >= target * 0.8

    def test_interactive_mode_prompts_between_sections(self, workspace_with_seed):
        ws, clip_id, _src = workspace_with_seed
        from acemusic.song_structure import plan_sections

        plan = plan_sections(seed_duration=30.0, target_duration=210)
        client = _make_full_song_client(30.0, [s.duration_s for s in plan])

        with (
            patch("acemusic.cli.AceStepClient", return_value=client),
            patch("acemusic.cli.typer.confirm", return_value=True) as mock_confirm,
        ):
            result = runner.invoke(app, ["full-song", str(clip_id)])

        assert result.exit_code == 0, result.output
        # 7 sections → 6 prompts between them (none after the last)
        assert mock_confirm.call_count == 6

    def test_interactive_n_exits_gracefully_after_partial_chain(self, workspace_with_seed):
        ws, clip_id, _src = workspace_with_seed
        from acemusic.song_structure import plan_sections

        plan = plan_sections(seed_duration=30.0, target_duration=210)
        # Only need audio for the sections that actually run (3 before user says no)
        client = _make_full_song_client(30.0, [s.duration_s for s in plan[:3]])

        # Say yes after sections 1 and 2, no after section 3
        with (
            patch("acemusic.cli.AceStepClient", return_value=client),
            patch("acemusic.cli.typer.confirm", side_effect=[True, True, False]),
        ):
            result = runner.invoke(app, ["full-song", str(clip_id)])

        assert result.exit_code == 0, result.output
        assert "partial" in result.output.lower() or "stopped" in result.output.lower()

        from acemusic.db import list_clips

        sections = [c for c in list_clips(ws.id) if c.generation_mode == "full-song"]
        assert len(sections) == 3

    def test_auto_mode_skips_all_confirmations(self, workspace_with_seed):
        ws, clip_id, _src = workspace_with_seed
        from acemusic.song_structure import plan_sections

        plan = plan_sections(seed_duration=30.0, target_duration=210)
        client = _make_full_song_client(30.0, [s.duration_s for s in plan])

        with (
            patch("acemusic.cli.AceStepClient", return_value=client),
            patch("acemusic.cli.typer.confirm") as mock_confirm,
        ):
            result = runner.invoke(app, ["full-song", str(clip_id), "--auto"])

        assert result.exit_code == 0, result.output
        mock_confirm.assert_not_called()

    def test_final_clip_title_marks_full_song(self, workspace_with_seed):
        ws, clip_id, _src = workspace_with_seed
        from acemusic.song_structure import plan_sections

        plan = plan_sections(seed_duration=30.0, target_duration=210)
        client = _make_full_song_client(30.0, [s.duration_s for s in plan])

        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(app, ["full-song", str(clip_id), "--auto"])
        assert result.exit_code == 0, result.output

        from acemusic.db import list_clips

        sections = sorted(
            [c for c in list_clips(ws.id) if c.generation_mode == "full-song"],
            key=lambda c: c.id,
        )
        assert sections[-1].title is not None
        assert "full song" in sections[-1].title.lower()


class TestFullSongValidation:
    """Input validation for the full-song command."""

    def test_seed_clip_not_found_errors(self, isolated_db):
        from acemusic.workspace import ensure_default_workspace

        ensure_default_workspace()
        result = runner.invoke(app, ["full-song", "99999", "--auto"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_missing_source_file_errors(self, isolated_db):
        from acemusic.db import create_clip
        from acemusic.workspace import ensure_default_workspace, get_active_workspace

        ensure_default_workspace()
        ws = get_active_workspace()
        clip = Clip(
            workspace_id=ws.id,
            file_path="/nonexistent/missing.wav",
            created_at=datetime.now(timezone.utc).isoformat(),
            format="wav",
            duration=30.0,
            generation_mode="generate",
        )
        clip_id = create_clip(clip)

        result = runner.invoke(app, ["full-song", str(clip_id), "--auto"])
        assert result.exit_code == 1

    def test_seed_longer_than_target_errors(self, workspace_with_seed):
        ws, clip_id, _src = workspace_with_seed
        # Seed is 30s; target 20s makes no sense
        result = runner.invoke(app, ["full-song", str(clip_id), "--target-duration", "20", "--auto"])
        assert result.exit_code == 1

    def test_seed_without_duration_errors(self, isolated_db, write_tone):
        from acemusic.db import create_clip
        from acemusic.workspace import ensure_default_workspace, get_active_workspace, get_workspace_path

        ensure_default_workspace()
        ws = get_active_workspace()
        clips_dir = get_workspace_path(ws.id)
        clips_dir.mkdir(parents=True, exist_ok=True)
        src_wav = clips_dir / "no-duration.wav"
        write_tone(src_wav, duration_s=10.0)

        clip = Clip(
            workspace_id=ws.id,
            file_path=str(src_wav),
            created_at=datetime.now(timezone.utc).isoformat(),
            format="wav",
            duration=None,  # missing duration metadata
            generation_mode="generate",
        )
        clip_id = create_clip(clip)
        result = runner.invoke(app, ["full-song", str(clip_id), "--auto"])
        assert result.exit_code == 1

    def test_generation_failure_mid_song_preserves_partial_chain(self, workspace_with_seed):
        ws, clip_id, _src = workspace_with_seed
        from acemusic.song_structure import plan_sections

        plan = plan_sections(seed_duration=30.0, target_duration=210)
        cumulative = 30.0
        good_results = []
        good_downloads = []
        for s in plan[:3]:
            cumulative += s.duration_s
            good_downloads.append(_wav_bytes(cumulative))
            good_results.append(_completed(AUDIO_URL.format(len(good_results))))

        client = MagicMock()
        client.submit_task.side_effect = [TASK_ID.format(i) for i in range(4)]
        # Sections 1-3 succeed; section 4 fails
        client.query_result.side_effect = good_results + [FAILED_RESULT]
        client.download_audio.side_effect = good_downloads

        with patch("acemusic.cli.AceStepClient", return_value=client):
            result = runner.invoke(app, ["full-song", str(clip_id), "--auto"])

        assert result.exit_code == 1
        assert "fail" in result.output.lower() or "error" in result.output.lower()

        from acemusic.db import list_clips

        sections = [c for c in list_clips(ws.id) if c.generation_mode == "full-song"]
        assert len(sections) == 3  # First three sections were committed before the failure
