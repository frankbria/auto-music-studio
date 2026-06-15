"""Tests for the full-song assembly endpoint (US-10.4, issue #84).

``POST /api/v1/clips/{id}/full-song`` grows a short seed clip into a complete
song by chaining one paid ACE-Step extend per planned section, tracked as a
single background job that reports per-section progress via the job-status
endpoint. Credits scale with the number of extends (sections).

The 401 auth-gate test runs in CI (no DB; the plain ``TestClient`` does not run
the lifespan); the rest are ``integration`` and drive the real app with
``httpx.AsyncClient`` over a local MongoDB.
"""

import asyncio
import io
import time

import httpx
import numpy as np
import pytest
import soundfile as sf
from beanie import PydanticObjectId
from fastapi.testclient import TestClient

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.models import Clip, CreditTransaction, Job, JobStatus, User, Workspace
from acemusic.api.services import users as user_service
from acemusic.api.settings import ApiSettings
from acemusic.api.tasks.iterative import IterativeProcessingError
from acemusic.song_structure import SONG_STRUCTURE
from acemusic.storage import LocalStorage, get_storage_backend

CLIPS_URL = f"{API_V1_PREFIX}/clips"


def _url(clip_id) -> str:
    return f"{CLIPS_URL}/{clip_id}/full-song"


def _status_url(job_id) -> str:
    return f"{API_V1_PREFIX}/jobs/{job_id}/status"


# ---------------------------------------------------------------------------
# Auth gate — runs in CI (no DB)
# ---------------------------------------------------------------------------


class TestAuthGate:
    def test_missing_auth_header_returns_401(self) -> None:
        client = TestClient(create_app())
        resp = client.post(_url(PydanticObjectId()), json={})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Integration scaffolding — real MongoDB
# ---------------------------------------------------------------------------


def _async_client(app) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


@pytest.fixture
def settings(mongo_db, mongo_settings) -> ApiSettings:
    # Disable the background processor: most tests assert on the queued job and
    # do not want a worker claiming it. The lifecycle test starts its own.
    return mongo_settings.model_copy(
        update={
            "jwt_secret_key": "test-secret-key-at-least-32-bytes-long-xx",
            "job_processor_enabled": False,
        }
    )


@pytest.fixture
async def client(settings):
    async with _async_client(create_app(settings)) as ac:
        yield ac


def _auth_headers(user, settings: ApiSettings) -> dict[str, str]:
    token = create_access_token(
        user_id=str(user.id),
        email=user.email,
        subscription_tier=user.subscription_tier,
        settings=settings,
    )
    return {"Authorization": f"Bearer {token}"}


async def _make_user(email: str, *, balance: float | None = None):
    user = await user_service.get_or_create_user(email=email, provider="google", oauth_id=f"g-{email}", name="T")
    if balance is not None:
        user.credits_balance = balance
        await user.save()
    return user


async def _make_workspace(user, name: str = "WS") -> Workspace:
    workspace = Workspace(name=name, user_id=user.id)
    await workspace.insert()
    return workspace


async def _insert_clip(user, workspace, *, duration=10.0, bpm=120, key="C", fmt="wav", style_tags=None) -> Clip:
    clip_id = PydanticObjectId()
    clip = Clip(
        id=clip_id,
        user_id=user.id,
        workspace_id=workspace.id,
        file_path=f"{user.id}/{workspace.id}/clips/{clip_id}.{fmt or 'wav'}",
        format=fmt,
        duration=duration,
        bpm=bpm,
        key=key,
        style_tags=style_tags or ["dream pop"],
    )
    await clip.insert()
    return clip


async def _user_with_clip(email: str, *, balance: float = 10.0, **clip_kwargs):
    user = await _make_user(email, balance=balance)
    workspace = await _make_workspace(user)
    clip = await _insert_clip(user, workspace, **clip_kwargs)
    return user, workspace, clip


async def _reload_user(user) -> User:
    return await User.get(user.id)


