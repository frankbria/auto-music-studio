"""Tests for the song-structure planning module (US-6.7)."""

from __future__ import annotations

import pytest

from acemusic.song_structure import SECTION_CONFIG, SONG_STRUCTURE, plan_sections


class TestSongStructureConstants:
    def test_song_structure_is_intro_to_outro(self):
        assert SONG_STRUCTURE == [
            "intro",
            "verse",
            "chorus",
            "verse",
            "chorus",
            "bridge",
            "outro",
        ]

    def test_every_section_has_config(self):
        for section in set(SONG_STRUCTURE):
            assert section in SECTION_CONFIG, f"Missing SECTION_CONFIG entry for {section!r}"
            proportion, style_hint = SECTION_CONFIG[section]
            assert proportion > 0
            assert isinstance(style_hint, str) and style_hint.strip()


class TestPlanSections:
    def test_returns_seven_sections_in_canonical_order(self):
        sections = plan_sections(seed_duration=30.0, target_duration=210)
        assert [s.name for s in sections] == SONG_STRUCTURE

    def test_section_durations_sum_to_remaining_target(self):
        seed = 30.0
        target = 210
        sections = plan_sections(seed_duration=seed, target_duration=target)
        total = sum(s.duration_s for s in sections)
        # Sum should equal target - seed (within rounding tolerance)
        assert total == pytest.approx(target - seed, abs=0.5)

    def test_durations_scale_with_target(self):
        small = plan_sections(seed_duration=30.0, target_duration=120)
        big = plan_sections(seed_duration=30.0, target_duration=300)
        assert sum(s.duration_s for s in big) > sum(s.duration_s for s in small)

    def test_chorus_no_shorter_than_intro(self):
        """Choruses carry the hook; they should be at least as long as intros."""
        sections = plan_sections(seed_duration=30.0, target_duration=210)
        intro = next(s for s in sections if s.name == "intro")
        chorus = next(s for s in sections if s.name == "chorus")
        assert chorus.duration_s >= intro.duration_s

    def test_style_hint_present_for_each_section(self):
        sections = plan_sections(seed_duration=30.0, target_duration=210)
        for s in sections:
            assert s.style_hint.strip()

    def test_minimum_section_duration_enforced(self):
        """When target is very close to seed, every section still gets a positive duration."""
        sections = plan_sections(seed_duration=58.0, target_duration=60)
        for s in sections:
            assert s.duration_s > 0

    def test_plan_total_never_overshoots_target(self):
        """The summed section duration must not exceed (target - seed), even at tight margins.

        Regression: previously the MIN_SECTION_SECONDS floor was unconditional,
        so a 58s seed + 60s target produced 7 × 4s = 28s of sections, growing
        the song to 86s instead of 60s.
        """
        # Mix of cases where the proportional fallback kicks in (tight margins)
        # and cases where the MIN_SECTION_SECONDS floor is active (more headroom).
        for seed, target in [(58.0, 60), (50.0, 55), (10.0, 11), (30.0, 33), (30.0, 60), (60.0, 100)]:
            sections = plan_sections(seed_duration=seed, target_duration=target)
            total = sum(s.duration_s for s in sections)
            remaining = target - seed
            # Allow a tiny rounding tolerance.
            assert total <= remaining + 0.01, (
                f"plan_sections({seed=}, {target=}) summed to {total:.3f}s, " f"overshooting remaining={remaining:.3f}s"
            )

    def test_target_less_than_seed_raises(self):
        with pytest.raises(ValueError):
            plan_sections(seed_duration=120.0, target_duration=60)

    def test_negative_target_raises(self):
        with pytest.raises(ValueError):
            plan_sections(seed_duration=30.0, target_duration=-10)
