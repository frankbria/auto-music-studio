"""Unit tests for the distribution status state machine (US-13.6, issue #137).

These cover the pure logic — transition validation, notification triggers, and
SoundCloud state mapping — with no database, so they run in CI.
"""

import pytest

from acemusic.api.models.distribution import DistributionStatus
from acemusic.api.services import distribution_status as svc


class TestValidateStatusTransition:
    @pytest.mark.parametrize(
        ("current", "target"),
        [
            (DistributionStatus.DRAFT, DistributionStatus.READY),
            (DistributionStatus.READY, DistributionStatus.SUBMITTED),
            (DistributionStatus.SUBMITTED, DistributionStatus.IN_REVIEW),
            (DistributionStatus.IN_REVIEW, DistributionStatus.LIVE),
            (DistributionStatus.IN_REVIEW, DistributionStatus.REJECTED),
        ],
    )
    def test_allows_sequential_steps(self, current, target) -> None:
        assert svc.validate_status_transition(current, target) is True

    @pytest.mark.parametrize(
        ("current", "target"),
        [
            (DistributionStatus.DRAFT, DistributionStatus.LIVE),  # the AC's headline case
            (DistributionStatus.DRAFT, DistributionStatus.SUBMITTED),
            (DistributionStatus.SUBMITTED, DistributionStatus.LIVE),
            (DistributionStatus.READY, DistributionStatus.IN_REVIEW),
            (DistributionStatus.LIVE, DistributionStatus.READY),  # terminal
            (DistributionStatus.REJECTED, DistributionStatus.READY),  # terminal
            (DistributionStatus.READY, DistributionStatus.READY),  # no self-loop
        ],
    )
    def test_rejects_skips_and_terminals(self, current, target) -> None:
        assert svc.validate_status_transition(current, target) is False


class TestShouldNotify:
    def test_terminal_transitions_notify(self) -> None:
        assert svc.should_notify(DistributionStatus.IN_REVIEW, DistributionStatus.LIVE) is True
        assert svc.should_notify(DistributionStatus.IN_REVIEW, DistributionStatus.REJECTED) is True

    def test_non_terminal_does_not_notify(self) -> None:
        assert svc.should_notify(DistributionStatus.SUBMITTED, DistributionStatus.IN_REVIEW) is False

    def test_no_notify_when_unchanged(self) -> None:
        assert svc.should_notify(DistributionStatus.LIVE, DistributionStatus.LIVE) is False


class TestMapSoundCloudState:
    @pytest.mark.parametrize(
        ("track", "expected"),
        [
            ({"state": "processing"}, DistributionStatus.IN_REVIEW),
            ({"state": "finished", "sharing": "public"}, DistributionStatus.LIVE),
            ({"state": "finished", "sharing": "private"}, DistributionStatus.IN_REVIEW),
            ({"state": "failed"}, DistributionStatus.REJECTED),
        ],
    )
    def test_maps_known_states(self, track, expected) -> None:
        assert svc.map_soundcloud_state(track) is expected

    @pytest.mark.parametrize("track", [{}, {"state": ""}, {"state": "weird"}])
    def test_unknown_state_is_none(self, track) -> None:
        assert svc.map_soundcloud_state(track) is None
