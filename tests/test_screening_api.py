"""Automated content screening (US-27.1).

Every generation entry point screens its text before charging credits: a blocked
request is a 422 that names the category and leaves the balance untouched; a
borderline one generates, with the flag carried to the clip. Rules live in Mongo,
so an admin edit applies to the very next request.
"""

import inspect
from datetime import timedelta

import httpx
import pytest
from beanie import PydanticObjectId

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.models import (
    Clip,
    Job,
    Release,
    SoundCloudConnection,
    VisibilityState,
    VoiceModel,
    VoiceModelStatus,
    Workspace,
)
from acemusic.api.models.common import utcnow
from acemusic.api.services import clips as clip_service, routing, screening, soundcloud, users as user_service
from acemusic.api.services.tiers import PRO
from acemusic.api.settings import ApiSettings
from acemusic.api.tasks.processor import JobProcessor
from tests.test_releases_api import FULL_METADATA as RELEASE_METADATA, RELEASES_URL
from tests.test_voice_models_api import wav as voice_wav
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

    # Cyrillic е/і/Һ, Greek ε/ι/Η/ο, fullwidth and mathematical letters standing in for Latin ones (#532).
    @pytest.mark.parametrize(
        "text", ["sieg hеil", "sіeg heil", "SIEG ҺEIL", "siεg hειl", "ＳＩＥＧ ＨＥＩＬ", "𝐬𝐢𝐞𝐠 𝐡𝐞𝐢𝐥"]
    )
    def test_homoglyphs_do_not_evade(self, text):
        assert screening.match(self.RULES, [text]).blocked is True

    def test_a_rule_written_with_homoglyphs_still_matches_plain_text(self):
        rules = screening.ScreeningRules(rules=[screening.Rule(term="hеil", category="hate speech", action="block")])
        assert screening.match(rules, ["heil"]).blocked is True

    # Zero-width space/joiner, word joiner, BOM and soft hyphen hidden inside a word.
    @pytest.mark.parametrize("hidden", ["​", "‍", "⁠", "﻿", "­"])
    def test_invisible_characters_do_not_split_a_word(self, hidden):
        assert screening.match(self.RULES, [f"sie{hidden}g he{hidden}il"]).blocked is True

    # Combining grapheme joiner and variation selectors: zero-width marks that combining() reports as 0.
    @pytest.mark.parametrize("hidden", ["͏", "️", "︀"])
    def test_zero_width_marks_do_not_split_a_word(self, hidden):
        assert screening.match(self.RULES, [f"sieg he{hidden}il"]).blocked is True

    def test_an_invisible_character_still_separates_words(self):
        assert screening.match(self.RULES, ["sieg​heil"]).blocked is True

    LEET = RULES.model_copy(update={"fold_leetspeak": True})

    @pytest.mark.parametrize("text", ["s13g h31l", "5ieg he1l", "$ieg h3il", "r4p3"])
    def test_leetspeak_evades_by_default(self, text):
        assert screening.match(self.RULES, [text]).categories == []

    @pytest.mark.parametrize("text", ["s13g h31l", "5ieg he1l", "$ieg h3il", "SIEG H3IL", "sie6 heil", "sie9 heil"])
    def test_leetspeak_is_caught_when_the_rule_set_folds_it(self, text):
        assert screening.match(self.LEET, [text]).blocked is True

    def test_one_stands_for_both_i_and_l(self):
        rules = screening.ScreeningRules(
            rules=[screening.Rule(term="kill list", category="violence", action="flag")], fold_leetspeak=True
        )
        assert screening.match(rules, ["k1ll 1ist"]).flags == ["violence"]

    def test_b_and_z_stand_ins_are_folded(self):
        rules = screening.ScreeningRules(
            rules=[screening.Rule(term="blitz", category="violence", action="flag")], fold_leetspeak=True
        )
        assert screening.match(rules, ["8li72"]).flags == ["violence"]

    def test_leet_allow_terms_still_suppress(self):
        assert screening.match(self.LEET, ["a r4pe awar3ness single"]).flags == []

    def test_leet_fold_keeps_whole_word_matching(self):
        assert screening.match(self.LEET, ["dr4pe the stage", "r4pes"]).flags == []

    @pytest.mark.parametrize("text", ["sieg$heil", "sieg@heil"])
    def test_leet_symbols_still_separate_words(self, text):
        assert screening.match(self.LEET, [text]).blocked is True

    def test_a_rule_containing_a_leet_symbol_matches_itself(self):
        rules = screening.ScreeningRules(
            rules=[screening.Rule(term="ca$h out", category="fraud", action="flag")], fold_leetspeak=True
        )
        assert screening.match(rules, ["ca$h out"]).flags == ["fraud"]

    def test_an_allow_term_containing_a_leet_symbol_still_suppresses(self):
        rules = screening.ScreeningRules(
            rules=[screening.Rule(term="nazi", category="hate speech", action="block")],
            allow_terms=["n@zi"],
            fold_leetspeak=True,
        )
        assert screening.match(rules, ["n@zi"]).categories == []


