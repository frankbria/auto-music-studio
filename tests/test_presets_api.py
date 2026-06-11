"""Tests for the preset CRUD endpoints and preset-aware generation (US-9.5, issue #79).

The 401 auth-gate tests run in CI (the router dependency rejects before any DB
access; plain ``TestClient`` does not run the lifespan). The CRUD and generate
tests are ``integration``: they drive the real app with ``httpx.AsyncClient``
over a local MongoDB (``mongo_db``), mirroring ``tests/test_workspaces_api.py``.
"""

import httpx
import pytest
from beanie import PydanticObjectId
from fastapi.testclient import TestClient

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.models import Job, Preset
from acemusic.api.services import users as user_service
from acemusic.api.settings import ApiSettings

PRESETS_URL = f"{API_V1_PREFIX}/presets"
GENERATE_URL = f"{API_V1_PREFIX}/generate"

# A representative full parameter snapshot used across tests.
FULL_PARAMS = {
    "style": "lofi hip hop",
    "lyrics": "la la la",
    "vocal_language": "en",
    "instrumental": True,
    "bpm": 90,
    "key": "C minor",
    "time_signature": "4/4",
    "duration": 60.0,
    "seed": 1234,
    "inference_steps": 32,
    "weirdness": 80,
    "style_influence": 20,
    "format": "flac",
    "thinking": True,
    "mode": "song",
}


# ---------------------------------------------------------------------------
# Auth gate — runs in CI (no DB)
# ---------------------------------------------------------------------------


class TestAuthGate:
    @pytest.mark.parametrize(
        ("method", "url"),
        [
            ("GET", PRESETS_URL),
            ("POST", PRESETS_URL),
            ("GET", f"{PRESETS_URL}/{PydanticObjectId()}"),
            ("PATCH", f"{PRESETS_URL}/{PydanticObjectId()}"),
            ("DELETE", f"{PRESETS_URL}/{PydanticObjectId()}"),
        ],
    )
    def test_missing_auth_header_returns_401(self, method: str, url: str) -> None:
        client = TestClient(create_app())
        resp = client.request(method, url)
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Integration — real MongoDB
# ---------------------------------------------------------------------------


def _async_client(app) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


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


def _auth_headers(user, settings: ApiSettings) -> dict[str, str]:
    token = create_access_token(
        user_id=str(user.id),
        email=user.email,
        subscription_tier=user.subscription_tier,
        settings=settings,
    )
    return {"Authorization": f"Bearer {token}"}


async def _make_user(email: str):
    return await user_service.get_or_create_user(email=email, provider="google", oauth_id=f"g-{email}", name="T")


async def _insert_preset(user, name: str = "Default", **params) -> Preset:
    preset = Preset(user_id=user.id, name=name, **params)
    await preset.insert()
    return preset


async def _get_job(job_id: str) -> Job:
    job = await Job.get(PydanticObjectId(job_id))
    assert job is not None
    return job


