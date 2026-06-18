"""Tests for the mastering job handler (US-12.2 + US-12.3, issue #128/#129).

Exercise ``acemusic.api.tasks.mastering.process_mastering_job`` directly with a
fake mastering orchestrator (built from in-process ``FakeService`` stubs) and a
local on-disk storage backend: the handler downloads the source clip, hands it
to the orchestrator which runs the requested backend (and falls back on
failure), downloads the mastered output and stores it as a lineage-tagged child
clip. They assert the worker contract — lineage + metrics + the service that
actually ran, graceful degradation without credentials, fallback from Dolby to
Bakuage, refund-on-rejection, per-stage error handling — that the live Dolby /
LANDR / Bakuage integration tests cannot cheaply cover.

The ``get_mastering_orchestrator`` factory tests run in CI (no DB). The handler
tests need a local MongoDB (Beanie) and are marked ``integration``.
"""

from __future__ import annotations

import io

import numpy as np
import pytest
import soundfile as sf
from beanie import PydanticObjectId

from acemusic.api.models import Clip, Job, JobStatus, Workspace
from acemusic.api.services import users as user_service
from acemusic.api.services.mastering import MASTERING_JOB_TYPE
from acemusic.api.settings import ApiSettings
from acemusic.api.tasks import mastering as tasks
from acemusic.mastering_orchestrator import MasteringOrchestrator
from acemusic.mastering_protocol import MasteringError, MasteringOutput
from acemusic.storage import LocalStorage

SR = 44100


