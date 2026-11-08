"""Per-channel details the SoundCloud poller records next to a status (#758)."""

from acemusic.api.models.distribution import DistributionStatus
from acemusic.api.services.distribution_status import soundcloud_details


def test_a_live_track_contributes_its_public_link() -> None:
    track = {"permalink_url": "https://soundcloud.com/dj/tune"}
    assert soundcloud_details(track, DistributionStatus.LIVE) == {
        "channel_permalinks.soundcloud": "https://soundcloud.com/dj/tune"
    }


def test_a_link_that_is_not_http_is_never_stored() -> None:
    assert soundcloud_details({"permalink_url": "javascript:alert(1)"}, DistributionStatus.LIVE) == {}


def test_a_track_still_in_review_contributes_nothing() -> None:
    assert soundcloud_details({"permalink_url": "https://soundcloud.com/dj/tune"}, DistributionStatus.IN_REVIEW) == {}


def test_a_failed_track_contributes_a_reason() -> None:
    details = soundcloud_details({}, DistributionStatus.REJECTED)
    assert details["channel_rejection_reasons.soundcloud"].startswith("SoundCloud")
