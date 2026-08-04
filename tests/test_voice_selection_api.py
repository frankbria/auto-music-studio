"""US-25.4: attaching a trained voice to a generation.

Covers the five creation modes that accept a voice (Simple/Advanced share
``POST /generate``; Cover, Add Vocal and Extend are clip-scoped), the rules that stop
an unusable or someone else's voice from being charged for, and the preview a musician
listens to before attaching one.
"""

import httpx
import pytest
from beanie import PydanticObjectId

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.models import Clip, Job, User, VoiceModel, VoiceModelStatus
from acemusic.api.services import routing, users as user_service
from acemusic.api.settings import ApiSettings
from acemusic.api.tasks.common import JobProcessingError
from acemusic.api.tasks.voice_adapter import resolve_weights
from acemusic.storage import get_storage_backend

pytestmark = pytest.mark.integration

GENERATE_URL = f"{API_V1_PREFIX}/generate"
VOICE_URL = f"{API_V1_PREFIX}/voice-models"

REFERENCE_BYTES = b"RIFF....WAVEfake-reference-audio"


@pytest.fixture(autouse=True)
def _local_compute_available(monkeypatch):
    """A reachable local backend, so these tests assert voices rather than routing."""

    async def _local(url, timeout=routing.LOCAL_AVAILABILITY_TIMEOUT):
        return True

    async def _remote(settings=None):
        return False

    monkeypatch.setattr(routing, "check_local_availability", _local)
    monkeypatch.setattr(routing, "check_remote_availability", _remote)


@pytest.fixture
def settings(mongo_db, mongo_settings) -> ApiSettings:
    return mongo_settings.model_copy(
        update={
            "jwt_secret_key": "test-secret-key-at-least-32-bytes-long-xx",
            "job_processor_enabled": False,
        }
    )


@pytest.fixture
async def client(settings):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings)), base_url="http://testserver"
    ) as ac:
        yield ac


@pytest.fixture
def local_storage(monkeypatch, tmp_path):
    monkeypatch.setenv("ACEMUSIC_STORAGE_BACKEND", "local")
    monkeypatch.setenv("ACEMUSIC_STORAGE_LOCAL_ROOT", str(tmp_path))
    return tmp_path


def _auth(user: User, settings: ApiSettings) -> dict[str, str]:
    token = create_access_token(
        user_id=str(user.id),
        email=user.email,
        subscription_tier=user.subscription_tier,
        settings=settings,
    )
    return {"Authorization": f"Bearer {token}"}


async def _make_user(email: str, credits: float = 100.0) -> User:
    user = await user_service.get_or_create_user(email=email, provider="google", oauth_id=f"g-{email}", name="T")
    user.credits_balance = credits
    await user.save()
    return user


async def _make_voice(
    user: User,
    *,
    name: str = "My Voice",
    status: VoiceModelStatus = VoiceModelStatus.READY,
    weights: str | None = "./voice-training/abc/voice.safetensors/adapter",
    references: bool = True,
) -> VoiceModel:
    """A voice model straight in the DB — training itself is US-25.1's business."""
    model = VoiceModel(user_id=user.id, name=name, status=status, weights_path=weights)
    await model.insert()

    if references:
        path = f"{user.id}/voice-models/{model.id}/ref-0.wav"
        get_storage_backend().upload(path, REFERENCE_BYTES)
        model.reference_paths = [path]
        await model.save()

    return model


async def _make_wav_clip(user: User) -> Clip:
    """A source clip the iterative endpoints will accept (wav, with a duration)."""
    workspace_id = PydanticObjectId()
    clip = Clip(
        user_id=user.id,
        workspace_id=workspace_id,
        file_path=f"{user.id}/{workspace_id}/clips/source.wav",
        format="wav",
        duration=60.0,
    )
    await clip.insert()
    return clip


def _song(**extra) -> dict:
    return {"prompt": "a warm ballad", **extra}


class TestGenerateWithAVoice:
    async def test_a_ready_voice_is_recorded_on_the_job(self, client, settings, local_storage) -> None:
        user = await _make_user("simple@example.com")
        voice = await _make_voice(user)

        resp = await client.post(GENERATE_URL, json=_song(voice_model_id=str(voice.id)), headers=_auth(user, settings))

        assert resp.status_code == 202, resp.text
        job = await Job.get(resp.json()["job_id"])
        assert job.input_params["voice_model_id"] == str(voice.id)

    async def test_a_voice_pins_the_job_to_local_compute(self, client, settings, local_storage) -> None:
        # The adapter is a file on the local ACE-Step host; a remote backend has no
        # way to load it, so the job must not be routed there.
        user = await _make_user("pinned@example.com")
        voice = await _make_voice(user)

        resp = await client.post(
            GENERATE_URL,
            json=_song(voice_model_id=str(voice.id), compute_target="remote"),
            headers=_auth(user, settings),
        )

        assert resp.status_code == 202, resp.text
        job = await Job.get(resp.json()["job_id"])
        assert job.compute_target == "local"

    async def test_generating_without_a_voice_is_unchanged(self, client, settings) -> None:
        user = await _make_user("plain@example.com")

        resp = await client.post(GENERATE_URL, json=_song(), headers=_auth(user, settings))

        assert resp.status_code == 202, resp.text
        job = await Job.get(resp.json()["job_id"])
        assert "voice_model_id" not in job.input_params

    async def test_an_unknown_voice_is_refused_without_charging(self, client, settings) -> None:
        user = await _make_user("unknown@example.com", credits=10.0)

        resp = await client.post(
            GENERATE_URL, json=_song(voice_model_id=str(PydanticObjectId())), headers=_auth(user, settings)
        )

        assert resp.status_code == 404, resp.text
        assert (await User.get(user.id)).credits_balance == 10.0

    async def test_another_users_voice_is_indistinguishable_from_a_missing_one(
        self, client, settings, local_storage
    ) -> None:
        owner = await _make_user("owner@example.com")
        intruder = await _make_user("intruder@example.com")
        voice = await _make_voice(owner)

        resp = await client.post(
            GENERATE_URL, json=_song(voice_model_id=str(voice.id)), headers=_auth(intruder, settings)
        )

        assert resp.status_code == 404, resp.text

    @pytest.mark.parametrize(
        "status,weights",
        [
            (VoiceModelStatus.TRAINING, None),
            (VoiceModelStatus.FAILED, None),
            # "Job completed" and "voice is usable" are different claims.
            (VoiceModelStatus.READY, None),
        ],
    )
    async def test_a_voice_that_cannot_sing_yet_is_a_conflict(
        self, client, settings, local_storage, status, weights
    ) -> None:
        user = await _make_user(f"notready-{status.value}-{weights}@example.com", credits=10.0)
        voice = await _make_voice(user, status=status, weights=weights)

        resp = await client.post(GENERATE_URL, json=_song(voice_model_id=str(voice.id)), headers=_auth(user, settings))

        assert resp.status_code == 409, resp.text
        assert (await User.get(user.id)).credits_balance == 10.0