# Everyday lyrics a fold must not turn into a rule hit: English with numbers and prices, and
# ordinary Russian and Greek, whose letters the homoglyph table maps onto Latin (#532).
ORDINARY_LYRICS = [
    "[Verse 1]\nWe drove 405 miles at 3am, $5 in the tank and 1 last song\nSing it loud, sing it 4 me",
    "Top 40 hits of 1999, 24/7 on the radio, 7 nights a week @ the club",
    "[Chorus]\nОчи чёрные, очи страстные, очи жгучие и прекрасные\nКак люблю я вас, как боюсь я вас",
    "Всё пройдёт, и печаль, и радость, солнце встанет над рекой",
    "Σ' αγαπώ, σε θέλω, κάτω από τον ουρανό της Αθήνας\nΧόρεψε μαζί μου απόψε",
    "Ruby Tuesday, heal my heart, the rapeseed fields are golden, sheila come home",
]


@pytest.mark.parametrize("fold_leetspeak", [False, True])
@pytest.mark.parametrize("lyrics", ORDINARY_LYRICS)
def test_folding_does_not_flag_ordinary_lyrics(lyrics, fold_leetspeak):
    rules = screening.DEFAULT_RULES.model_copy(update={"fold_leetspeak": fold_leetspeak})
    assert screening.match(rules, [lyrics]).categories == []


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

    async def test_leet_folding_is_off_until_an_admin_turns_it_on(self, client, settings):
        admin = await make_user("screen-admin-leet@example.com", is_admin=True)
        user = await make_user("screen-leet@example.com")
        prompt = {"prompt": "a chant of s13g h31l"}
        current = (await client.get(RULES_URL, headers=_auth(admin, settings))).json()
        assert current["fold_leetspeak"] is False
        assert (await client.post(GENERATE_URL, json=prompt, headers=_auth(user, settings))).status_code == 202

        current["fold_leetspeak"] = True
        assert (await client.put(RULES_URL, json=current, headers=_auth(admin, settings))).status_code == 200
        assert (await client.get(RULES_URL, headers=_auth(admin, settings))).json()["fold_leetspeak"] is True
        assert (await client.post(GENERATE_URL, json=prompt, headers=_auth(user, settings))).status_code == 422

    async def test_a_rule_set_saved_before_leet_folding_existed_reads_as_off(self, client, settings):
        admin = await make_user("screen-admin-legacy@example.com", is_admin=True)
        legacy = {"key": "global", "rules": [], "allow_terms": [], "block_threshold": 0}
        await screening.ScreeningRulesDocument.get_pymongo_collection().insert_one(legacy)
        assert (await client.get(RULES_URL, headers=_auth(admin, settings))).json()["fold_leetspeak"] is False

    async def test_invalid_rules_are_rejected(self, client, settings):
        admin = await make_user("screen-admin-bad@example.com", is_admin=True)
        bad = {"rules": [{"term": " ", "category": "x", "action": "block"}], "allow_terms": [], "block_threshold": 0}
        assert (await client.put(RULES_URL, json=bad, headers=_auth(admin, settings))).status_code == 422
        worse = {"rules": [{"term": "x", "category": "x", "action": "nuke"}], "allow_terms": [], "block_threshold": 0}
        assert (await client.put(RULES_URL, json=worse, headers=_auth(admin, settings))).status_code == 422


@pytest.fixture
def local_storage(monkeypatch, tmp_path):
    monkeypatch.setenv("ACEMUSIC_STORAGE_BACKEND", "local")
    monkeypatch.setenv("ACEMUSIC_STORAGE_LOCAL_ROOT", str(tmp_path))
    return tmp_path


def _wav() -> bytes:
    payload = b"\x00" * 64
    return b"RIFF" + (36 + len(payload)).to_bytes(4, "little") + b"WAVEfmt " + payload


def test_blocked_metadata_says_it_was_not_saved():
    message = str(screening.ContentBlockedError(["hate speech"], saving=True))
    assert message.startswith("This wasn't saved because")
    assert "hate speech" in message
    assert "prompt" not in message


