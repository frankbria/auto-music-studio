"""Automated content screening (US-27.1).

Every generation entry point screens its text before charging credits: a blocked
request is a 422 that names the category and leaves the balance untouched; a
borderline one generates, with the flag carried to the clip. Rules live in Mongo,
so an admin edit applies to the very next request.
"""

import httpx
import pytest
from beanie import PydanticObjectId

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.models import Clip, Job, Workspace
from acemusic.api.services import routing, screening, users as user_service
from acemusic.api.settings import ApiSettings
from acemusic.api.tasks.processor import JobProcessor
from tests.users import make_user

GENERATE_URL = f"{API_V1_PREFIX}/generate"
RULES_URL = f"{API_V1_PREFIX}/admin/screening-rules"


class TestMatch:
    """The pure matcher, independent of storage."""

    RULES = screening.ScreeningRules(
        rules=[
            screening.Rule(term="sieg heil", category="hate speech", action="block"),
            screening.Rule(term="rape", category="sexual violence", action="flag"),
            screening.Rule(term="genocide", category="violence", action="flag"),
        ],
        allow_terms=["rape awareness"],
        block_threshold=2,
    )

    def test_clean_text_passes(self):
        result = screening.match(self.RULES, ["an upbeat indie pop song about summer"])
        assert result.blocked is False
        assert result.flags == []

    def test_block_term_blocks_case_insensitively(self):
        result = screening.match(self.RULES, ["a march", "chant SIEG  HEIL loudly"])
        assert result.blocked is True
        assert result.categories == ["hate speech"]

    def test_matches_whole_words_only(self):
        assert screening.match(self.RULES, ["drape the stage in grapes"]).flags == []

    def test_flag_term_flags_without_blocking(self):
        result = screening.match(self.RULES, ["a protest song about rape"])
        assert result.blocked is False
        assert result.flags == ["sexual violence"]

    def test_allow_term_suppresses_a_match(self):
        assert screening.match(self.RULES, ["a Rape  Awareness charity single"]).flags == []

    def test_flag_hits_at_threshold_escalate_to_block(self):
        result = screening.match(self.RULES, ["rape", "genocide"])
        assert result.blocked is True
        assert result.categories == ["sexual violence", "violence"]

    def test_zero_threshold_never_escalates(self):
        rules = self.RULES.model_copy(update={"block_threshold": 0})
        assert screening.match(rules, ["rape", "genocide"]).blocked is False

    @pytest.mark.parametrize("text", ["chant sieg-heil", "SIEG.HEIL", "sieg_heil", "chant sieg heíl"])
    def test_punctuation_and_accents_do_not_evade(self, text):
        assert screening.match(self.RULES, [text]).blocked is True

    def test_a_phrase_does_not_span_two_fields(self):
        assert screening.match(self.RULES, ["a march for sieg", "heil"]).blocked is False

    def test_none_texts_are_ignored(self):
        assert screening.match(self.RULES, [None, ""]).flags == []


@pytest.fixture(autouse=True)
def _local_compute_available(monkeypatch):
    async def _up(*_args, **_kwargs):
        return True

    async def _down(*_args, **_kwargs):
        return False

    monkeypatch.setattr(routing, "check_local_availability", _up)
    monkeypatch.setattr(routing, "check_remote_availability", _down)


@pytest.fixture
def settings(mongo_db, mongo_settings) -> ApiSettings:
    return mongo_settings.model_copy(
        update={"jwt_secret_key": "test-secret-key-at-least-32-bytes-long-xx", "job_processor_enabled": False}
    )


@pytest.fixture
async def client(settings):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(settings)), base_url="http://t") as ac:
        yield ac


def _auth(user, settings: ApiSettings) -> dict[str, str]:
    token = create_access_token(
        user_id=str(user.id), email=user.email, subscription_tier=user.subscription_tier, settings=settings
    )
    return {"Authorization": f"Bearer {token}"}


async def _balance(user) -> float:
    return (await user_service.get_user_by_id(str(user.id))).credits_balance