# ---------------------------------------------------------------------------
# 404 — unknown / malformed / other-user clip ids
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestClipNotFound:
    async def test_unknown_clip_returns_404(self, client, settings) -> None:
        user = await _make_user("fs-404@example.com", balance=10.0)
        resp = await client.post(_url(PydanticObjectId()), json={}, headers=_auth_headers(user, settings))
        assert resp.status_code == 404
        assert await Job.count() == 0

    async def test_malformed_id_returns_404(self, client, settings) -> None:
        user = await _make_user("fs-malformed@example.com", balance=10.0)
        resp = await client.post(_url("not-an-object-id"), json={}, headers=_auth_headers(user, settings))
        assert resp.status_code == 404

    async def test_other_users_clip_returns_404(self, client, settings) -> None:
        _, _, clip = await _user_with_clip("fs-owner@example.com")
        other = await _make_user("fs-other@example.com", balance=10.0)
        resp = await client.post(_url(clip.id), json={}, headers=_auth_headers(other, settings))
        assert resp.status_code == 404
        assert (await _reload_user(other)).credits_balance == 10.0
        assert await Job.count() == 0


# ---------------------------------------------------------------------------
# 422 — validation (the body parsed; the request is logically invalid)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestValidation:
    async def test_seed_at_or_over_60s_returns_422(self, client, settings) -> None:
        user, _, clip = await _user_with_clip("fs-longseed@example.com", duration=60.0)
        resp = await client.post(_url(clip.id), json={}, headers=_auth_headers(user, settings))
        assert resp.status_code == 422
        assert "60s" in resp.json()["detail"]
        assert await Job.count() == 0

    async def test_seed_just_under_60s_is_accepted(self, client, settings) -> None:
        # Boundary happy-path: 59.9s is "shorter than 60s", so it must enqueue.
        user, _, clip = await _user_with_clip("fs-seed-599@example.com", duration=59.9)
        resp = await client.post(_url(clip.id), json={}, headers=_auth_headers(user, settings))
        assert resp.status_code == 202
        assert await Job.count() == 1

    async def test_target_not_exceeding_seed_returns_422(self, client, settings) -> None:
        user, _, clip = await _user_with_clip("fs-target-low@example.com", duration=30.0)
        resp = await client.post(_url(clip.id), json={"target_duration": 20}, headers=_auth_headers(user, settings))
        assert resp.status_code == 422
        assert await Job.count() == 0

    async def test_target_over_backend_max_returns_422(self, client, settings) -> None:
        user, _, clip = await _user_with_clip("fs-target-high@example.com", duration=10.0)
        resp = await client.post(_url(clip.id), json={"target_duration": 999}, headers=_auth_headers(user, settings))
        assert resp.status_code == 422
        assert await Job.count() == 0

    async def test_unknown_structure_section_returns_422(self, client, settings) -> None:
        user, _, clip = await _user_with_clip("fs-badsection@example.com", duration=10.0)
        resp = await client.post(
            _url(clip.id),
            json={"structure_plan": ["intro", "drop", "outro"]},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 422
        assert await Job.count() == 0

    async def test_empty_structure_plan_returns_422(self, client, settings) -> None:
        user, _, clip = await _user_with_clip("fs-emptystructure@example.com", duration=10.0)
        resp = await client.post(_url(clip.id), json={"structure_plan": []}, headers=_auth_headers(user, settings))
        assert resp.status_code == 422
        assert await Job.count() == 0

    async def test_extra_field_returns_422(self, client, settings) -> None:
        user, _, clip = await _user_with_clip("fs-extra@example.com", duration=10.0)
        resp = await client.post(_url(clip.id), json={"bogus": 1}, headers=_auth_headers(user, settings))
        assert resp.status_code == 422

    async def test_missing_duration_metadata_returns_422(self, client, settings) -> None:
        user, _, clip = await _user_with_clip("fs-nodur@example.com", duration=None)
        resp = await client.post(_url(clip.id), json={}, headers=_auth_headers(user, settings))
        assert resp.status_code == 422
        assert await Job.count() == 0

    async def test_non_wav_source_returns_422(self, client, settings) -> None:
        user, _, clip = await _user_with_clip("fs-mp3@example.com", duration=10.0, fmt="mp3")
        resp = await client.post(_url(clip.id), json={}, headers=_auth_headers(user, settings))
        assert resp.status_code == 422
        assert await Job.count() == 0


# ---------------------------------------------------------------------------
# 202 — happy path: job persisted, params forwarded
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestEnqueueSuccess:
    async def test_returns_202_with_job_id(self, client, settings) -> None:
        user, _, clip = await _user_with_clip("fs-202@example.com")
        resp = await client.post(_url(clip.id), json={}, headers=_auth_headers(user, settings))
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "queued"
        assert body["job_id"]
        assert body["estimated_time_seconds"] > 0

    async def test_persists_job_with_resolved_params(self, client, settings) -> None:
        user, workspace, clip = await _user_with_clip("fs-job@example.com")
        resp = await client.post(
            _url(clip.id),
            json={"target_duration": 180, "style": "orchestral", "lyrics": "ooh"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 202
        jobs = await Job.find_all().to_list()
        assert len(jobs) == 1
        job = jobs[0]
        assert job.job_type == "full_song"
        assert job.workspace_id == workspace.id
        assert job.input_params["clip_id"] == str(clip.id)
        assert job.input_params["target_duration"] == 180
        assert job.input_params["style"] == "orchestral"
        assert job.input_params["lyrics"] == "ooh"

    async def test_custom_structure_plan_is_persisted(self, client, settings) -> None:
        user, _, clip = await _user_with_clip("fs-structure@example.com")
        structure = ["intro", "verse", "chorus", "outro"]
        resp = await client.post(
            _url(clip.id), json={"structure_plan": structure}, headers=_auth_headers(user, settings)
        )
        assert resp.status_code == 202
        job = (await Job.find_all().to_list())[0]
        assert job.input_params["structure_plan"] == structure


# ---------------------------------------------------------------------------
# Credits — deducted per extend (one per section)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCredits:
    async def test_deducts_one_credit_per_section(self, client, settings) -> None:
        user, _, clip = await _user_with_clip("fs-credit@example.com", balance=10.0)
        resp = await client.post(_url(clip.id), json={}, headers=_auth_headers(user, settings))
        assert resp.status_code == 202
        # Default structure is the seven canonical sections → seven extends.
        expected = float(len(SONG_STRUCTURE))
        assert (await _reload_user(user)).credits_balance == 10.0 - expected
        txns = await CreditTransaction.find(CreditTransaction.user_id == user.id).to_list()
        assert len(txns) == 1
        assert txns[0].amount == -expected
        assert txns[0].action_type == "full_song"

    async def test_cost_scales_with_structure_length(self, client, settings) -> None:
        user, _, clip = await _user_with_clip("fs-credit-custom@example.com", balance=10.0)
        resp = await client.post(
            _url(clip.id),
            json={"structure_plan": ["intro", "verse", "chorus", "outro"]},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 202
        assert (await _reload_user(user)).credits_balance == 6.0  # 10 - 4

    async def test_insufficient_credits_returns_402(self, client, settings) -> None:
        user, _, clip = await _user_with_clip("fs-poor@example.com", balance=3.0)
        resp = await client.post(_url(clip.id), json={}, headers=_auth_headers(user, settings))
        assert resp.status_code == 402
        detail = resp.json()["detail"]
        assert detail["error"] == "insufficient_credits"
        assert detail["balance"] == 3.0
        assert detail["required"] == float(len(SONG_STRUCTURE))
        assert await Job.count() == 0


# ---------------------------------------------------------------------------
# Progress — surfaced by the job-status endpoint while in flight
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestProgressSurfaced:
    async def test_status_endpoint_returns_progress_while_processing(self, client, settings) -> None:
        user = await _make_user("fs-progress@example.com", balance=10.0)
        workspace = await _make_workspace(user)
        job = Job(
            user_id=user.id,
            workspace_id=workspace.id,
            job_type="full_song",
            status=JobStatus.PROCESSING,
            input_params={"target_duration": 210},
            progress="Processing section 3 of 7",
        )
        await job.insert()
        resp = await client.get(_status_url(job.id), headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        assert resp.json()["progress"] == "Processing section 3 of 7"

    async def test_progress_dropped_once_completed(self, client, settings) -> None:
        user = await _make_user("fs-progress-done@example.com", balance=10.0)
        workspace = await _make_workspace(user)
        job = Job(
            user_id=user.id,
            workspace_id=workspace.id,
            job_type="full_song",
            status=JobStatus.COMPLETED,
            input_params={"target_duration": 210},
            progress="Processing section 7 of 7",
            result={"clip_ids": []},
        )
        await job.insert()
        resp = await client.get(_status_url(job.id), headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        assert "progress" not in resp.json()

    async def test_progress_dropped_once_failed(self, client, settings) -> None:
        # A mid-chain failure may leave a stale progress string in the document;
        # the status endpoint must not surface it once the job is terminal.
        user = await _make_user("fs-progress-failed@example.com", balance=10.0)
        workspace = await _make_workspace(user)
        job = Job(
            user_id=user.id,
            workspace_id=workspace.id,
            job_type="full_song",
            status=JobStatus.FAILED,
            input_params={"target_duration": 210},
            progress="Processing section 3 of 7",
            error="boom",
        )
        await job.insert()
        resp = await client.get(_status_url(job.id), headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        body = resp.json()
        assert "progress" not in body
        assert body["error"] == "boom"


# ---------------------------------------------------------------------------
# Worker handler — deterministic, section-by-section assertions
# ---------------------------------------------------------------------------


def _wav_bytes(duration_s: float = 2.0, freq: float = 440.0, sr: int = 44100) -> bytes:
    t = np.linspace(0, duration_s, int(sr * duration_s), endpoint=False)
    mono = (0.3 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    buf = io.BytesIO()
    sf.write(buf, np.column_stack([mono, mono]), sr, format="WAV")
    return buf.getvalue()


class _RecordingAce:
    """ACE-Step double that records every submit so per-section behaviour is testable."""

    def __init__(self, output: bytes) -> None:
        self.output = output
        self.submits: list[dict] = []

    def submit_task(self, **kwargs) -> str:
        self.submits.append(kwargs)
        return f"task-{len(self.submits)}"

    def query_result(self, task_id: str) -> dict:
        return {"status": "completed", "audio_urls": ["u0"], "error": None}

    def download_audio(self, url: str) -> bytes:
        return self.output


class _FailingAce:
    """ACE-Step double whose Nth task (1-based ``fail_on``) reports a failure."""

    def __init__(self, output: bytes, *, fail_on: int) -> None:
        self.output = output
        self.fail_on = fail_on

    def submit_task(self, **kwargs) -> str:
        # Encode the call ordinal in the task id so query_result can fail the Nth.
        self._n = getattr(self, "_n", 0) + 1
        return f"task-{self._n}"

    def query_result(self, task_id: str) -> dict:
        n = int(task_id.split("-")[1])
        if n >= self.fail_on:
            return {"status": "failed", "audio_urls": [], "error": "ace boom"}
        return {"status": "completed", "audio_urls": ["u0"], "error": None}

    def download_audio(self, url: str) -> bytes:
        return self.output


async def _poll(client, task_id):
    return await asyncio.to_thread(client.query_result, task_id)


@pytest.fixture
def local_storage(monkeypatch, tmp_path):
    monkeypatch.setenv("ACEMUSIC_STORAGE_BACKEND", "local")
    monkeypatch.setenv("ACEMUSIC_STORAGE_LOCAL_ROOT", str(tmp_path / "storage"))
    return tmp_path


@pytest.fixture
def storage(mongo_db, tmp_path) -> LocalStorage:
    # ``mongo_db`` initialises Beanie so the handler can read/insert documents
    # on this test's event loop; the LocalStorage instance is passed directly.
    return LocalStorage(tmp_path / "storage")


@pytest.mark.integration
class TestFullSongHandler:
    async def _seed(self, storage: LocalStorage, *, duration=10.0, style_tags=None):
        user = await _make_user(f"fs-handler-{PydanticObjectId()}@example.com", balance=50.0)
        workspace = await _make_workspace(user)
        clip_id = PydanticObjectId()
        file_path = f"{user.id}/{workspace.id}/clips/{clip_id}.wav"
        storage.upload(file_path, _wav_bytes(2.0))
        clip = Clip(
            id=clip_id,
            user_id=user.id,
            workspace_id=workspace.id,
            file_path=file_path,
            format="wav",
            duration=duration,
            bpm=120,
            key="C",
            style_tags=style_tags or ["dream pop"],
        )
        await clip.insert()
        return user, workspace, clip

    async def _run(self, job, ace, storage: LocalStorage):
        from acemusic.api.tasks.iterative import process_full_song_job

        return await process_full_song_job(job, storage=storage, client=ace, poll=_poll)

    async def _job(self, user, workspace, clip, **params):
        job = Job(
            user_id=user.id,
            workspace_id=workspace.id,
            job_type="full_song",
            status=JobStatus.PROCESSING,
            input_params={"clip_id": str(clip.id), "target_duration": 210, "structure_plan": None, **params},
        )
        await job.insert()
        return job

    async def test_runs_one_extend_per_section(self, storage) -> None:
        user, workspace, clip = await self._seed(storage)
        ace = _RecordingAce(_wav_bytes(2.0))
        job = await self._job(user, workspace, clip)
        result = await self._run(job, ace, storage)
        assert len(ace.submits) == len(SONG_STRUCTURE)
        assert all(s["task_type"] == "repaint" for s in ace.submits)
        assert len(result["clip_ids"]) == 1

    async def test_final_clip_duration_approximates_target(self, storage) -> None:
        user, workspace, clip = await self._seed(storage, duration=10.0)
        job = await self._job(user, workspace, clip, target_duration=210)
        result = await self._run(job, _RecordingAce(_wav_bytes(2.0)), storage)
        final = await Clip.get(PydanticObjectId(result["clip_ids"][0]))
        assert final.duration == pytest.approx(210, abs=1.0)
        assert final.generation_mode == "full_song"

    async def test_lineage_chains_seed_through_sections(self, storage) -> None:
        user, workspace, clip = await self._seed(storage)
        result = await self._run(await self._job(user, workspace, clip), _RecordingAce(_wav_bytes(2.0)), storage)
        # Every full_song child plus the seed; walk the single-parent chain back.
        children = await Clip.find(Clip.generation_mode == "full_song").to_list()
        assert len(children) == len(SONG_STRUCTURE)
        final = await Clip.get(PydanticObjectId(result["clip_ids"][0]))
        seen = 0
        node = final
        while node.parent_clip_ids:
            assert len(node.parent_clip_ids) == 1
            node = await Clip.get(node.parent_clip_ids[0])
            seen += 1
        assert node.id == clip.id  # chain terminates at the seed
        assert seen == len(SONG_STRUCTURE)

    async def test_sections_carry_distinct_styles_for_variety(self, storage) -> None:
        user, workspace, clip = await self._seed(storage, style_tags=["dream pop"])
        ace = _RecordingAce(_wav_bytes(2.0))
        await self._run(await self._job(user, workspace, clip), ace, storage)
        styles = [s["style"] for s in ace.submits]
        # Distinct section hints → audible structural variety (not pure repetition).
        assert len(set(styles)) >= 3
        # Every section anchors to the seed's own style so the chain doesn't drift.
        assert all("dream pop" in s for s in styles)

    async def test_style_override_anchors_every_section(self, storage) -> None:
        user, workspace, clip = await self._seed(storage, style_tags=["dream pop"])
        ace = _RecordingAce(_wav_bytes(2.0))
        await self._run(await self._job(user, workspace, clip, style="orchestral"), ace, storage)
        assert all("orchestral" in s["style"] for s in ace.submits)
        assert all("dream pop" not in s["style"] for s in ace.submits)

    async def test_progress_updated_per_section(self, storage) -> None:
        user, workspace, clip = await self._seed(storage)
        job = await self._job(user, workspace, clip)
        await self._run(job, _RecordingAce(_wav_bytes(2.0)), storage)
        refreshed = await Job.get(job.id)
        assert refreshed.progress == f"Processing section {len(SONG_STRUCTURE)} of {len(SONG_STRUCTURE)}"

    async def test_custom_structure_controls_section_count(self, storage) -> None:
        user, workspace, clip = await self._seed(storage)
        ace = _RecordingAce(_wav_bytes(2.0))
        job = await self._job(user, workspace, clip, structure_plan=["intro", "chorus", "outro"])
        result = await self._run(job, ace, storage)
        assert len(ace.submits) == 3
        assert len(result["clip_ids"]) == 1

    async def test_mid_chain_failure_preserves_earlier_sections(self, storage) -> None:
        # Intentional policy (mirrors the CLI): sections committed before a
        # mid-chain failure are kept as partial progress — full_song does not
        # roll children back, unlike the multi-output sample handler.
        user, workspace, clip = await self._seed(storage)
        job = await self._job(user, workspace, clip, structure_plan=["intro", "verse", "chorus", "outro"])
        with pytest.raises(IterativeProcessingError, match="ace boom"):
            await self._run(job, _FailingAce(_wav_bytes(2.0), fail_on=3), storage)
        # Sections 1 and 2 committed before the third failed.
        children = await Clip.find(Clip.generation_mode == "full_song").to_list()
        assert len(children) == 2


# ---------------------------------------------------------------------------
# End-to-end — endpoint → queued job → JobProcessor → completed clip
# ---------------------------------------------------------------------------


class _FakeAce:
    def __init__(self, output: bytes) -> None:
        self.output = output

    def submit_task(self, **kwargs) -> str:
        return "task-1"

    def query_result(self, task_id: str) -> dict:
        return {"status": "completed", "audio_urls": ["u0"], "error": None}

    def download_audio(self, url: str) -> bytes:
        return self.output


@pytest.mark.integration
class TestLifecycleEndToEnd:
    async def test_full_song_runs_to_completed_via_status_endpoint(self, client, settings, local_storage) -> None:
        from acemusic.api.tasks.processor import JobProcessor

        user = await _make_user("fs-e2e@example.com", balance=20.0)
        workspace = await _make_workspace(user)
        clip_id = PydanticObjectId()
        file_path = f"{user.id}/{workspace.id}/clips/{clip_id}.wav"
        get_storage_backend().upload(file_path, _wav_bytes(2.0))
        clip = Clip(
            id=clip_id,
            user_id=user.id,
            workspace_id=workspace.id,
            file_path=file_path,
            format="wav",
            duration=10.0,
            bpm=120,
            key="C",
            style_tags=["dream pop"],
        )
        await clip.insert()
        headers = _auth_headers(user, settings)

        accepted = await client.post(_url(clip.id), json={"target_duration": 210}, headers=headers)
        assert accepted.status_code == 202
        job_id = accepted.json()["job_id"]

        processor = JobProcessor(
            concurrency=1,
            poll_interval=0.05,
            ace_poll_interval=0.01,
            client_factory=lambda: _FakeAce(_wav_bytes(2.0)),
        )
        await processor.start()
        try:
            status_body = None
            deadline = time.monotonic() + 30.0
            while time.monotonic() < deadline:
                resp = await client.get(_status_url(job_id), headers=headers)
                assert resp.status_code == 200
                status_body = resp.json()
                assert status_body["status"] in {"queued", "processing", "completed"}, status_body.get("error")
                if status_body["status"] == "completed":
                    break
                await asyncio.sleep(0.05)
        finally:
            await processor.stop()

        assert status_body is not None and status_body["status"] == "completed", "job never completed"
        assert len(status_body["clip_ids"]) == 1
        final = await Clip.get(PydanticObjectId(status_body["clip_ids"][0]))
        assert final.generation_mode == "full_song"
        assert final.duration == pytest.approx(210, abs=1.0)