def test_clip_edits_never_whole_document_save():
    # A whole-document save() of a Clip read before a moderation removal lands would undo it (AGENTS.md).
    assert ".save(" not in inspect.getsource(clip_service.update_clip_fields)


@pytest.mark.integration
class TestClipMetadataScreening:
    """US-27.1 follow-up (#531): text a clip only *displays* is screened like generation text."""

    async def _upload(self, client, settings, user, **form):
        workspace = Workspace(name="WS", user_id=user.id)
        await workspace.insert()
        return await client.post(
            f"{API_V1_PREFIX}/clips/upload",
            files={"file": ("clip.wav", _wav(), "audio/wav")},
            data={"workspace_id": str(workspace.id), **form},
            headers=_auth(user, settings),
        )

    async def test_upload_with_a_blocked_title_is_refused_and_stores_nothing(self, client, settings, local_storage):
        user = await make_user("meta-upload-block@example.com")
        resp = await self._upload(client, settings, user, title="Sieg Heil march")
        assert resp.status_code == 422
        assert "hate speech" in resp.json()["detail"]
        assert "wasn't saved" in resp.json()["detail"]
        assert await Clip.find(Clip.user_id == user.id).to_list() == []

    async def test_upload_screens_tags_as_the_joined_string(self, client, settings, local_storage):
        user = await make_user("meta-upload-tags@example.com")
        resp = await self._upload(client, settings, user, title="March", style_tags="sieg, heil")
        assert resp.status_code == 422

    async def test_upload_with_a_borderline_tag_is_stored_with_the_flag(self, client, settings, local_storage):
        user = await make_user("meta-upload-flag@example.com")
        resp = await self._upload(client, settings, user, title="Grief", style_tags="suicide ballad")
        assert resp.status_code == 201, resp.text
        clip = await Clip.get(PydanticObjectId(resp.json()["id"]))
        assert clip.moderation_flags == ["self-harm"]

    async def test_clean_upload_passes_unflagged(self, client, settings, local_storage):
        user = await make_user("meta-upload-clean@example.com")
        resp = await self._upload(client, settings, user, title="Night drive", style_tags="synthwave")
        assert resp.status_code == 201, resp.text
        assert (await Clip.get(PydanticObjectId(resp.json()["id"]))).moderation_flags == []

    async def _patch(self, client, settings, user, clip, body):
        return await client.patch(f"{API_V1_PREFIX}/clips/{clip.id}", json=body, headers=_auth(user, settings))

    async def test_a_blocked_rename_is_refused_and_the_title_is_unchanged(self, client, settings):
        user, clip = await _user_with_clip("meta-rename-block@example.com")
        await clip.set({Clip.title: "Old title"})
        resp = await self._patch(client, settings, user, clip, {"title": "white power anthem"})
        assert resp.status_code == 422
        assert "wasn't saved" in resp.json()["detail"]
        assert (await Clip.get(clip.id)).title == "Old title"

    async def test_a_borderline_rename_is_saved_and_requeues_a_reviewed_clip(self, client, settings):
        user, clip = await _user_with_clip("meta-rename-flag@example.com")
        await clip.set({Clip.moderation_flags: ["self-harm"], Clip.moderation_reviewed_at: utcnow()})
        resp = await self._patch(client, settings, user, clip, {"title": "Terrorist in my head"})
        assert resp.status_code == 200, resp.text
        stored = await Clip.get(clip.id)
        assert stored.title == "Terrorist in my head"
        assert stored.moderation_flags == ["self-harm", "violent extremism"]
        assert stored.moderation_reviewed_at is None

    async def test_a_clean_rename_passes_unflagged(self, client, settings):
        user, clip = await _user_with_clip("meta-rename-clean@example.com")
        resp = await self._patch(client, settings, user, clip, {"title": "Night drive"})
        assert resp.status_code == 200, resp.text
        stored = await Clip.get(clip.id)
        assert (stored.title, stored.moderation_flags) == ("Night drive", [])

    @pytest.mark.parametrize("visibility", ["public", "unlisted"])
    async def test_going_visible_screens_text_written_before_screening_existed(self, client, settings, visibility):
        user, clip = await _user_with_clip(f"meta-publish-block-{visibility}@example.com")
        await clip.set({Clip.title: "Song", Clip.style_tags: ["folk"], Clip.lyrics: "[Chorus]\nheil hitler"})
        resp = await self._patch(client, settings, user, clip, {"visibility": visibility})
        assert resp.status_code == 422
        assert (await Clip.get(clip.id)).visibility == VisibilityState.PRIVATE

    async def test_a_blocked_title_sent_with_publish_is_screened(self, client, settings):
        user, clip = await _user_with_clip("meta-rename-publish@example.com")
        await clip.set({Clip.title: "Song", Clip.style_tags: ["folk"]})
        resp = await self._patch(client, settings, user, clip, {"title": "white power anthem", "visibility": "public"})
        assert resp.status_code == 422
        stored = await Clip.get(clip.id)
        assert (stored.title, stored.visibility) == ("Song", VisibilityState.PRIVATE)

    async def test_a_removal_landing_mid_publish_is_not_undone(self, client, settings, monkeypatch):
        user, clip = await _user_with_clip("meta-publish-race@example.com")
        await clip.set({Clip.title: "Song", Clip.style_tags: ["folk"]})
        real_enforce = screening.enforce

        async def removed_while_screening(*texts, **kwargs):
            # The owner's PATCH has read the clip; a moderator removes it before the write.
            await Clip.find_one(Clip.id == clip.id).update({"$set": {"removed_at": utcnow()}})
            return await real_enforce(*texts, **kwargs)

        monkeypatch.setattr(screening, "enforce", removed_while_screening)
        resp = await self._patch(client, settings, user, clip, {"visibility": "public"})
        assert resp.status_code == 403
        stored = await Clip.get(clip.id)
        assert stored.visibility == VisibilityState.PRIVATE and stored.removed_at is not None

    async def test_publishing_does_not_requeue_an_already_reviewed_flag(self, client, settings):
        user, clip = await _user_with_clip("meta-publish-reviewed@example.com")
        reviewed = utcnow()
        await clip.set(
            {
                Clip.title: "Grief",
                Clip.style_tags: ["folk"],
                Clip.lyrics: "a song about suicide",
                Clip.moderation_flags: ["self-harm"],
                Clip.moderation_reviewed_at: reviewed,
            }
        )
        resp = await self._patch(client, settings, user, clip, {"visibility": "public"})
        assert resp.status_code == 200, resp.text
        stored = await Clip.get(clip.id)
        assert stored.visibility == VisibilityState.PUBLIC and stored.is_public
        assert stored.moderation_flags == ["self-harm"]
        assert stored.moderation_reviewed_at is not None

    async def test_a_clean_clip_publishes_unflagged(self, client, settings):
        user, clip = await _user_with_clip("meta-publish-clean@example.com")
        await clip.set({Clip.title: "Night drive", Clip.style_tags: ["synthwave"]})
        resp = await self._patch(client, settings, user, clip, {"visibility": "public"})
        assert resp.status_code == 200, resp.text
        stored = await Clip.get(clip.id)
        assert (stored.visibility, stored.moderation_flags) == (VisibilityState.PUBLIC, [])


