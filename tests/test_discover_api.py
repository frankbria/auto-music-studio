"""Public discovery listings for Feed, Explore and Search (#651).

``GET /discover/clips`` and ``GET /discover/facets`` are anonymous reads over the public
pool: public, not removed by moderation, and not owned by a banned user. That rule lives in
one shared filter (``services/clips.public_clip_filter``), which similar-clips uses too.
"""

import itertools
from datetime import timedelta

import httpx
import pytest
from beanie import PydanticObjectId
from fastapi.testclient import TestClient

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.models import Clip, VisibilityState, Workspace
from acemusic.api.models.common import utcnow
from acemusic.api.services import discovery
from acemusic.api.services.clips import find_similar_clips
from acemusic.api.services.moderation import encode_cursor
from acemusic.api.settings import ApiSettings
from tests.users import make_user

CLIPS_URL = f"{API_V1_PREFIX}/discover/clips"
FACETS_URL = f"{API_V1_PREFIX}/discover/facets"

_SEQ = itertools.count(1)
_BASE_TIME = utcnow().replace(microsecond=0) - timedelta(days=1)


class TestValidationWithoutDatabase:
    def test_unknown_sort_is_422(self) -> None:
        assert TestClient(create_app()).get(CLIPS_URL, params={"sort": "popular"}).status_code == 422

    def test_limit_over_the_cap_is_422(self) -> None:
        assert TestClient(create_app()).get(CLIPS_URL, params={"limit": 51}).status_code == 422

    def test_overlong_query_is_422(self) -> None:
        assert TestClient(create_app()).get(CLIPS_URL, params={"q": "x" * 201}).status_code == 422


@pytest.fixture
def settings(mongo_db, mongo_settings) -> ApiSettings:
    return mongo_settings.model_copy(
        update={"jwt_secret_key": "test-secret-key-at-least-32-bytes-long-xx", "job_processor_enabled": False}
    )


@pytest.fixture(autouse=True)
def _fresh_facets():
    """The facet cache is per process; each test changes the pool."""
    discovery.clear_facets_cache()
    yield
    discovery.clear_facets_cache()


@pytest.fixture
async def client(settings):
    transport = httpx.ASGITransport(app=create_app(settings))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


async def _owner(**fields):
    return await make_user(f"discover-{next(_SEQ)}@example.com", **fields)


async def _clip(owner=None, *, minutes: int = 0, visibility=VisibilityState.PUBLIC, **fields) -> Clip:
    owner = owner or await _owner()
    workspace = Workspace(name="WS", user_id=owner.id)
    await workspace.insert()
    clip = Clip(
        id=PydanticObjectId(),
        user_id=owner.id,
        workspace_id=workspace.id,
        file_path="x.wav",
        format="wav",
        visibility=visibility,
        created_at=_BASE_TIME + timedelta(minutes=minutes),
        **{"title": "Song", "style_tags": ["lofi"], **fields},
    )
    await clip.insert()
    return clip


async def _ids(client, **params) -> list[str]:
    resp = await client.get(CLIPS_URL, params=params)
    assert resp.status_code == 200, resp.text
    return [c["id"] for c in resp.json()["clips"]]


async def _all_pages(client, **params) -> list[str]:
    ids: list[str] = []
    cursor = None
    while True:
        resp = await client.get(CLIPS_URL, params={**params, **({"cursor": cursor} if cursor else {})})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        ids += [c["id"] for c in body["clips"]]
        cursor = body["next_cursor"]
        if cursor is None:
            return ids