@pytest.mark.integration
class TestGenerateScreening:
    async def test_prohibited_prompt_is_blocked_with_an_explanation_and_no_charge(self, client, settings):
        user = await make_user("screen-block@example.com")
        before = user.credits_balance
        resp = await client.post(
            GENERATE_URL, json={"prompt": "a rally anthem, sieg heil"}, headers=_auth(user, settings)
        )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert "hate speech" in detail
        assert "wasn't generated" in detail
        assert await Job.find(Job.user_id == user.id).to_list() == []
        assert await _balance(user) == before

    async def test_vocal_language_is_screened(self, client, settings):
        user = await make_user("screen-lang@example.com")
        resp = await client.post(
            GENERATE_URL, json={"prompt": "pop", "vocal_language": "heil hitler"}, headers=_auth(user, settings)
        )
        assert resp.status_code == 422

    async def test_prohibited_lyrics_are_blocked(self, client, settings):
        user = await make_user("screen-lyrics@example.com")
        resp = await client.post(
            GENERATE_URL,
            json={"prompt": "folk ballad", "lyrics": "[Verse]\nwe share child porn"},
            headers=_auth(user, settings),
        )
        assert resp.status_code == 422

    async def test_normal_prompt_passes_unflagged(self, client, settings):
        user = await make_user("screen-clean@example.com")
        resp = await client.post(
            GENERATE_URL, json={"prompt": "a killer synthwave groove at night"}, headers=_auth(user, settings)
        )
        assert resp.status_code == 202
        job = await Job.get(PydanticObjectId(resp.json()["job_id"]))
        assert "moderation_flags" not in job.input_params

    async def test_borderline_prompt_generates_and_the_clip_carries_the_flag(self, client, settings):
        user = await make_user("screen-flag@example.com")
        before = user.credits_balance
        resp = await client.post(
            GENERATE_URL, json={"prompt": "a dark song about suicide and grief"}, headers=_auth(user, settings)
        )
        assert resp.status_code == 202
        job = await Job.get(PydanticObjectId(resp.json()["job_id"]))
        assert job.input_params["moderation_flags"] == ["self-harm"]
        assert await _balance(user) < before

        clip = JobProcessor._build_clip(job, job.input_params, PydanticObjectId(), "p.wav", "wav")
        assert clip.moderation_flags == ["self-harm"]

        # The status poll rebuilds the request from input_params; the flag must not break its estimate.
        status_resp = await client.get(f"{API_V1_PREFIX}/jobs/{job.id}/status", headers=_auth(user, settings))
        assert status_resp.json()["estimated_time_seconds"] == resp.json()["estimated_time_seconds"]

    async def test_preset_supplied_text_is_screened(self, client, settings):
        user = await make_user("screen-preset@example.com")
        preset = await client.post(
            f"{API_V1_PREFIX}/presets",
            json={"name": "bad", "style": "white power rock"},
            headers=_auth(user, settings),
        )
        assert preset.status_code == 201, preset.text
        resp = await client.post(
            GENERATE_URL,
            json={"prompt": "rock", "preset_id": preset.json()["id"]},
            headers=_auth(user, settings),
        )
        assert resp.status_code == 422


async def _user_with_clip(email: str):
    user = await make_user(email, credits_balance=10.0)
    workspace = Workspace(name="WS", user_id=user.id)
    await workspace.insert()
    clip_id = PydanticObjectId()
    clip = Clip(
        id=clip_id,
        user_id=user.id,
        workspace_id=workspace.id,
        file_path=f"{user.id}/{workspace.id}/clips/{clip_id}.wav",
        format="wav",
        duration=10.0,
    )
    await clip.insert()
    return user, clip