@pytest.mark.integration
class TestReleaseVisibilityScreening:
    """A release's visibility is mirrored onto its source clip, so it is a second way to publish one."""

    async def _publish(self, client, settings, lyrics, *, on_soundcloud=False):
        user, clip = await _user_with_clip(f"meta-release-{len(lyrics)}@example.com")
        await clip.set({Clip.title: "Song", Clip.style_tags: ["folk"], Clip.lyrics: lyrics})
        created = await client.post(
            RELEASES_URL, json={"clip_id": str(clip.id), **RELEASE_METADATA}, headers=_auth(user, settings)
        )
        assert created.status_code == 201, created.text
        if on_soundcloud:
            await Release.find_one(Release.id == PydanticObjectId(created.json()["id"])).update(
                {"$set": {"soundcloud_track_id": "789"}}
            )
            await SoundCloudConnection(
                user_id=user.id,
                soundcloud_user_id="sc-1",
                access_token="tok",
                refresh_token="ref",
                token_expires_at=utcnow() + timedelta(hours=1),
            ).insert()
        resp = await client.patch(
            f"{RELEASES_URL}/{created.json()['id']}/visibility", json={"state": "public"}, headers=_auth(user, settings)
        )
        return resp, await Clip.get(clip.id), await Release.get(PydanticObjectId(created.json()["id"]))

    async def test_blocked_source_text_keeps_the_release_and_clip_private(self, client, settings):
        resp, clip, release = await self._publish(client, settings, "[Chorus]\ngas the jews")
        assert resp.status_code == 422
        assert "wasn't saved" in resp.json()["detail"]
        assert (clip.visibility, release.visibility) == (VisibilityState.PRIVATE, VisibilityState.PRIVATE)

    async def test_borderline_source_text_publishes_and_flags_the_clip(self, client, settings):
        resp, clip, _ = await self._publish(client, settings, "a song about self harm")
        assert resp.status_code == 200, resp.text
        assert (clip.visibility, clip.moderation_flags) == (VisibilityState.PUBLIC, ["self-harm"])
        assert clip.moderation_reviewed_at is None

    async def test_a_removal_landing_mid_publish_keeps_the_release_private(self, client, settings, monkeypatch):
        real_enforce = screening.enforce

        async def removed_while_screening(*texts, **kwargs):
            # The router has checked the source clip; a moderator removes it before the write.
            await Clip.find({"title": "Song", "lyrics": "a quiet folk song"}).update({"$set": {"removed_at": utcnow()}})
            return await real_enforce(*texts, **kwargs)

        shared: list[str] = []

        async def update_track_sharing(_token, track_id, sharing):
            shared.append(f"{track_id}:{sharing}")
            return {}

        monkeypatch.setattr(screening, "enforce", removed_while_screening)
        monkeypatch.setattr(soundcloud, "update_track_sharing", update_track_sharing)
        resp, clip, release = await self._publish(client, settings, "a quiet folk song", on_soundcloud=True)
        assert resp.status_code == 403
        assert (clip.visibility, release.visibility) == (VisibilityState.PRIVATE, VisibilityState.PRIVATE)
        # The removed clip's SoundCloud track is never re-shared.
        assert shared == []