@pytest.mark.integration
class TestPublicPool:
    async def test_only_public_clips_from_unbanned_owners_that_were_not_removed_are_listed(self, client) -> None:
        listed = await _clip(title="Listed", key="A minor", model="ace-step-v1")
        await _clip(title="Private", visibility=VisibilityState.PRIVATE, key="B minor", model="m-private")
        await _clip(title="Unlisted", visibility=VisibilityState.UNLISTED, key="C minor", model="m-unlisted")
        # Written straight to the database, past the ban sweep and the removal path that would
        # also make them private: the shared filter must hold on its own.
        await _clip(title="Removed", removed_at=utcnow(), key="D minor", model="m-removed")
        stamp = utcnow()
        await _clip(
            await _owner(banned_at=stamp), title="Banned", owner_banned_at=stamp, key="E minor", model="m-banned"
        )

        for sort in ("newest", "relevance"):
            assert await _ids(client, sort=sort) == [str(listed.id)]
            for hidden in ("Private", "Unlisted", "Removed", "Banned"):
                assert await _ids(client, sort=sort, q=hidden) == []
        assert (await client.get(FACETS_URL)).json() == {"keys": ["A minor"], "models": ["ace-step-v1"]}

    async def test_a_public_clip_written_before_visibility_existed_is_listed(self, client) -> None:
        owner = await _owner()
        legacy_id = PydanticObjectId()
        legacy = {"_id": legacy_id, "user_id": owner.id, "workspace_id": PydanticObjectId(), "file_path": "x.wav"}
        legacy |= {"style_tags": [], "is_public": True, "created_at": _BASE_TIME}
        await Clip.get_pymongo_collection().insert_one(legacy)  # pre-US-20.7 shape: no visibility key
        assert await _ids(client) == [str(legacy_id)]

    async def test_a_clip_whose_two_visibility_copies_disagree_is_not_listed(self, client) -> None:
        drifted = await _clip(visibility=VisibilityState.PUBLIC)
        await Clip.get_pymongo_collection().update_one({"_id": drifted.id}, {"$set": {"visibility": "unlisted"}})
        assert await _ids(client) == []

    async def test_discovery_has_its_own_rate_limit_bucket(self, settings) -> None:
        app = create_app(settings.model_copy(update={"discover_rate_limit_per_minute": 1}))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as ac:
            assert (await ac.get(CLIPS_URL)).status_code == 200
            limited = await ac.get(FACETS_URL)
            assert (limited.status_code, limited.json()["detail"]) == (429, "Too many discovery requests; slow down.")
            assert (await ac.get(f"{API_V1_PREFIX}/clips/{PydanticObjectId()}/public")).status_code == 404

    async def test_total_counts_the_whole_match_not_the_page(self, client) -> None:
        for i in range(3):
            await _clip(minutes=i)
        body = (await client.get(CLIPS_URL, params={"limit": 2})).json()
        assert (len(body["clips"]), body["total"]) == (2, 3)
        assert body["next_cursor"] is not None

    async def test_response_is_the_redacted_public_clip_shape(self, client) -> None:
        clip = await _clip(seed=7, inference_steps=30, content_warning=True)
        [served] = (await client.get(CLIPS_URL)).json()["clips"]
        assert served["id"] == str(clip.id)
        assert (served["workspace_id"], served["seed"], served["inference_steps"]) == (None, None, None)
        assert (served["is_owner"], served["content_warning"]) == (False, True)

    async def test_a_signed_in_viewer_sees_their_own_clip_marked(self, client, settings) -> None:
        viewer = await _owner()
        mine, theirs = await _clip(viewer, title="Mine"), await _clip(title="Theirs", minutes=1)
        token = create_access_token(
            user_id=str(viewer.id), email=viewer.email, subscription_tier=viewer.subscription_tier, settings=settings
        )

        signed_in = (await client.get(CLIPS_URL, headers={"Authorization": f"Bearer {token}"})).json()["clips"]
        anonymous = (await client.get(CLIPS_URL)).json()["clips"]

        assert {c["id"]: c["is_owner"] for c in signed_in} == {str(mine.id): True, str(theirs.id): False}
        assert [c["is_owner"] for c in anonymous] == [False, False]

    async def test_a_bad_token_is_401_not_silently_anonymous(self, client) -> None:
        resp = await client.get(CLIPS_URL, headers={"Authorization": "Bearer not-a-jwt"})
        assert resp.status_code == 401

    async def test_similar_clips_public_scope_skips_a_banned_owners_clip(self, mongo_db) -> None:
        viewer = await _owner()
        seed = await _clip(style_tags=["lofi"])
        kept = await _clip(style_tags=["lofi"])
        stamp = utcnow()
        await _clip(await _owner(banned_at=stamp), style_tags=["lofi"], owner_banned_at=stamp)
        await _clip(style_tags=["lofi"], removed_at=utcnow())
        for scope in ("public", "all"):
            similar, total = await find_similar_clips(str(seed.id), str(viewer.id), scope=scope)
            assert ([c.id for c in similar], total) == ([kept.id], 1)


