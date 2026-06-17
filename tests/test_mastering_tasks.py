"""Tests for the mastering job handler (US-12.2, issue #128).

Exercise ``acemusic.api.tasks.mastering.process_mastering_job`` directly with a
fake DolbyClient and a local on-disk storage backend: the handler downloads the
source clip, "uploads" it to Dolby, "submits"/"polls" a master preview, downloads
the mastered output and stores it as a lineage-tagged child clip. They assert the
worker contract — preview clips with lineage, metrics in the result, graceful
degradation without credentials, per-stage error handling, rollback — that the
real Dolby integration tests cannot cheaply cover.

The ``get_dolby_client`` factory tests run in CI (no DB). The handler tests need a
local MongoDB (Beanie) and are marked ``integration``.
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
from acemusic.dolby_client import DolbyError
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


class FakeDolby:
    """Records the workflow calls and returns canned previews/metrics."""

    def __init__(
        self,
        *,
        output: bytes,
        previews: list[str] | None = None,
        fail_on: str | None = None,
    ) -> None:
        self.output = output
        self.previews = previews if previews is not None else ["dlb://preview-1.wav"]
        self.fail_on = fail_on
        self.calls: list[str] = []

    def _maybe_fail(self, stage: str) -> None:
        self.calls.append(stage)
        if self.fail_on == stage:
            raise DolbyError(f"boom at {stage}")

    def upload(self, audio_bytes: bytes, filename: str) -> str:
        self._maybe_fail("upload")
        self.upload_filename = filename
        return f"dlb://{filename}"

    def submit_preview(self, input_url: str, outputs: list[dict]) -> str:
        self._maybe_fail("submit")
        self.submitted_outputs = outputs
        return "dolby-job-1"

    def wait_for_completion(self, job_id: str, *args, **kwargs) -> dict:
        self._maybe_fail("wait")
        return {"status": "success"}

    def get_results(self, job_id: str, status_payload: dict | None = None) -> dict:
        self._maybe_fail("results")
        return {
            "metrics": _METRICS,
            "outputs": [{"destination": p, "preview": p} for p in self.previews],
        }

    def download(self, dlb_url: str) -> bytes:
        self._maybe_fail("download")
        return self.output


# ---------------------------------------------------------------------------
# get_dolby_client factory (CI — no DB)
# ---------------------------------------------------------------------------


class TestGetDolbyClient:
    def test_returns_none_without_credentials(self) -> None:
        settings = ApiSettings(_env_file=None)
        assert tasks.get_dolby_client(settings) is None

    def test_returns_client_with_credentials(self) -> None:
        settings = ApiSettings(_env_file=None, dolby_api_key="k", dolby_api_secret="s")
        client = tasks.get_dolby_client(settings)
        assert client is not None
        assert client.api_key == "k"
        assert client.api_secret == "s"


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
            "service": "dolby",
            "format": "wav",
            "target_lufs": -14.0,
        },
        status=JobStatus.QUEUED,
    )
    return job, clip


pytestmark = pytest.mark.integration


class TestSuccess:
    async def test_creates_master_clip_with_lineage_and_metrics(self, storage) -> None:
        job, source = await _make_clip(storage, email="master-ok@example.com")
        client = FakeDolby(output=_wav_bytes(3.0))

        result = await tasks.process_mastering_job(job, storage=storage, client=client)

        assert len(result["clip_ids"]) == 1
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

    async def test_workflow_calls_in_order(self, storage) -> None:
        job, _ = await _make_clip(storage, email="master-order@example.com")
        client = FakeDolby(output=_wav_bytes(3.0))
        await tasks.process_mastering_job(job, storage=storage, client=client)
        assert client.calls == ["upload", "submit", "wait", "results", "download"]

    async def test_multiple_previews_each_become_clips(self, storage) -> None:
        job, _ = await _make_clip(storage, email="master-multi@example.com")
        client = FakeDolby(output=_wav_bytes(3.0), previews=["dlb://p1.wav", "dlb://p2.wav", "dlb://p3.wav"])
        result = await tasks.process_mastering_job(job, storage=storage, client=client)
        assert len(result["clip_ids"]) == 3

    async def test_dolby_keys_are_unique_per_job(self, storage) -> None:
        # The input/output keys carry the job id so concurrent masters on the same
        # clip never collide (codex review P2).
        job, source = await _make_clip(storage, email="master-keys@example.com")
        client = FakeDolby(output=_wav_bytes(3.0))
        await tasks.process_mastering_job(job, storage=storage, client=client)
        assert str(job.id) in client.upload_filename
        assert str(job.id) in client.submitted_outputs[0]["destination"]
        assert str(source.id) in client.upload_filename


class TestGracefulDegradation:
    async def test_missing_client_raises_clear_error(self, storage) -> None:
        job, _ = await _make_clip(storage, email="master-nocreds@example.com")
        with pytest.raises(tasks.MasteringProcessingError, match="not configured"):
            await tasks.process_mastering_job(job, storage=storage, client=None)

    async def test_unsupported_service_raises(self, storage) -> None:
        job, _ = await _make_clip(storage, email="master-landr@example.com")
        job.input_params = {**job.input_params, "service": "landr"}
        client = FakeDolby(output=_wav_bytes(3.0))
        with pytest.raises(tasks.MasteringProcessingError, match="not yet implemented"):
            await tasks.process_mastering_job(job, storage=storage, client=client)

    async def test_unsupported_service_refunds_charged_credits(self, storage) -> None:
        # The router charges per service up front; a pre-flight rejection must
        # refund so the user is not left paying for a failed job (codex review P2).
        from acemusic.api.services import credits as credits_service

        job, _ = await _make_clip(storage, email="master-refund-landr@example.com")
        job.input_params = {**job.input_params, "service": "landr"}
        cost = credits_service.get_mastering_cost("landr")
        before = await credits_service.deduct_credits(job.user_id, cost)
        with pytest.raises(tasks.MasteringProcessingError):
            await tasks.process_mastering_job(job, storage=storage, client=FakeDolby(output=_wav_bytes(3.0)))
        user = await user_service.get_user_by_id(str(job.user_id))
        assert user.credits_balance == before + cost

    async def test_missing_client_refunds_charged_credits(self, storage) -> None:
        from acemusic.api.services import credits as credits_service

        job, _ = await _make_clip(storage, email="master-refund-nocreds@example.com")
        cost = credits_service.get_mastering_cost("dolby")
        before = await credits_service.deduct_credits(job.user_id, cost)
        with pytest.raises(tasks.MasteringProcessingError, match="not configured"):
            await tasks.process_mastering_job(job, storage=storage, client=None)
        user = await user_service.get_user_by_id(str(job.user_id))
        assert user.credits_balance == before + cost


class TestErrorHandling:
    @pytest.mark.parametrize("stage", ["upload", "submit", "wait", "results", "download"])
    async def test_dolby_error_at_each_stage_is_wrapped(self, storage, stage) -> None:
        job, _ = await _make_clip(storage, email=f"master-fail-{stage}@example.com")
        client = FakeDolby(output=_wav_bytes(3.0), fail_on=stage)
        with pytest.raises(tasks.MasteringProcessingError, match="Dolby"):
            await tasks.process_mastering_job(job, storage=storage, client=client)

    async def test_missing_source_clip_fails(self, storage) -> None:
        job, source = await _make_clip(storage, email="master-gone@example.com")
        await source.delete()
        client = FakeDolby(output=_wav_bytes(3.0))
        with pytest.raises(tasks.MasteringProcessingError, match="no longer exists"):
            await tasks.process_mastering_job(job, storage=storage, client=client)

    async def test_no_previews_returned_fails(self, storage) -> None:
        job, _ = await _make_clip(storage, email="master-empty@example.com")
        client = FakeDolby(output=_wav_bytes(3.0), previews=[])
        with pytest.raises(tasks.MasteringProcessingError, match="no preview outputs"):
            await tasks.process_mastering_job(job, storage=storage, client=client)

    async def test_download_failure_rolls_back_stored_previews(self, storage) -> None:
        job, _ = await _make_clip(storage, email="master-rollback@example.com")
        # First preview stores fine; the second download fails — the first must roll back.
        client = _RollbackDolby(output=_wav_bytes(3.0), previews=["dlb://p1.wav", "dlb://p2.wav"])
        with pytest.raises(tasks.MasteringProcessingError):
            await tasks.process_mastering_job(job, storage=storage, client=client)
        # No master clip should survive for this job's source.
        remaining = await Clip.find(Clip.generation_mode == MASTERING_JOB_TYPE).to_list()
        assert remaining == []


class _RollbackDolby(FakeDolby):
    """Succeeds on the first download, fails on the second to trigger rollback."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._downloads = 0

    def download(self, dlb_url: str) -> bytes:
        self._downloads += 1
        if self._downloads >= 2:
            raise DolbyError("download blew up")
        return self.output