@pytest.mark.integration
class TestVoiceModelScreening:
    async def _train(self, client, settings, user, **form):
        files = [("files", (f"take{i}.wav", voice_wav(freq=200.0 + 10 * i), "audio/wav")) for i in range(3)]
        return await client.post(
            f"{API_V1_PREFIX}/voice-models/train", files=files, data=form, headers=_auth(user, settings)
        )

    async def test_a_blocked_name_is_refused_before_charging(self, client, settings, local_storage):
        user = await make_user("voice-block@example.com", tier=PRO)
        before = user.credits_balance
        resp = await self._train(client, settings, user, name="Heil Hitler voice")
        assert resp.status_code == 422
        assert "wasn't saved" in resp.json()["detail"]
        assert await VoiceModel.find(VoiceModel.user_id == user.id).to_list() == []
        assert await _balance(user) == before

    async def test_a_borderline_description_is_stored_with_the_flag(self, client, settings, local_storage):
        user = await make_user("voice-flag@example.com", tier=PRO)
        resp = await self._train(client, settings, user, name="Mine", description="for my genocide concept album")
        assert resp.status_code == 202, resp.text
        model = await VoiceModel.get(PydanticObjectId(resp.json()["voice_model"]["id"]))
        assert model.moderation_flags == ["violent extremism"]

    async def test_a_clean_voice_trains_unflagged(self, client, settings, local_storage):
        user = await make_user("voice-clean@example.com", tier=PRO)
        resp = await self._train(client, settings, user, name="Warm baritone")
        assert resp.status_code == 202, resp.text
        assert (await VoiceModel.get(PydanticObjectId(resp.json()["voice_model"]["id"]))).moderation_flags == []

    async def _model(self, email):
        user = await make_user(email, tier=PRO)
        model = VoiceModel(user_id=user.id, name="Original", status=VoiceModelStatus.READY)
        await model.insert()
        return user, model

    async def test_a_blocked_rename_is_refused(self, client, settings):
        user, model = await self._model("voice-rename-block@example.com")
        resp = await client.patch(
            f"{API_V1_PREFIX}/voice-models/{model.id}",
            json={"description": "sieg heil"},
            headers=_auth(user, settings),
        )
        assert resp.status_code == 422
        assert (await VoiceModel.get(model.id)).description is None

    async def test_a_borderline_rename_adds_the_flag(self, client, settings):
        user, model = await self._model("voice-rename-flag@example.com")
        resp = await client.patch(
            f"{API_V1_PREFIX}/voice-models/{model.id}", json={"name": "Rape survivor"}, headers=_auth(user, settings)
        )
        assert resp.status_code == 200, resp.text
        stored = await VoiceModel.get(model.id)
        assert (stored.name, stored.moderation_flags) == ("Rape survivor", ["sexual violence"])

    async def test_a_clean_rename_passes(self, client, settings):
        user, model = await self._model("voice-rename-clean@example.com")
        resp = await client.patch(
            f"{API_V1_PREFIX}/voice-models/{model.id}", json={"name": "Tenor"}, headers=_auth(user, settings)
        )
        assert resp.status_code == 200, resp.text
        assert (await VoiceModel.get(model.id)).moderation_flags == []