@pytest.mark.integration
class TestFiltersAndSorts:
    async def test_newest_first(self, client) -> None:
        old = await _clip(minutes=1)
        new = await _clip(minutes=2)
        assert await _ids(client) == [str(new.id), str(old.id)]

    async def test_free_text_matches_whole_words_in_title_tags_and_lyrics_case_insensitively(self, client) -> None:
        """#655: the text index matches stemmed whole words, not substrings."""
        by_title = await _clip(title="Neon NIGHTS", minutes=3)
        by_tag = await _clip(title="A", style_tags=["late night drive"], minutes=2)
        by_lyrics = await _clip(title="B", lyrics="all night long", minutes=1)
        await _clip(title="C", style_tags=["nightcore"])
        assert await _ids(client, q="night") == [str(by_title.id), str(by_tag.id), str(by_lyrics.id)]

    async def test_free_text_is_stemmed_and_a_partial_word_finds_nothing(self, client) -> None:
        loving = await _clip(title="Loving You")
        assert await _ids(client, q="love") == [str(loving.id)]
        assert await _ids(client, q="lov") == []

    async def test_free_text_symbols_are_not_operators(self, client) -> None:
        something = await _clip(title="Something")
        for q in (".", "(", "[a-z]+", "$where", '"', '"night', "-anything"):
            resp = await client.get(CLIPS_URL, params={"q": q})
            assert resp.status_code == 200, (q, resp.text)
            assert resp.json()["clips"] == []
        assert await _ids(client, q="--something") == [str(something.id)]

    async def test_relevance_ranks_title_then_tag_then_lyrics(self, client) -> None:
        lyrics = await _clip(title="Zzz", lyrics="glow", minutes=3)
        tag = await _clip(title="Yyy", style_tags=["glow"], minutes=2)
        title = await _clip(title="Glow Up", minutes=1)
        expected = [str(title.id), str(tag.id), str(lyrics.id)]
        assert await _ids(client, q="glow", sort="relevance") == expected
        assert await _all_pages(client, q="glow", sort="relevance", limit=1) == expected

    async def test_facets_are_cached_briefly(self, client) -> None:
        await _clip(key="A minor", model="m1")
        assert (await client.get(FACETS_URL)).json()["keys"] == ["A minor"]
        await _clip(key="B minor", model="m1")
        assert (await client.get(FACETS_URL)).json()["keys"] == ["A minor"]
        discovery.clear_facets_cache()
        assert (await client.get(FACETS_URL)).json()["keys"] == ["A minor", "B minor"]

    async def test_total_is_counted_on_the_first_page_only(self, client) -> None:
        for i in range(3):
            await _clip(title="Count", minutes=i)
        first = (await client.get(CLIPS_URL, params={"limit": 2})).json()
        second = (await client.get(CLIPS_URL, params={"limit": 2, "cursor": first["next_cursor"]})).json()
        assert (first["total"], second["total"]) == (3, None)

    async def test_relevance_without_a_query_is_newest(self, client) -> None:
        old = await _clip(minutes=1)
        new = await _clip(minutes=2)
        assert await _ids(client, sort="relevance") == [str(new.id), str(old.id)]

    async def test_style_bpm_key_and_model_filters_combine(self, client) -> None:
        match = await _clip(style_tags=["Gritty ROCK anthem"], bpm=120, key="E minor", model="turbo")
        await _clip(style_tags=["rockabilly"], bpm=120, key="E minor", model="turbo")  # a whole word, not a prefix
        await _clip(style_tags=["rock"], bpm=140, key="E minor", model="turbo")
        await _clip(style_tags=["rock"], bpm=120, key="A minor", model="turbo")
        await _clip(style_tags=["rock"], bpm=120, key="E minor", model="base")
        params = {"style": "rock", "bpm_min": 100, "bpm_max": 130, "key": "E minor", "model": "turbo"}
        assert await _ids(client, **params) == [str(match.id)]

    async def test_a_genre_slug_matches_the_phrase_inside_a_generated_style_prompt(self, client) -> None:
        # Generation stores the whole style prompt as the clip's one tag (tasks/processor.py).
        spaced = await _clip(style_tags=["dark hip hop beat"], minutes=2)
        hyphenated = await _clip(style_tags=["Hip-Hop"], minutes=1)
        joined = await _clip(style_tags=["hiphop"])
        assert await _ids(client, style="hip-hop") == [str(spaced.id), str(hyphenated.id)]
        everything = [str(spaced.id), str(hyphenated.id), str(joined.id)]
        for blank in (None, "   ", "-"):  # no style, or one with no words, filters nothing
            assert await _ids(client, **({"style": blank} if blank is not None else {})) == everything

    async def test_the_r_and_b_genre_finds_clips_tagged_r_and_b(self, client) -> None:
        """#657: the R&B tile searches style "r&b"."""
        tagged = await _clip(style_tags=["smooth r&b groove"])
        await _clip(style_tags=["rock"], minutes=1)
        assert await _ids(client, style="r&b") == [str(tagged.id)]

    async def test_a_style_ending_in_a_symbol_still_matches_as_a_whole_word(self, client) -> None:
        coded = await _clip(style_tags=["chiptune c++ demo"])
        await _clip(style_tags=["c++x"])
        assert await _ids(client, style="c++") == [str(coded.id)]

    async def test_bpm_bounds_are_inclusive(self, client) -> None:
        low = await _clip(bpm=100, minutes=1)
        high = await _clip(bpm=130, minutes=2)
        assert await _ids(client, bpm_min=100, bpm_max=130) == [str(high.id), str(low.id)]