def _wav_bytes(duration_s: float = 3.0, freq: float = 440.0) -> bytes:
    t = np.linspace(0, duration_s, int(SR * duration_s), endpoint=False)
    mono = (0.3 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    stereo = np.column_stack([mono, mono])
    buf = io.BytesIO()
    sf.write(buf, stereo, SR, format="WAV")
    return buf.getvalue()


_METRICS = {"loudness": -14.0, "eq_bands": [float(i) for i in range(16)], "stereo": {"width": 0.8, "balance": 0.0}}


class FakeService:
    """A MasteringService stub: returns canned output, or raises on master()."""

    def __init__(self, *, service: str, output: bytes, metrics: dict | None = None, fail: bool = False) -> None:
        self.service = service
        self._output = output
        self._metrics = metrics if metrics is not None else _METRICS
        self._fail = fail
        self.master_calls: list[dict] = []

    def master(
        self, audio_bytes: bytes, filename: str, profile: str, target_lufs: float, output_format: str
    ) -> MasteringOutput:
        self.master_calls.append(
            {
                "audio_bytes": audio_bytes,
                "filename": filename,
                "profile": profile,
                "target_lufs": target_lufs,
                "output_format": output_format,
            }
        )
        if self._fail:
            raise MasteringError(f"{self.service} unavailable")
        return MasteringOutput(audio_bytes=self._output, metrics=dict(self._metrics), service=self.service)


def _orchestrator(**services: FakeService) -> MasteringOrchestrator:
    """Build an orchestrator from the given FakeService stubs keyed by service name."""
    return MasteringOrchestrator(dict(services))


# ---------------------------------------------------------------------------
# get_mastering_orchestrator factory (CI — no DB)
# ---------------------------------------------------------------------------


class TestGetMasteringOrchestrator:
    def test_no_credentials_yields_empty_orchestrator(self) -> None:
        settings = ApiSettings(_env_file=None)
        orch = tasks.get_mastering_orchestrator(settings)
        assert orch.available_services == ()

    def test_dolby_only(self) -> None:
        settings = ApiSettings(_env_file=None, dolby_api_key="k", dolby_api_secret="s")
        orch = tasks.get_mastering_orchestrator(settings)
        assert orch.available_services == ("dolby",)

    def test_all_three_backends_wired(self) -> None:
        settings = ApiSettings(
            _env_file=None,
            dolby_api_key="dk",
            dolby_api_secret="ds",
            landr_api_key="lk",
            landr_api_secret="ls",
            bakuage_api_key="bk",
        )
        orch = tasks.get_mastering_orchestrator(settings)
        assert orch.available_services == ("dolby", "landr", "bakuage")


# ---------------------------------------------------------------------------
# Handler — integration (local MongoDB)
# ---------------------------------------------------------------------------


@pytest.fixture
def storage(mongo_db, tmp_path) -> LocalStorage:
    # ``mongo_db`` initialises Beanie so the handler can read/insert documents.
    return LocalStorage(tmp_path / "storage")


async def _make_clip(
    storage: LocalStorage,
    *,
    email: str,
    duration: float = 3.0,
    bpm: int | None = 120,
    key: str | None = "C",
    service: str = "dolby",
) -> tuple[Job, Clip]:
    user = await user_service.get_or_create_user(email=email, provider="google", oauth_id=f"g-{email}", name="T")
    workspace = Workspace(name="WS", user_id=user.id)
    await workspace.insert()
    clip_id = PydanticObjectId()
    file_path = f"{user.id}/{workspace.id}/clips/{clip_id}.wav"
    storage.upload(file_path, _wav_bytes(duration))
    clip = Clip(
        id=clip_id,
        user_id=user.id,
        workspace_id=workspace.id,
        file_path=file_path,
        format="wav",
        duration=duration,
        bpm=bpm,
        key=key,
        style_tags=["lofi"],
    )
    await clip.insert()
    job = Job(
        user_id=user.id,
        workspace_id=workspace.id,
        job_type=MASTERING_JOB_TYPE,
        input_params={
            "clip_id": str(clip.id),
            "profile": "streaming",
            "service": service,
            "format": "wav",
            "target_lufs": -14.0,
        },
        status=JobStatus.QUEUED,
    )
    return job, clip


pytestmark = pytest.mark.integration


class TestSuccess:
    async def test_dolby_creates_master_clip_with_lineage_and_metrics(self, storage) -> None:
        job, source = await _make_clip(storage, email="master-ok@example.com")
        dolby = FakeService(service="dolby", output=_wav_bytes(3.0))
        orch = _orchestrator(dolby=dolby)

        result = await tasks.process_mastering_job(job, storage=storage, orchestrator=orch)

        assert result["clip_ids"]  # one clip stored
        assert result["service"] == "dolby"
        assert result["target_lufs"] == -14.0
        assert result["metrics"] == _METRICS
        child = await Clip.get(PydanticObjectId(result["clip_ids"][0]))
        assert child is not None
        assert child.parent_clip_ids == [source.id]
        assert child.generation_mode == MASTERING_JOB_TYPE
        assert child.duration == source.duration
        assert child.bpm == source.bpm
        # The mastered audio is retrievable from storage.
        assert storage.download(child.file_path)

    async def test_landr_creates_master_clip(self, storage) -> None:
        # AC1: LANDR mastering produces a mastered audio file.
        job, source = await _make_clip(storage, email="master-landr@example.com", service="landr")
        landr = FakeService(
            service="landr", output=_wav_bytes(3.0), metrics={"loudness": -14.2, "eq_bands": [], "stereo": {}}
        )
        orch = _orchestrator(landr=landr)

        result = await tasks.process_mastering_job(job, storage=storage, orchestrator=orch)

        assert result["service"] == "landr"
        assert result["metrics"]["loudness"] == -14.2
        child = await Clip.get(PydanticObjectId(result["clip_ids"][0]))
        assert child is not None
        assert child.parent_clip_ids == [source.id]
        assert storage.download(child.file_path)

    async def test_bakuage_creates_master_clip(self, storage) -> None:
        # AC2: Bakuage mastering produces a mastered audio file.
        job, source = await _make_clip(storage, email="master-bakuage@example.com", service="bakuage")
        bakuage = FakeService(
            service="bakuage", output=_wav_bytes(3.0), metrics={"loudness": -9.0, "eq_bands": [], "stereo": {}}
        )
        orch = _orchestrator(bakuage=bakuage)

        result = await tasks.process_mastering_job(job, storage=storage, orchestrator=orch)

        assert result["service"] == "bakuage"
        child = await Clip.get(PydanticObjectId(result["clip_ids"][0]))
        assert child is not None
        assert child.parent_clip_ids == [source.id]

    async def test_upload_keyed_by_job_id(self, storage) -> None:
        # The upload filename carries the job id so concurrent masters on the same
        # clip never collide on the backend's input keys.
        job, source = await _make_clip(storage, email="master-keys@example.com")
        dolby = FakeService(service="dolby", output=_wav_bytes(3.0))
        await tasks.process_mastering_job(job, storage=storage, orchestrator=_orchestrator(dolby=dolby))
        filename = dolby.master_calls[0]["filename"]
        assert str(job.id) in filename
        assert str(source.id) in filename


class TestFallback:
    async def test_dolby_failure_falls_back_to_bakuage(self, storage) -> None:
        # AC3: when Dolby.io returns an error, the job falls back to Bakuage.
        job, source = await _make_clip(storage, email="master-fb@example.com", service="dolby")
        dolby = FakeService(service="dolby", output=_wav_bytes(3.0), fail=True)
        bakuage = FakeService(service="bakuage", output=_wav_bytes(3.0))
        orch = _orchestrator(dolby=dolby, bakuage=bakuage)

        result = await tasks.process_mastering_job(job, storage=storage, orchestrator=orch)

        # The fallback backend ran and its service is attributed in the result.
        assert result["service"] == "bakuage"
        assert dolby.master_calls and dolby.master_calls[0]  # primary was attempted
        assert bakuage.master_calls  # fallback was attempted
        child = await Clip.get(PydanticObjectId(result["clip_ids"][0]))
        assert child is not None
        assert child.parent_clip_ids == [source.id]
        assert storage.download(child.file_path)

    async def test_all_backends_fail_raises(self, storage) -> None:
        job, _ = await _make_clip(storage, email="master-allfail@example.com", service="dolby")
        dolby = FakeService(service="dolby", output=_wav_bytes(3.0), fail=True)
        bakuage = FakeService(service="bakuage", output=_wav_bytes(3.0), fail=True)
        orch = _orchestrator(dolby=dolby, bakuage=bakuage)

        with pytest.raises(tasks.JobProcessingError, match="Mastering failed"):
            await tasks.process_mastering_job(job, storage=storage, orchestrator=orch)


class TestGracefulDegradation:
    async def test_requested_service_unconfigured_refunds_and_raises(self, storage) -> None:
        # Explicitly requesting landr on a dolby-only deployment: clear error +
        # refund (no silent substitution, no work performed).
        from acemusic.api.services import credits as credits_service

        job, _ = await _make_clip(storage, email="master-unconfigured@example.com", service="landr")
        dolby = FakeService(service="dolby", output=_wav_bytes(3.0))
        orch = _orchestrator(dolby=dolby)
        cost = credits_service.get_mastering_cost("landr")
        before = await credits_service.deduct_credits(job.user_id, cost)

        with pytest.raises(tasks.JobProcessingError, match="not configured"):
            await tasks.process_mastering_job(job, storage=storage, orchestrator=orch)

        user = await user_service.get_user_by_id(str(job.user_id))
        assert user.credits_balance == before + cost

    async def test_no_backends_at_all_refunds_and_raises(self, storage) -> None:
        from acemusic.api.services import credits as credits_service

        job, _ = await _make_clip(storage, email="master-nobackend@example.com", service="dolby")
        orch = _orchestrator()  # empty
        cost = credits_service.get_mastering_cost("dolby")
        before = await credits_service.deduct_credits(job.user_id, cost)

        with pytest.raises(tasks.JobProcessingError, match="not configured"):
            await tasks.process_mastering_job(job, storage=storage, orchestrator=orch)

        user = await user_service.get_user_by_id(str(job.user_id))
        assert user.credits_balance == before + cost


class TestErrorHandling:
    async def test_missing_source_clip_fails(self, storage) -> None:
        job, source = await _make_clip(storage, email="master-gone@example.com")
        await source.delete()
        dolby = FakeService(service="dolby", output=_wav_bytes(3.0))
        with pytest.raises(tasks.JobProcessingError, match="no longer exists"):
            await tasks.process_mastering_job(job, storage=storage, orchestrator=_orchestrator(dolby=dolby))

    async def test_missing_target_lufs_fails(self, storage) -> None:
        job, _ = await _make_clip(storage, email="master-nolufs@example.com")
        job.input_params = {k: v for k, v in job.input_params.items() if k != "target_lufs"}
        dolby = FakeService(service="dolby", output=_wav_bytes(3.0))
        with pytest.raises(tasks.JobProcessingError, match="target_lufs"):
            await tasks.process_mastering_job(job, storage=storage, orchestrator=_orchestrator(dolby=dolby))