@pytest.mark.integration
class TestOtherEntryPoints:
    async def test_iterative_blocked_style_costs_nothing(self, client, settings):
        user, clip = await _user_with_clip("screen-remix@example.com")
        resp = await client.post(
            f"{API_V1_PREFIX}/clips/{clip.id}/remix", json={"style": "heil hitler"}, headers=_auth(user, settings)
        )
        assert resp.status_code == 422
        assert await Job.find(Job.user_id == user.id).to_list() == []
        assert await _balance(user) == 10.0

    async def test_iterative_borderline_is_flagged_on_the_job(self, client, settings):
        user, clip = await _user_with_clip("screen-remix-flag@example.com")
        resp = await client.post(
            f"{API_V1_PREFIX}/clips/{clip.id}/remix", json={"style": "terrorist drill"}, headers=_auth(user, settings)
        )
        assert resp.status_code == 202
        job = await Job.get(PydanticObjectId(resp.json()["job_id"]))
        assert job.input_params["moderation_flags"] == ["violent extremism"]

    async def test_iterative_screens_the_source_clip_title_the_worker_prompts_with(self, client, settings):
        # extend carries no text of its own: the worker prompts ACE-Step with the clip's title/tags.
        user, clip = await _user_with_clip("screen-extend-title@example.com")
        await clip.set({Clip.title: "Sieg Heil march"})
        resp = await client.post(
            f"{API_V1_PREFIX}/clips/{clip.id}/extend", json={"duration": "30s"}, headers=_auth(user, settings)
        )
        assert resp.status_code == 422
        assert await _balance(user) == 10.0

    async def test_full_song_screens_the_seed_lyrics_it_inherits(self, client, settings):
        user, clip = await _user_with_clip("screen-fullsong@example.com")
        await clip.set({Clip.lyrics: "[Chorus]\nwhite power"})
        resp = await client.post(f"{API_V1_PREFIX}/clips/{clip.id}/full-song", json={}, headers=_auth(user, settings))
        assert resp.status_code == 422, resp.text
        assert await _balance(user) == 10.0

    async def test_a_phrase_split_across_tags_is_screened_as_the_joined_prompt(self, client, settings):
        user, clip = await _user_with_clip("screen-split-tags@example.com")
        await clip.set({Clip.style_tags: ["sieg", "heil"]})
        resp = await client.post(
            f"{API_V1_PREFIX}/clips/{clip.id}/extend", json={"duration": "30s"}, headers=_auth(user, settings)
        )
        assert resp.status_code == 422
        assert await _balance(user) == 10.0

    async def test_mashup_flags_a_borderline_tag_on_any_source(self, client, settings):
        user, first = await _user_with_clip("screen-mashup@example.com")
        second = Clip(
            user_id=user.id,
            workspace_id=first.workspace_id,
            file_path="b.wav",
            format="wav",
            duration=10.0,
            style_tags=["genocide doom"],
        )
        await second.insert()
        resp = await client.post(
            f"{API_V1_PREFIX}/mashup",
            json={"clip_ids": [str(first.id), str(second.id)]},
            headers=_auth(user, settings),
        )
        assert resp.status_code == 202, resp.text
        job = await Job.get(PydanticObjectId(resp.json()["job_id"]))
        assert job.input_params["moderation_flags"] == ["violent extremism"]

    async def test_artwork_prompt_is_screened(self, client, settings):
        user, clip = await _user_with_clip("screen-art@example.com")
        resp = await client.post(
            f"{API_V1_PREFIX}/clips/{clip.id}/artwork/generate",
            json={"style_prompt": "child pornography"},
            headers=_auth(user, settings),
        )
        assert resp.status_code == 422
        assert await Job.find(Job.user_id == user.id).to_list() == []

    async def test_artwork_prompt_derived_from_the_clip_title_is_screened(self, client, settings):
        user, clip = await _user_with_clip("screen-art-title@example.com")
        await clip.set({Clip.title: "White-Power rally"})
        resp = await client.post(
            f"{API_V1_PREFIX}/clips/{clip.id}/artwork/generate", json={}, headers=_auth(user, settings)
        )
        assert resp.status_code == 422
        assert await Job.find(Job.user_id == user.id).to_list() == []

    async def test_borderline_artwork_prompt_is_flagged_on_the_job(self, client, settings):
        user, clip = await _user_with_clip("screen-art-flag@example.com")
        resp = await client.post(
            f"{API_V1_PREFIX}/clips/{clip.id}/artwork/generate",
            json={"style_prompt": "terrorist propaganda aesthetic, satirical"},
            headers=_auth(user, settings),
        )
        assert resp.status_code == 202
        job = await Job.get(PydanticObjectId(resp.json()["job_id"]))
        assert job.input_params["moderation_flags"] == ["violent extremism"]

    @pytest.mark.parametrize(
        ("prompt", "status", "flags"),
        [("sieg heil parade", 422, None), ("a genocide memorial montage", 202, ["violent extremism"])],
    )
    async def test_video_prompt_is_screened_before_charging(self, mongo_settings, mongo_db, prompt, status, flags):
        s = mongo_settings.model_copy(
            update={
                "jwt_secret_key": "test-secret-key-at-least-32-bytes-long-xx",
                "job_processor_enabled": False,
                "video_api_url": "http://video.invalid",
                "video_api_key": "k",
            }
        )
        user, clip = await _user_with_clip("screen-video@example.com")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(s)), base_url="http://t") as ac:
            resp = await ac.post(
                f"{API_V1_PREFIX}/videos/generate",
                json={"clip_id": str(clip.id), "prompt": prompt},
                headers=_auth(user, s),
            )
        assert resp.status_code == status, resp.text
        if flags is None:
            assert await _balance(user) == 10.0
        else:
            job = await Job.get(PydanticObjectId(resp.json()["job_id"]))
            assert job.input_params["moderation_flags"] == flags