@pytest.mark.integration
class TestKeysetPaging:
    async def test_pages_cover_every_clip_once(self, client) -> None:
        clips = [await _clip(minutes=i // 2) for i in range(5)]  # pairs share a created_at
        ids = await _all_pages(client, limit=2)
        assert sorted(ids) == sorted(str(c.id) for c in clips)
        assert len(ids) == len(set(ids))

    async def test_relevance_pages_cover_every_clip_once_when_score_and_time_tie(self, client) -> None:
        clips = [await _clip(title="tie", minutes=i // 2) for i in range(5)]  # same score, pairs share created_at
        ids = await _all_pages(client, q="tie", sort="relevance", limit=2)
        assert sorted(ids) == sorted(str(c.id) for c in clips)
        assert len(ids) == len(set(ids))

    async def test_a_newer_clip_inserted_between_pages_does_not_shift_the_next_page(self, client) -> None:
        for i in range(4):
            await _clip(minutes=i)
        first = (await client.get(CLIPS_URL, params={"limit": 2})).json()
        await _clip(minutes=10)
        second = (await client.get(CLIPS_URL, params={"limit": 2, "cursor": first["next_cursor"]})).json()
        seen = [c["id"] for c in first["clips"] + second["clips"]]
        assert len(seen) == len(set(seen)) == 4

    async def test_a_relevance_page_survives_a_newer_better_match(self, client) -> None:
        for i in range(3):
            await _clip(title="drift", minutes=i)
        first = (await client.get(CLIPS_URL, params={"q": "drift", "sort": "relevance", "limit": 2})).json()
        await _clip(title="drift", minutes=10)
        cursor = first["next_cursor"]
        second = (await client.get(CLIPS_URL, params={"q": "drift", "sort": "relevance", "cursor": cursor})).json()
        seen = [c["id"] for c in first["clips"] + second["clips"]]
        assert len(seen) == len(set(seen)) == 3

    async def test_a_malformed_cursor_is_422(self, client) -> None:
        assert (await client.get(CLIPS_URL, params={"cursor": "not-a-cursor"})).status_code == 422

    async def test_a_relevance_cursor_with_a_bad_id_is_422(self, client) -> None:
        cursor = encode_cursor("discover_relevance", (3, _BASE_TIME.replace(tzinfo=None), "not-an-object-id"))
        resp = await client.get(CLIPS_URL, params={"q": "echo", "sort": "relevance", "cursor": cursor})
        assert resp.status_code == 422

    async def test_a_cursor_from_the_other_sort_is_422(self, client) -> None:
        for i in range(2):
            await _clip(title="echo", minutes=i)
        cursor = (await client.get(CLIPS_URL, params={"limit": 1})).json()["next_cursor"]
        replayed = await client.get(CLIPS_URL, params={"q": "echo", "sort": "relevance", "cursor": cursor})
        assert replayed.status_code == 422
