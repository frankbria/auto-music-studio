"""Tests for voice model training (US-25.1, issue #325).

Validation and the auth gate run in CI (no DB); the rest are ``integration`` and
drive the real app with ``httpx.AsyncClient`` over a local MongoDB, mirroring
``tests/test_clips_crud_api.py``.

The thing most worth protecting here is the *order* of validation: the musician
is only charged once every check that can reject the request has passed, so a bad
upload never costs credits.
"""

import io

import httpx
import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.models import Job, User, VoiceModel, VoiceModelStatus
from acemusic.api.services import credits as credits_service, users as user_service, voice_models as voice_service
from acemusic.api.settings import ApiSettings
from acemusic.storage import get_storage_backend

TRAIN_URL = f"{API_V1_PREFIX}/voice-models/train"
LIST_URL = f"{API_V1_PREFIX}/voice-models"


def wav(freq: float = 200.0, seconds: float = 2.0, sample_rate: int = 44100, amplitude: float = 0.5) -> bytes:
    """A tone as a real WAV container."""
    t = np.arange(int(sample_rate * seconds)) / sample_rate
    buf = io.BytesIO()
    sf.write(buf, amplitude * np.sin(2 * np.pi * freq * t), sample_rate, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def _files(count: int = 3, **kwargs) -> list[tuple[str, tuple[str, bytes, str]]]:
    # Slightly different tones, as separate takes of one voice would be.
    return [("files", (f"take{i}.wav", wav(freq=200.0 + 10 * i, **kwargs), "audio/wav")) for i in range(count)]


# ---------------------------------------------------------------------------
# Validation — runs in CI (no DB)
# ---------------------------------------------------------------------------


class TestValidation:
    async def _reject(self, files: list[tuple[str, bytes]]) -> str:
        with pytest.raises(voice_service.VoiceModelError) as exc:
            await voice_service.validate_references(files)
        return str(exc.value)

    async def test_three_valid_takes_are_accepted(self) -> None:
        refs = await voice_service.validate_references([("a.wav", wav(200)), ("b.wav", wav(210)), ("c.wav", wav(220))])
        assert len(refs) == 3
        assert all(r.sample_rate == 44100 for r in refs)

    @pytest.mark.parametrize("count", [0, 1, 11, 20])
    async def test_the_file_count_bounds_are_enforced(self, count: int) -> None:
        message = await self._reject([(f"{i}.wav", wav()) for i in range(count)])
        assert "reference files" in message

    async def test_a_file_below_16khz_is_rejected_and_named(self) -> None:
        # AC 2 asks for a *clear* error. "Invalid file" is useless when ten were
        # uploaded, so the message has to identify which one and why.
        message = await self._reject([("good.wav", wav()), ("thin.wav", wav(sample_rate=8000))])
        assert "thin.wav" in message
        assert "8000" in message
        assert "16000" in message

    async def test_a_silent_reference_is_rejected(self) -> None:
        # Otherwise this costs 10 credits and minutes of GPU time to learn nothing.
        message = await self._reject([("good.wav", wav()), ("silent.wav", wav(amplitude=0.0))])
        assert "silent.wav" in message

    async def test_a_body_that_is_not_audio_is_rejected(self) -> None:
        message = await self._reject([("good.wav", wav()), ("notes.wav", b"this is not audio")])
        assert "notes.wav" in message

    async def test_a_very_short_reference_is_rejected(self) -> None:
        message = await self._reject([("good.wav", wav()), ("blip.wav", wav(seconds=0.2))])
        assert "blip.wav" in message

    async def test_an_obvious_odd_one_out_is_rejected(self) -> None:
        # The mistake that actually happens: a drum loop among the vocal takes.
        message = await self._reject([("v1.wav", wav(200)), ("v2.wav", wav(210)), ("drums.wav", wav(9000))])
        assert "drums.wav" in message

    async def test_the_consistency_check_does_not_reject_ordinary_variation(self) -> None:
        # A false reject costs a usable model, which is worse than training on one
        # slightly odd take — so takes an octave apart must still pass.
        refs = await voice_service.validate_references(
            [("low.wav", wav(150)), ("mid.wav", wav(220)), ("high.wav", wav(300))]
        )
        assert len(refs) == 3


# ---------------------------------------------------------------------------
# Auth gate — runs in CI (no DB)
# ---------------------------------------------------------------------------


class TestAuthGate:
    def test_training_without_a_token_is_401(self) -> None:
        client = TestClient(create_app())
        resp = client.post(TRAIN_URL, files=_files(3), data={"name": "My voice"})
        assert resp.status_code == 401

    def test_listing_without_a_token_is_401(self) -> None:
        client = TestClient(create_app())
        assert client.get(LIST_URL).status_code == 401


def test_training_costs_the_documented_premium_amount() -> None:
    # The story sets 10; a silent change to this changes what people are charged.
    assert credits_service.VOICE_TRAINING_COST == 10.0


# ---------------------------------------------------------------------------
# Integration — real MongoDB
# ---------------------------------------------------------------------------


def _async_client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


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
    async with _async_client(create_app(settings)) as ac:
        yield ac


@pytest.fixture
def local_storage(monkeypatch, tmp_path):
    monkeypatch.setenv("ACEMUSIC_STORAGE_BACKEND", "local")
    monkeypatch.setenv("ACEMUSIC_STORAGE_LOCAL_ROOT", str(tmp_path))
    return tmp_path


def _auth_headers(user, settings: ApiSettings) -> dict[str, str]:
    token = create_access_token(
        user_id=str(user.id),
        email=user.email,
        subscription_tier=user.subscription_tier,
        settings=settings,
    )
    return {"Authorization": f"Bearer {token}"}


async def _make_user(email: str, credits: float = 100.0):
    user = await user_service.get_or_create_user(email=email, provider="google", oauth_id=f"g-{email}", name="T")
    user.credits_balance = credits
    await user.save()
    return user


@pytest.mark.integration
class TestTraining:
    async def test_three_valid_files_return_a_job_id(self, client, settings, local_storage) -> None:
        user = await _make_user("train@example.com")

        resp = await client.post(
            TRAIN_URL,
            headers=_auth_headers(user, settings),
            files=_files(3),
            data={"name": "My voice", "description": "warm baritone"},
        )

        assert resp.status_code == 202, resp.text
        body = resp.json()
        assert body["job_id"]
        assert body["voice_model"]["name"] == "My voice"
        assert body["voice_model"]["reference_count"] == 3
        assert body["voice_model"]["status"] == VoiceModelStatus.QUEUED.value
        assert body["credits_charged"] == 10.0

        # The job really exists and is claimable by a worker.
        job = await Job.get(body["job_id"])
        assert job is not None
        assert job.job_type == "voice_training"
        assert job.input_params["voice_model_id"] == body["voice_model"]["id"]

        # And the references are in storage, all three of them.
        model = await VoiceModel.get(body["voice_model"]["id"])
        assert len(model.reference_paths) == 3
        storage = get_storage_backend()
        for path in model.reference_paths:
            assert len(storage.download(path)) > 0

    async def test_ten_credits_are_deducted_on_submission(self, client, settings, local_storage) -> None:
        user = await _make_user("charged@example.com", credits=25.0)

        resp = await client.post(
            TRAIN_URL,
            headers=_auth_headers(user, settings),
            files=_files(3),
            data={"name": "Voice"},
        )
        assert resp.status_code == 202, resp.text

        fresh = await User.get(user.id)
        assert fresh.credits_balance == 15.0

    async def test_insufficient_credits_returns_402_and_charges_nothing(self, client, settings, local_storage) -> None:
        user = await _make_user("broke@example.com", credits=3.0)

        resp = await client.post(
            TRAIN_URL,
            headers=_auth_headers(user, settings),
            files=_files(3),
            data={"name": "Voice"},
        )

        assert resp.status_code == 402
        fresh = await User.get(user.id)
        assert fresh.credits_balance == 3.0
        assert await VoiceModel.find_all().count() == 0

    async def test_a_rejected_upload_costs_nothing(self, client, settings, local_storage) -> None:
        # The order of validation is the behaviour: an 8kHz file must be refused
        # *before* the balance is touched.
        user = await _make_user("rejected@example.com", credits=50.0)

        resp = await client.post(
            TRAIN_URL,
            headers=_auth_headers(user, settings),
            files=[
                ("files", ("ok.wav", wav(), "audio/wav")),
                ("files", ("thin.wav", wav(sample_rate=8000), "audio/wav")),
            ],
            data={"name": "Voice"},
        )

        assert resp.status_code == 422
        assert "thin.wav" in resp.json()["detail"]

        fresh = await User.get(user.id)
        assert fresh.credits_balance == 50.0, "a rejected upload was charged for"
        assert await VoiceModel.find_all().count() == 0

    @pytest.mark.parametrize("count", [1, 11])
    async def test_wrong_file_counts_are_refused_without_charge(
        self, client, settings, local_storage, count: int
    ) -> None:
        user = await _make_user(f"count{count}@example.com", credits=50.0)

        resp = await client.post(
            TRAIN_URL,
            headers=_auth_headers(user, settings),
            files=_files(count),
            data={"name": "Voice"},
        )

        assert resp.status_code == 422
        fresh = await User.get(user.id)
        assert fresh.credits_balance == 50.0

    async def test_a_failed_run_refunds_what_it_charged(self, client, settings, local_storage) -> None:
        # AC 4's second half, and the easiest thing to get wrong.
        user = await _make_user("refund@example.com", credits=40.0)

        resp = await client.post(
            TRAIN_URL, headers=_auth_headers(user, settings), files=_files(3), data={"name": "Voice"}
        )
        assert resp.status_code == 202
        assert (await User.get(user.id)).credits_balance == 30.0

        model = await VoiceModel.get(resp.json()["voice_model"]["id"])
        await voice_service.fail_training(model, "the GPU fell over")

        fresh = await User.get(user.id)
        assert fresh.credits_balance == 40.0, "a failed training run did not refund"

        failed = await VoiceModel.get(model.id)
        assert failed.status is VoiceModelStatus.FAILED
        assert "GPU" in failed.error
        # A failed model is not usable, whatever else is true of it.
        assert not failed.is_usable

    async def test_a_refund_uses_what_was_charged_not_the_current_price(
        self, client, settings, local_storage, monkeypatch
    ) -> None:
        # If the price changes between charging and failing, the musician gets back
        # what they actually paid.
        user = await _make_user("priced@example.com", credits=40.0)
        resp = await client.post(
            TRAIN_URL, headers=_auth_headers(user, settings), files=_files(3), data={"name": "Voice"}
        )
        assert resp.status_code == 202

        monkeypatch.setattr(credits_service, "VOICE_TRAINING_COST", 999.0)

        model = await VoiceModel.get(resp.json()["voice_model"]["id"])
        await voice_service.fail_training(model, "boom")

        fresh = await User.get(user.id)
        assert fresh.credits_balance == 40.0, "the refund used the new price, not the charged one"

    async def test_a_model_needs_weights_to_count_as_usable(self, client, settings, local_storage) -> None:
        # "Job completed" and "voice is usable" are different claims.
        user = await _make_user("usable@example.com")
        resp = await client.post(
            TRAIN_URL, headers=_auth_headers(user, settings), files=_files(3), data={"name": "Voice"}
        )
        model = await VoiceModel.get(resp.json()["voice_model"]["id"])

        model.status = VoiceModelStatus.READY
        await model.save()
        assert not (await VoiceModel.get(model.id)).is_usable, "ready with no weights read as usable"

        model.weights_path = "somewhere/lora.safetensors"
        await model.save()
        assert (await VoiceModel.get(model.id)).is_usable


@pytest.mark.integration
class TestLibraryScoping:
    async def test_a_user_only_sees_their_own_models(self, client, settings, local_storage) -> None:
        mine = await _make_user("mine@example.com")
        theirs = await _make_user("theirs@example.com")

        for user, name in ((mine, "Mine"), (theirs, "Theirs")):
            resp = await client.post(
                TRAIN_URL, headers=_auth_headers(user, settings), files=_files(3), data={"name": name}
            )
            assert resp.status_code == 202, resp.text

        listed = await client.get(LIST_URL, headers=_auth_headers(mine, settings))
        assert listed.status_code == 200
        assert [m["name"] for m in listed.json()] == ["Mine"]

    async def test_another_users_model_cannot_be_fetched_by_id(self, client, settings, local_storage) -> None:
        owner = await _make_user("owner2@example.com")
        intruder = await _make_user("intruder2@example.com")

        resp = await client.post(
            TRAIN_URL, headers=_auth_headers(owner, settings), files=_files(3), data={"name": "Private"}
        )
        model_id = resp.json()["voice_model"]["id"]

        assert await voice_service.find_owned_model(model_id, str(owner.id)) is not None
        assert await voice_service.find_owned_model(model_id, str(intruder.id)) is None

    async def test_a_malformed_id_is_not_found_rather_than_an_error(self, client, settings) -> None:
        user = await _make_user("malformed@example.com")
        assert await voice_service.find_owned_model("not-an-object-id", str(user.id)) is None


# ---------------------------------------------------------------------------
# The training worker — real MongoDB, stubbed ACE-Step
# ---------------------------------------------------------------------------


def _acestep_stub(
    *, training_error: str | None = None, exports: bool = True, ever_starts: bool = True, samples: int = 3
):
    """A stand-in for ACE-Step's real training API.

    The shapes here are ACE-Step's own, taken from its request models and a live
    probe of the running server -- **not** invented. Training reports a *boolean*
    ``is_training`` alongside a human ``status`` string ("Idle"), not a
    "completed"/"failed" word; an earlier version of this stub guessed the latter
    and the worker was written to match the guess, so both agreed and both were
    wrong.

    The status sequence is: not started -> training -> finished.
    """
    calls = {"status": 0, "labelled": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path

        if path.endswith("/dataset/scan"):
            assert "audio_dir" in request.read().decode(), "scan needs an audio_dir"
            return httpx.Response(
                200,
                json={"data": {"num_samples": 3, "samples": [{"index": i, "labeled": False} for i in range(3)]}},
            )

        if "/dataset/sample/" in path:
            # Labelling is not optional: preprocessing skips unlabelled samples and
            # returns "No labeled samples to preprocess".
            assert "sample_idx" in request.read().decode(), "labelling needs a sample_idx"
            calls["labelled"] += 1
            return httpx.Response(200, json={"data": {"message": "updated"}})

        if path.endswith("/dataset/preprocess_async"):
            assert calls["labelled"] == 3, "preprocess ran before every sample was labelled"
            assert "output_dir" in request.read().decode(), "preprocess needs an output_dir"
            return httpx.Response(200, json={"data": {"task_id": "ds-1"}})

        if "/dataset/preprocess_status" in path:
            return httpx.Response(200, json={"data": {"status": "completed", "current": 3, "total": 3}})

        if path.endswith("/training/start"):
            body = request.read().decode()
            assert "tensor_dir" in body, "training/start needs a tensor_dir"
            assert "lora_output_dir" in body, "training/start needs a lora_output_dir"
            return httpx.Response(200, json={"data": {"started": True}})

        if path.endswith("/training/status"):
            calls["status"] += 1
            if training_error:
                return httpx.Response(200, json={"data": {"is_training": False, "error": training_error}})
            if not ever_starts:
                return httpx.Response(200, json={"data": {"is_training": False, "status": "Idle", "error": None}})
            # First poll is mid-run, then it finishes.
            running = calls["status"] < 2
            return httpx.Response(
                200,
                json={
                    "data": {
                        "is_training": running,
                        "status": "Training" if running else "Idle",
                        "current_step": 10 * calls["status"],
                        "current_epoch": 1,
                        "current_loss": 0.42,
                        "estimated_time_remaining": 30.0,
                        "error": None,
                    }
                },
            )

        if path.endswith("/training/export"):
            if not exports:
                return httpx.Response(404, json={"detail": "No trained model found"})
            body = request.read().decode()
            assert "export_path" in body, "export needs an export_path"
            assert "lora_output_dir" in body, "export needs a lora_output_dir"
            return httpx.Response(200, json={"data": {"export_path": "demo/voice.safetensors"}})

        return httpx.Response(404, json={"error": f"unexpected {path}"})

    return httpx.MockTransport(handler)


@pytest.mark.integration
class TestTrainingWorker:
    async def _queued(self, client, settings, user):
        resp = await client.post(
            TRAIN_URL, headers=_auth_headers(user, settings), files=_files(3), data={"name": "Voice"}
        )
        assert resp.status_code == 202, resp.text
        body = resp.json()
        return await VoiceModel.get(body["voice_model"]["id"]), await Job.get(body["job_id"])

    async def _run(self, job, monkeypatch, **stub_kwargs):
        from acemusic.api.tasks import voice_training

        transport = _acestep_stub(**stub_kwargs)
        original = httpx.AsyncClient

        def patched(*args, **kwargs):
            kwargs["transport"] = transport
            return original(*args, **kwargs)

        monkeypatch.setattr(voice_training.httpx, "AsyncClient", patched)
        return await voice_training.process_voice_training_job(
            job,
            storage=get_storage_backend(),
            base_url="http://acestep.test",
            poll_interval=0.0,
            poll_timeout=5.0,
        )

    async def test_a_successful_run_stores_weights_and_marks_the_voice_ready(
        self, client, settings, local_storage, monkeypatch
    ) -> None:
        user = await _make_user("worker-ok@example.com", credits=40.0)
        model, job = await self._queued(client, settings, user)

        result = await self._run(job, monkeypatch)

        # The export path is a directory; the loadable PEFT adapter is inside it,
        # and pointing /v1/lora/load at the root is rejected. Verified against a
        # real trained model, so this is the path that actually loads.
        assert result["weights_path"] == "demo/voice.safetensors/adapter"
        fresh = await VoiceModel.get(model.id)
        assert fresh.status is VoiceModelStatus.READY
        assert fresh.is_usable, "a completed run did not produce a usable voice"
        # A successful run keeps the charge.
        assert (await User.get(user.id)).credits_balance == 30.0

    async def test_a_failed_run_refunds_and_records_why(self, client, settings, local_storage, monkeypatch) -> None:
        user = await _make_user("worker-fail@example.com", credits=40.0)
        model, job = await self._queued(client, settings, user)
        assert (await User.get(user.id)).credits_balance == 30.0

        with pytest.raises(Exception):
            await self._run(job, monkeypatch, training_error="CUDA out of memory")

        fresh = await VoiceModel.get(model.id)
        assert fresh.status is VoiceModelStatus.FAILED
        assert fresh.error
        assert not fresh.is_usable
        assert (await User.get(user.id)).credits_balance == 40.0, "a failed run did not refund"

    async def test_training_that_reports_success_but_exports_nothing_is_a_failure(
        self, client, settings, local_storage, monkeypatch
    ) -> None:
        # "Completed" and "produced a usable voice" are different claims; a run
        # with no weights must not leave a model that looks ready.
        user = await _make_user("worker-noweights@example.com", credits=40.0)
        model, job = await self._queued(client, settings, user)

        with pytest.raises(Exception):
            await self._run(job, monkeypatch, exports=False)

        fresh = await VoiceModel.get(model.id)
        assert fresh.status is VoiceModelStatus.FAILED
        assert not fresh.is_usable
        assert (await User.get(user.id)).credits_balance == 40.0

    async def test_a_run_that_never_starts_is_a_failure_not_a_success(
        self, client, settings, local_storage, monkeypatch
    ) -> None:
        # is_training reads false both *before* a run begins and *after* it ends.
        # Treating the first as "already finished" would report success for a run
        # that never happened -- and keep the credits.
        from acemusic.api.tasks import voice_training

        monkeypatch.setattr(voice_training, "TRAINING_START_GRACE_S", 0.0)

        user = await _make_user("worker-nostart@example.com", credits=40.0)
        model, job = await self._queued(client, settings, user)

        with pytest.raises(Exception):
            await self._run(job, monkeypatch, ever_starts=False)

        fresh = await VoiceModel.get(model.id)
        assert fresh.status is VoiceModelStatus.FAILED
        assert (await User.get(user.id)).credits_balance == 40.0

    async def test_a_job_pointing_at_a_missing_model_fails_loudly(
        self, client, settings, local_storage, monkeypatch
    ) -> None:
        user = await _make_user("worker-orphan@example.com")
        _, job = await self._queued(client, settings, user)
        job.input_params = {"voice_model_id": "000000000000000000000000"}
        await job.save()

        with pytest.raises(Exception):
            await self._run(job, monkeypatch)