class TestIterativeModesWithAVoice:
    @pytest.mark.parametrize(
        "op,body",
        [
            ("cover", {"style": "acoustic ballad"}),
            ("add-vocal", {"lyrics": "[Verse]\nla la la"}),
            ("extend", {"duration": "20s"}),
        ],
    )
    async def test_the_voice_reaches_the_job(self, client, settings, local_storage, op, body) -> None:
        user = await _make_user(f"{op}@example.com")
        voice = await _make_voice(user)
        clip = await _make_wav_clip(user)

        resp = await client.post(
            f"{API_V1_PREFIX}/clips/{clip.id}/{op}",
            json={**body, "voice_model_id": str(voice.id)},
            headers=_auth(user, settings),
        )

        assert resp.status_code == 202, resp.text
        job = await Job.get(resp.json()["job_id"])
        assert job.input_params["voice_model_id"] == str(voice.id)

    @pytest.mark.parametrize(
        "op,body",
        [
            ("cover", {"style": "acoustic ballad"}),
            ("add-vocal", {"lyrics": "[Verse]\nla la la"}),
            ("extend", {"duration": "20s"}),
        ],
    )
    async def test_an_unusable_voice_costs_nothing(self, client, settings, local_storage, op, body) -> None:
        user = await _make_user(f"{op}-notready@example.com", credits=10.0)
        voice = await _make_voice(user, status=VoiceModelStatus.TRAINING, weights=None)
        clip = await _make_wav_clip(user)

        resp = await client.post(
            f"{API_V1_PREFIX}/clips/{clip.id}/{op}",
            json={**body, "voice_model_id": str(voice.id)},
            headers=_auth(user, settings),
        )

        assert resp.status_code == 409, resp.text
        assert (await User.get(user.id)).credits_balance == 10.0


class TestPreview:
    async def test_the_owner_hears_a_reference_recording(self, client, settings, local_storage) -> None:
        user = await _make_user("preview@example.com")
        voice = await _make_voice(user)

        resp = await client.get(f"{VOICE_URL}/{voice.id}/preview", headers=_auth(user, settings))

        assert resp.status_code == 200, resp.text
        assert resp.content == REFERENCE_BYTES
        assert resp.headers["content-type"].startswith("audio/wav")

    async def test_someone_elses_voice_cannot_be_previewed(self, client, settings, local_storage) -> None:
        owner = await _make_user("preview-owner@example.com")
        intruder = await _make_user("preview-intruder@example.com")
        voice = await _make_voice(owner)

        resp = await client.get(f"{VOICE_URL}/{voice.id}/preview", headers=_auth(intruder, settings))

        assert resp.status_code == 404, resp.text

    async def test_a_voice_with_no_stored_references_is_a_clean_404(self, client, settings, local_storage) -> None:
        user = await _make_user("preview-empty@example.com")
        voice = await _make_voice(user, references=False)

        resp = await client.get(f"{VOICE_URL}/{voice.id}/preview", headers=_auth(user, settings))

        assert resp.status_code == 404, resp.text


class TestWorkerResolution:
    async def _job(self, user: User, voice_model_id: str | None) -> Job:
        params = {"prompt": "x"}
        if voice_model_id is not None:
            params["voice_model_id"] = voice_model_id
        job = Job(
            user_id=user.id,
            workspace_id=PydanticObjectId(),
            job_type="generate",
            input_params=params,
        )
        await job.insert()
        return job

    async def test_the_adapter_path_is_read_from_the_voice(self, mongo_db, local_storage) -> None:
        user = await _make_user("worker@example.com")
        voice = await _make_voice(user, weights="./lora/mine/adapter")

        assert await resolve_weights(await self._job(user, str(voice.id))) == "./lora/mine/adapter"

    async def test_a_job_with_no_voice_needs_no_adapter(self, mongo_db) -> None:
        user = await _make_user("worker-plain@example.com")

        assert await resolve_weights(await self._job(user, None)) is None

    async def test_a_voice_deleted_after_queueing_fails_the_job(self, mongo_db, local_storage) -> None:
        # Falling back to the base voice would silently deliver something else.
        user = await _make_user("worker-deleted@example.com")
        voice = await _make_voice(user)
        job = await self._job(user, str(voice.id))
        await voice.delete()

        with pytest.raises(JobProcessingError):
            await resolve_weights(job)