@pytest.mark.integration
class TestCreatePreset:
    async def test_create_with_full_params_returns_201_and_echoes_all(self, client, settings) -> None:
        user = await _make_user("preset-create@example.com")
        resp = await client.post(
            PRESETS_URL,
            json={"name": "My Lofi", **FULL_PARAMS},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["id"]
        assert body["name"] == "My Lofi"
        assert body["created_at"]
        for field, value in FULL_PARAMS.items():
            assert body[field] == value, f"field {field!r}: {body[field]!r} != {value!r}"

    async def test_create_minimal_returns_201_with_null_params(self, client, settings) -> None:
        user = await _make_user("preset-create-min@example.com")
        resp = await client.post(PRESETS_URL, json={"name": "Bare"}, headers=_auth_headers(user, settings))
        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "Bare"
        assert body["style"] is None
        assert body["bpm"] is None
        assert body["instrumental"] is None

    async def test_bpm_auto_is_accepted(self, client, settings) -> None:
        user = await _make_user("preset-create-auto@example.com")
        resp = await client.post(
            PRESETS_URL, json={"name": "Auto", "bpm": "auto"}, headers=_auth_headers(user, settings)
        )
        assert resp.status_code == 201
        assert resp.json()["bpm"] == "auto"

    async def test_duplicate_name_for_same_user_returns_409(self, client, settings) -> None:
        user = await _make_user("preset-dup@example.com")
        headers = _auth_headers(user, settings)
        assert (await client.post(PRESETS_URL, json={"name": "Beats"}, headers=headers)).status_code == 201
        assert (await client.post(PRESETS_URL, json={"name": "Beats"}, headers=headers)).status_code == 409

    async def test_same_name_for_different_users_is_allowed(self, client, settings) -> None:
        alice = await _make_user("preset-alice@example.com")
        bob = await _make_user("preset-bob@example.com")
        assert (
            await client.post(PRESETS_URL, json={"name": "Beats"}, headers=_auth_headers(alice, settings))
        ).status_code == 201
        assert (
            await client.post(PRESETS_URL, json={"name": "Beats"}, headers=_auth_headers(bob, settings))
        ).status_code == 201

    @pytest.mark.parametrize(
        "payload",
        [
            {},  # missing name
            {"name": ""},
            {"name": "   "},
            {"name": "X", "bpm": 300},  # out of range
            {"name": "X", "weirdness": 101},
            {"name": "X", "format": "ogg"},  # not a valid format
            {"name": "X", "time_signature": "13/8"},
            {"name": "X", "nope": True},  # unknown field
        ],
    )
    async def test_invalid_payload_returns_422(self, client, settings, payload: dict) -> None:
        user = await _make_user("preset-invalid@example.com")
        resp = await client.post(PRESETS_URL, json=payload, headers=_auth_headers(user, settings))
        assert resp.status_code == 422


@pytest.mark.integration
class TestListPresets:
    async def test_lists_only_own_presets(self, client, settings) -> None:
        user = await _make_user("preset-list@example.com")
        other = await _make_user("preset-list-other@example.com")
        mine_a = await _insert_preset(user, "A", style="ambient")
        mine_b = await _insert_preset(user, "B")
        await _insert_preset(other, "Theirs")

        resp = await client.get(PRESETS_URL, headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        by_id = {p["id"]: p for p in body["presets"]}
        assert set(by_id) == {str(mine_a.id), str(mine_b.id)}
        assert by_id[str(mine_a.id)]["style"] == "ambient"

    async def test_empty_list_for_new_user(self, client, settings) -> None:
        user = await _make_user("preset-list-empty@example.com")
        resp = await client.get(PRESETS_URL, headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        assert resp.json() == {"presets": [], "total": 0}


@pytest.mark.integration
class TestGetPreset:
    async def test_get_own_preset_returns_all_saved_params(self, client, settings) -> None:
        user = await _make_user("preset-get@example.com")
        preset = await _insert_preset(user, "Mine", **FULL_PARAMS)

        resp = await client.get(f"{PRESETS_URL}/{preset.id}", headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == str(preset.id)
        assert body["name"] == "Mine"
        for field, value in FULL_PARAMS.items():
            assert body[field] == value, f"field {field!r}: {body[field]!r} != {value!r}"

    async def test_unknown_preset_returns_404(self, client, settings) -> None:
        user = await _make_user("preset-get-unknown@example.com")
        resp = await client.get(f"{PRESETS_URL}/{PydanticObjectId()}", headers=_auth_headers(user, settings))
        assert resp.status_code == 404

    async def test_malformed_id_returns_404(self, client, settings) -> None:
        user = await _make_user("preset-get-malformed@example.com")
        resp = await client.get(f"{PRESETS_URL}/not-an-object-id", headers=_auth_headers(user, settings))
        assert resp.status_code == 404

    async def test_other_users_preset_returns_404(self, client, settings) -> None:
        owner = await _make_user("preset-get-owner@example.com")
        other = await _make_user("preset-get-other@example.com")
        preset = await _insert_preset(owner, "Private")
        resp = await client.get(f"{PRESETS_URL}/{preset.id}", headers=_auth_headers(other, settings))
        assert resp.status_code == 404


@pytest.mark.integration
class TestUpdatePreset:
    async def test_partial_update_changes_only_sent_fields(self, client, settings) -> None:
        user = await _make_user("preset-patch@example.com")
        preset = await _insert_preset(user, "Mine", style="lofi", bpm=90, weirdness=80)

        resp = await client.patch(
            f"{PRESETS_URL}/{preset.id}",
            json={"bpm": 120},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["bpm"] == 120
        assert body["style"] == "lofi"
        assert body["weirdness"] == 80
        assert body["updated_at"] is not None

        fetched = await Preset.get(preset.id)
        assert fetched.bpm == 120
        assert fetched.style == "lofi"

    async def test_explicit_null_clears_a_param(self, client, settings) -> None:
        user = await _make_user("preset-patch-null@example.com")
        preset = await _insert_preset(user, "Mine", style="lofi", bpm=90)

        resp = await client.patch(
            f"{PRESETS_URL}/{preset.id}",
            json={"style": None},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["style"] is None
        assert body["bpm"] == 90

    async def test_rename_returns_updated_preset(self, client, settings) -> None:
        user = await _make_user("preset-rename@example.com")
        preset = await _insert_preset(user, "Old")
        resp = await client.patch(
            f"{PRESETS_URL}/{preset.id}",
            json={"name": "New"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "New"

    async def test_rename_to_existing_name_returns_409(self, client, settings) -> None:
        user = await _make_user("preset-rename-dup@example.com")
        await _insert_preset(user, "Taken")
        preset = await _insert_preset(user, "Original")
        resp = await client.patch(
            f"{PRESETS_URL}/{preset.id}",
            json={"name": "Taken"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 409

    async def test_null_name_returns_422(self, client, settings) -> None:
        user = await _make_user("preset-rename-null@example.com")
        preset = await _insert_preset(user, "Mine")
        resp = await client.patch(
            f"{PRESETS_URL}/{preset.id}",
            json={"name": None},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 422

    async def test_other_users_preset_returns_404(self, client, settings) -> None:
        owner = await _make_user("preset-patch-owner@example.com")
        other = await _make_user("preset-patch-other@example.com")
        preset = await _insert_preset(owner, "Private")
        resp = await client.patch(
            f"{PRESETS_URL}/{preset.id}",
            json={"bpm": 100},
            headers=_auth_headers(other, settings),
        )
        assert resp.status_code == 404
        assert (await Preset.get(preset.id)).bpm is None


@pytest.mark.integration
class TestDeletePreset:
    async def test_delete_returns_204_and_preset_is_gone(self, client, settings) -> None:
        user = await _make_user("preset-del@example.com")
        preset = await _insert_preset(user, "Doomed")
        headers = _auth_headers(user, settings)

        resp = await client.delete(f"{PRESETS_URL}/{preset.id}", headers=headers)
        assert resp.status_code == 204
        assert await Preset.get(preset.id) is None
        assert (await client.get(f"{PRESETS_URL}/{preset.id}", headers=headers)).status_code == 404

    async def test_unknown_preset_returns_404(self, client, settings) -> None:
        user = await _make_user("preset-del-unknown@example.com")
        resp = await client.delete(f"{PRESETS_URL}/{PydanticObjectId()}", headers=_auth_headers(user, settings))
        assert resp.status_code == 404

    async def test_other_users_preset_returns_404(self, client, settings) -> None:
        owner = await _make_user("preset-del-owner@example.com")
        other = await _make_user("preset-del-other@example.com")
        preset = await _insert_preset(owner, "Private")
        resp = await client.delete(f"{PRESETS_URL}/{preset.id}", headers=_auth_headers(other, settings))
        assert resp.status_code == 404
        assert await Preset.get(preset.id) is not None


@pytest.mark.integration
class TestMissingUser:
    """Token valid, but the referenced user no longer exists (stale token)."""

    def _orphan_headers(self, settings: ApiSettings) -> dict[str, str]:
        token = create_access_token(
            user_id=str(PydanticObjectId()),
            email="ghost@example.com",
            subscription_tier="free",
            settings=settings,
        )
        return {"Authorization": f"Bearer {token}"}

    async def test_create_returns_404(self, client, settings) -> None:
        resp = await client.post(PRESETS_URL, json={"name": "Orphan"}, headers=self._orphan_headers(settings))
        assert resp.status_code == 404


@pytest.mark.integration
class TestGenerateWithPreset:
    """`POST /api/v1/generate` with `preset_id` (US-9.5 acceptance criteria 2+3)."""

    async def test_preset_params_are_applied_to_job(self, client, settings) -> None:
        user = await _make_user("gen-preset@example.com")
        preset = await _insert_preset(user, "Lofi", style="lofi hip hop", bpm=90, weirdness=80, instrumental=True)

        resp = await client.post(
            GENERATE_URL,
            json={"prompt": "rainy evening", "preset_id": str(preset.id)},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 202
        job = await _get_job(resp.json()["job_id"])
        assert job.input_params["prompt"] == "rainy evening"
        assert job.input_params["style"] == "lofi hip hop"
        assert job.input_params["bpm"] == 90
        assert job.input_params["weirdness"] == 80
        assert job.input_params["instrumental"] is True
        # The preset reference itself is not a generation parameter.
        assert "preset_id" not in job.input_params

    async def test_explicit_params_override_preset_values(self, client, settings) -> None:
        user = await _make_user("gen-preset-override@example.com")
        preset = await _insert_preset(user, "Lofi", style="lofi hip hop", bpm=90, weirdness=80)

        resp = await client.post(
            GENERATE_URL,
            json={"prompt": "x", "preset_id": str(preset.id), "bpm": 140, "style": "drum and bass"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 202
        job = await _get_job(resp.json()["job_id"])
        assert job.input_params["bpm"] == 140
        assert job.input_params["style"] == "drum and bass"
        assert job.input_params["weirdness"] == 80  # untouched preset value still applies

    async def test_explicitly_sent_default_value_overrides_preset(self, client, settings) -> None:
        # weirdness=50 equals the schema default; because the client SENT it,
        # it must beat the preset's 80 (model_fields_set semantics, not
        # truthiness/None checks).
        user = await _make_user("gen-preset-default@example.com")
        preset = await _insert_preset(user, "Weird", weirdness=80, instrumental=True)

        resp = await client.post(
            GENERATE_URL,
            json={"prompt": "x", "preset_id": str(preset.id), "weirdness": 50, "instrumental": False},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 202
        job = await _get_job(resp.json()["job_id"])
        assert job.input_params["weirdness"] == 50
        assert job.input_params.get("instrumental", False) is False

    async def test_omitted_default_field_does_not_override_preset(self, client, settings) -> None:
        # The client did NOT send weirdness, so the schema default (50) must
        # not clobber the preset's snapshot.
        user = await _make_user("gen-preset-omitted@example.com")
        preset = await _insert_preset(user, "Weird", weirdness=80)

        resp = await client.post(
            GENERATE_URL,
            json={"prompt": "x", "preset_id": str(preset.id)},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 202
        job = await _get_job(resp.json()["job_id"])
        assert job.input_params["weirdness"] == 80

    async def test_preset_supplying_sound_mode_passes_deferred_validation(self, client, settings) -> None:
        # mode/sound_type coupling is validated after the merge, so a preset
        # may carry the whole sound configuration.
        user = await _make_user("gen-preset-sound@example.com")
        preset = await _insert_preset(user, "Loop", mode="sound", sound_type="loop", bpm=124)

        resp = await client.post(
            GENERATE_URL,
            json={"prompt": "house loop", "preset_id": str(preset.id)},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 202
        job = await _get_job(resp.json()["job_id"])
        assert job.input_params["mode"] == "sound"
        assert job.input_params["sound_type"] == "loop"

    async def test_invalid_merged_params_return_422(self, client, settings) -> None:
        # Preset bpm + explicit one-shot request: the merged result violates
        # the "no bpm for one-shot sounds" rule and must be rejected.
        user = await _make_user("gen-preset-merge-invalid@example.com")
        preset = await _insert_preset(user, "Tempo", bpm=120)

        resp = await client.post(
            GENERATE_URL,
            json={"prompt": "kick", "preset_id": str(preset.id), "mode": "sound", "sound_type": "one-shot"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 422

    async def test_unknown_preset_id_returns_404(self, client, settings) -> None:
        user = await _make_user("gen-preset-unknown@example.com")
        resp = await client.post(
            GENERATE_URL,
            json={"prompt": "x", "preset_id": str(PydanticObjectId())},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 404

    async def test_malformed_preset_id_returns_404(self, client, settings) -> None:
        user = await _make_user("gen-preset-malformed@example.com")
        resp = await client.post(
            GENERATE_URL,
            json={"prompt": "x", "preset_id": "not-an-object-id"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 404

    async def test_other_users_preset_id_returns_404(self, client, settings) -> None:
        owner = await _make_user("gen-preset-owner@example.com")
        other = await _make_user("gen-preset-other@example.com")
        preset = await _insert_preset(owner, "Private", bpm=100)
        resp = await client.post(
            GENERATE_URL,
            json={"prompt": "x", "preset_id": str(preset.id)},
            headers=_auth_headers(other, settings),
        )
        assert resp.status_code == 404

    async def test_generate_without_preset_id_is_unchanged(self, client, settings) -> None:
        user = await _make_user("gen-no-preset@example.com")
        resp = await client.post(
            GENERATE_URL,
            json={"prompt": "a calm piano ballad"},
            headers=_auth_headers(user, settings),
        )
        assert resp.status_code == 202
        job = await _get_job(resp.json()["job_id"])
        assert "preset_id" not in job.input_params