@pytest.mark.integration
class TestAdminRules:
    async def test_non_admin_cannot_read_or_change_rules(self, client, settings):
        user = await make_user("screen-nonadmin@example.com")
        assert (await client.get(RULES_URL, headers=_auth(user, settings))).status_code == 403
        assert (await client.put(RULES_URL, json={}, headers=_auth(user, settings))).status_code == 403

    async def test_admin_reads_the_seeded_defaults(self, client, settings):
        admin = await make_user("screen-admin-read@example.com", is_admin=True)
        resp = await client.get(RULES_URL, headers=_auth(admin, settings))
        assert resp.status_code == 200
        body = resp.json()
        assert {"term": "sieg heil", "category": "hate speech", "action": "block"} in body["rules"]
        assert body["block_threshold"] == screening.DEFAULT_BLOCK_THRESHOLD

    async def test_admin_edit_applies_to_the_next_request(self, client, settings):
        admin = await make_user("screen-admin@example.com", is_admin=True)
        user = await make_user("screen-after-edit@example.com")
        prompt = {"prompt": "a banana anthem"}
        assert (await client.post(GENERATE_URL, json=prompt, headers=_auth(user, settings))).status_code == 202

        current = (await client.get(RULES_URL, headers=_auth(admin, settings))).json()
        current["rules"].append({"term": "banana", "category": "test category", "action": "block"})
        current["allow_terms"] = ["suicide squad"]
        put = await client.put(RULES_URL, json=current, headers=_auth(admin, settings))
        assert put.status_code == 200

        blocked = await client.post(GENERATE_URL, json=prompt, headers=_auth(user, settings))
        assert blocked.status_code == 422
        assert "test category" in blocked.json()["detail"]
        allowed = await client.post(
            GENERATE_URL, json={"prompt": "suicide squad soundtrack"}, headers=_auth(user, settings)
        )
        job = await Job.get(PydanticObjectId(allowed.json()["job_id"]))
        assert "moderation_flags" not in job.input_params

    async def test_invalid_rules_are_rejected(self, client, settings):
        admin = await make_user("screen-admin-bad@example.com", is_admin=True)
        bad = {"rules": [{"term": " ", "category": "x", "action": "block"}], "allow_terms": [], "block_threshold": 0}
        assert (await client.put(RULES_URL, json=bad, headers=_auth(admin, settings))).status_code == 422
        worse = {"rules": [{"term": "x", "category": "x", "action": "nuke"}], "allow_terms": [], "block_threshold": 0}
        assert (await client.put(RULES_URL, json=worse, headers=_auth(admin, settings))).status_code == 422
