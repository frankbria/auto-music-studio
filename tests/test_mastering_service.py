"""Tests for the mastering service layer (US-12.1).

The cost lookup and profile→LUFS resolution are pure functions and run in CI
(no DB); ``create_mastering_job`` is ``integration`` and drives a real MongoDB
via the ``mongo_db`` fixture, mirroring ``tests/test_clips_edit_api.py``.
"""

import pytest
from beanie import PydanticObjectId

from acemusic.api.models import Job, JobStatus
from acemusic.api.services import credits as credits_service, mastering as mastering_service

# ---------------------------------------------------------------------------
# Pure unit tests — credit costs (no DB)
# ---------------------------------------------------------------------------


class TestMasteringCost:
    @pytest.mark.parametrize(
        ("service", "expected"),
        [("dolby", 3.0), ("landr", 2.0), ("bakuage", 5.0)],
    )
    def test_known_services_map_to_costs(self, service: str, expected: float) -> None:
        assert credits_service.get_mastering_cost(service) == expected

    def test_costs_stay_within_documented_range(self) -> None:
        # The issue specifies "2-5 credits"; guard the band so a future tweak
        # cannot drift outside the contract silently.
        for service in ("dolby", "landr", "bakuage"):
            assert 2.0 <= credits_service.get_mastering_cost(service) <= 5.0

    def test_unknown_service_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            credits_service.get_mastering_cost("nope")


# ---------------------------------------------------------------------------
# Pure unit tests — profile → LUFS resolution (no DB)
# ---------------------------------------------------------------------------


class TestResolveTargetLufs:
    @pytest.mark.parametrize(
        ("profile", "expected"),
        [("streaming", -14.0), ("soundcloud", -12.0), ("club", -6.0), ("vinyl", -18.0)],
    )
    def test_standard_profiles_map_to_lufs(self, profile: str, expected: float) -> None:
        assert mastering_service.resolve_target_lufs(profile, None) == expected

    def test_standard_profile_ignores_custom_value(self) -> None:
        # A standard profile owns its target; a stray custom value must not win.
        assert mastering_service.resolve_target_lufs("streaming", -3.0) == -14.0

    def test_custom_profile_returns_supplied_value(self) -> None:
        assert mastering_service.resolve_target_lufs("custom", -9.5) == -9.5

    def test_custom_profile_without_value_raises(self) -> None:
        with pytest.raises(ValueError):
            mastering_service.resolve_target_lufs("custom", None)

    def test_unknown_profile_raises(self) -> None:
        with pytest.raises(ValueError):
            mastering_service.resolve_target_lufs("bogus", None)


# ---------------------------------------------------------------------------
# Integration — create_mastering_job persists + dispatches
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCreateMasteringJob:
    async def test_persists_queued_job_with_params(self, mongo_db) -> None:
        user_id = PydanticObjectId()
        workspace_id = PydanticObjectId()
        params = {
            "clip_id": str(PydanticObjectId()),
            "profile": "streaming",
            "service": "dolby",
            "format": "wav",
            "target_lufs": -14.0,
        }
        job = await mastering_service.create_mastering_job(user_id=user_id, workspace_id=workspace_id, params=params)

        stored = await Job.get(job.id)
        assert stored is not None
        assert stored.status is JobStatus.QUEUED
        assert stored.job_type == mastering_service.MASTERING_JOB_TYPE
        assert stored.user_id == user_id
        assert stored.workspace_id == workspace_id
        assert stored.input_params == params

    async def test_dispatch_failure_rolls_back_job(self, mongo_db, monkeypatch) -> None:
        async def _boom(_job_id: str) -> None:
            raise RuntimeError("dispatch down")

        monkeypatch.setattr(mastering_service, "dispatch_job", _boom)
        before = await Job.find_all().count()
        with pytest.raises(RuntimeError):
            await mastering_service.create_mastering_job(
                user_id=PydanticObjectId(),
                workspace_id=PydanticObjectId(),
                params={"clip_id": str(PydanticObjectId()), "profile": "streaming"},
            )
        # The orphan must be deleted so the processor never runs an un-acked job.
        assert await Job.find_all().count() == before
