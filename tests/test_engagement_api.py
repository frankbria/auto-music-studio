"""Plays, likes, shares, staff picks, and the listings they back (#656).

Owner decisions: a play counts once per listener per clip per hour, a like once per signed-in user (undoable), a
share once per user per clip per day. Trending is plays + 3 x likes + 5 x shares inside 24 h or 7 days; Charts and
Most Popular are all-time plays; staff picks are newest first. Plays and likes are public, shares admin-only.
"""

import asyncio
import itertools
from datetime import timedelta

import httpx
import pytest
from beanie import PydanticObjectId
from pymongo.errors import ExecutionTimeout

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.models import Clip, ClipEngagement, ModerationLogEntry, VisibilityState, Workspace
from acemusic.api.models.common import utcnow
from acemusic.api.services import discovery, engagement
from acemusic.api.settings import ApiSettings
from tests.users import make_user

CLIPS = f"{API_V1_PREFIX}/clips"
DISCOVER = f"{API_V1_PREFIX}/discover/clips"
ADMIN = f"{API_V1_PREFIX}/admin/clips"
_SEQ = itertools.count(1)

pytestmark = pytest.mark.integration


@pytest.fixture
def settings(mongo_db, mongo_settings) -> ApiSettings:
    return mongo_settings.model_copy(
        update={"jwt_secret_key": "test-secret-key-at-least-32-bytes-long-xx", "job_processor_enabled": False}
    )


@pytest.fixture(autouse=True)
def _fresh_trending():
    """The trending ranking is cached per process; each test records its own engagement."""
    discovery.clear_trending_cache()
    yield
    discovery.clear_trending_cache()


@pytest.fixture
async def client(settings):
    transport = httpx.ASGITransport(app=create_app(settings))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


def _auth(user, settings: ApiSettings) -> dict[str, str]:
    token = create_access_token(
        user_id=str(user.id), email=user.email, subscription_tier=user.subscription_tier, settings=settings
    )
    return {"Authorization": f"Bearer {token}"}


async def _user(**fields):
    return await make_user(f"engage-{next(_SEQ)}@example.com", **fields)


async def _clip(*, visibility=VisibilityState.PUBLIC, minutes: int = 0, **fields) -> Clip:
    owner = await _user()
    workspace = await Workspace(name="WS", user_id=owner.id).insert()
    clip = Clip(
        id=PydanticObjectId(),
        user_id=owner.id,
        workspace_id=workspace.id,
        file_path="x.wav",
        format="wav",
        visibility=visibility,
        created_at=utcnow() - timedelta(days=1) + timedelta(minutes=minutes),
        title="Song",
        **fields,
    )
    return await clip.insert()


async def _engaged(clip: Clip, kind: str, *, hours_ago: float = 1.0, actor: str | None = None) -> None:
    await ClipEngagement(
        clip_id=clip.id,
        kind=kind,
        actor=actor or f"u{next(_SEQ)}",
        created_at=utcnow() - timedelta(hours=hours_ago),
    ).insert()


async def _ids(client, **params) -> list[str]:
    resp = await client.get(DISCOVER, params=params)
    assert resp.status_code == 200, resp.text
    return [clip["id"] for clip in resp.json()["clips"]]


async def _all_pages(client, **params) -> list[str]:
    ids, cursor = [], None
    while True:
        resp = await client.get(DISCOVER, params={**params, "limit": 1, **({"cursor": cursor} if cursor else {})})
        assert resp.status_code == 200, resp.text
        ids += [clip["id"] for clip in resp.json()["clips"]]
        cursor = resp.json()["next_cursor"]
        if not cursor:
            return ids


class TestPlays:
    async def test_a_listener_counts_once_an_hour_and_each_listener_counts(self, client, settings) -> None:
        clip = await _clip()
        first, second = await _user(), await _user()

        for listener in (first, first, second):
            resp = await client.post(f"{CLIPS}/{clip.id}/play", headers=_auth(listener, settings))
            assert resp.status_code == 204
        await client.post(f"{CLIPS}/{clip.id}/play")
        await client.post(f"{CLIPS}/{clip.id}/play")

        assert (await Clip.get(clip.id)).play_count == 3, "two users and one signed-out address"

    async def test_a_play_from_the_next_hour_counts_again(self, client) -> None:
        clip = await _clip()
        await ClipEngagement(clip_id=clip.id, kind="play", actor="ip:127.0.0.1", bucket="2020-01-01T00").insert()

        await client.post(f"{CLIPS}/{clip.id}/play")

        assert (await Clip.get(clip.id)).play_count == 1

    @pytest.mark.parametrize("visibility", [VisibilityState.PRIVATE, VisibilityState.UNLISTED])
    async def test_a_clip_outside_the_public_pool_is_404(self, client, visibility) -> None:
        clip = await _clip(visibility=visibility)

        assert (await client.post(f"{CLIPS}/{clip.id}/play")).status_code == 404
        assert (await Clip.get(clip.id)).play_count == 0

    async def test_a_removed_clip_is_404(self, client) -> None:
        clip = await _clip(removed_at=utcnow())

        assert (await client.post(f"{CLIPS}/{clip.id}/share")).status_code == 404


class TestLikes:
    async def test_liking_twice_counts_once_and_unliking_undoes_it(self, client, settings) -> None:
        clip, fan = await _clip(), await _user()
        url = f"{CLIPS}/{clip.id}/like"

        assert (await client.put(url, headers=_auth(fan, settings))).json() == {"liked": True, "like_count": 1}
        assert (await client.put(url, headers=_auth(fan, settings))).json()["like_count"] == 1
        assert (await client.delete(url, headers=_auth(fan, settings))).json() == {"liked": False, "like_count": 0}
        assert (await client.delete(url, headers=_auth(fan, settings))).json()["like_count"] == 0

    async def test_a_like_can_be_undone_after_the_clip_leaves_the_public_pool(self, client, settings) -> None:
        clip, fan = await _clip(), await _user()
        url = f"{CLIPS}/{clip.id}/like"
        await client.put(url, headers=_auth(fan, settings))
        await Clip.find_one(Clip.id == clip.id).update({"$set": {"is_public": False, "visibility": "private"}})

        resp = await client.delete(url, headers=_auth(fan, settings))

        assert resp.json() == {"liked": False, "like_count": 0}
        assert await ClipEngagement.find(ClipEngagement.kind == "like").count() == 0
        assert (await client.put(url, headers=_auth(fan, settings))).status_code == 404

    async def test_plays_and_shares_expire_but_likes_are_kept(self, client) -> None:
        indexes = await ClipEngagement.get_pymongo_collection().index_information()

        expiry = indexes["expire_plays_and_shares"]
        assert expiry["expireAfterSeconds"] == 8 * 24 * 3600
        assert expiry["partialFilterExpression"] == {"kind": {"$in": ["play", "share"]}}

    async def test_liking_needs_a_signed_in_user(self, client) -> None:
        clip = await _clip()

        assert (await client.put(f"{CLIPS}/{clip.id}/like")).status_code == 401

    async def test_cards_show_plays_likes_and_whether_the_viewer_liked_but_not_shares(self, client, settings) -> None:
        liked, other = await _clip(minutes=1), await _clip()
        fan = await _user()
        await client.put(f"{CLIPS}/{liked.id}/like", headers=_auth(fan, settings))
        await client.post(f"{CLIPS}/{liked.id}/play", headers=_auth(fan, settings))
        await client.post(f"{CLIPS}/{liked.id}/share", headers=_auth(fan, settings))

        resp = await client.get(DISCOVER, headers=_auth(fan, settings))

        cards = {card["id"]: card for card in resp.json()["clips"]}
        mine = cards[str(liked.id)]
        assert (mine["play_count"], mine["like_count"], mine["viewer_liked"]) == (1, 1, True)
        assert "share_count" not in mine
        assert cards[str(other.id)]["viewer_liked"] is False
        public = (await client.get(f"{CLIPS}/{liked.id}/public")).json()
        assert (public["like_count"], public["viewer_liked"]) == (1, False)


class TestShares:
    async def test_a_user_counts_once_a_day(self, client, settings) -> None:
        clip, fan = await _clip(), await _user()

        for _ in range(3):
            await client.post(f"{CLIPS}/{clip.id}/share", headers=_auth(fan, settings))

        assert (await Clip.get(clip.id)).share_count == 1


class TestPopular:
    async def test_charts_rank_by_all_time_plays_across_pages(self, client) -> None:
        quiet, loud, middling = await _clip(play_count=1), await _clip(play_count=9), await _clip(play_count=4)
        hidden = await _clip(play_count=50, visibility=VisibilityState.PRIVATE)

        ranked = await _all_pages(client, sort="popular")

        assert ranked == [str(loud.id), str(middling.id), str(quiet.id)]
        assert str(hidden.id) not in ranked

    async def test_clips_predating_the_counters_still_page(self, client) -> None:
        played = await _clip(play_count=3)
        legacy = await _clip()
        await Clip.get_pymongo_collection().update_one(
            {"_id": legacy.id}, {"$unset": {"play_count": "", "like_count": "", "share_count": ""}}
        )

        assert await engagement.backfill_counters() == 1
        assert await _all_pages(client, sort="popular") == [str(played.id), str(legacy.id)]


class TestTrending:
    async def test_likes_weigh_three_plays_and_shares_five(self, client) -> None:
        played, liked, shared = await _clip(), await _clip(), await _clip()
        for _ in range(2):
            await _engaged(played, "play")
        await _engaged(liked, "like")
        await _engaged(shared, "share")

        assert await _all_pages(client, sort="trending_24h") == [str(shared.id), str(liked.id), str(played.id)]

    async def test_the_window_decides_what_counts(self, client) -> None:
        recent, older = await _clip(), await _clip()
        await _engaged(recent, "play", hours_ago=2)
        for _ in range(3):
            await _engaged(older, "play", hours_ago=48)
        await _engaged(older, "play", hours_ago=24 * 8)

        assert await _ids(client, sort="trending_24h") == [str(recent.id)]
        assert await _ids(client, sort="trending_7d") == [str(older.id), str(recent.id)]

    async def test_only_the_public_pool_trends_and_there_is_no_total(self, client) -> None:
        public, private = await _clip(), await _clip(visibility=VisibilityState.PRIVATE)
        await _engaged(public, "play")
        for _ in range(5):
            await _engaged(private, "share")

        resp = await client.get(DISCOVER, params={"sort": "trending_7d"})

        assert [clip["id"] for clip in resp.json()["clips"]] == [str(public.id)]
        assert resp.json()["total"] is None

    async def test_the_ranking_is_reused_for_a_minute_then_recomputed(self, client, monkeypatch) -> None:
        first, second = await _clip(), await _clip()
        await _engaged(first, "play")
        assert await _ids(client, sort="trending_7d") == [str(first.id)]

        for _ in range(3):
            await _engaged(second, "play")
        assert await _ids(client, sort="trending_7d") == [str(first.id)], "inside the minute, the cached ranking"

        monkeypatch.setattr(discovery, "TRENDING_TTL_SECONDS", 0.0)
        assert await _ids(client, sort="trending_7d") == [str(second.id), str(first.id)]

    async def test_concurrent_requests_share_one_rebuild(self, client, monkeypatch) -> None:
        await _engaged(await _clip(), "play")
        real = discovery._rank_trending
        rebuilds = 0

        async def counted(sort: str):
            nonlocal rebuilds
            rebuilds += 1
            await asyncio.sleep(0.05)
            return await real(sort)

        monkeypatch.setattr(discovery, "_rank_trending", counted)

        await asyncio.gather(*(client.get(DISCOVER, params={"sort": "trending_7d"}) for _ in range(5)))

        assert rebuilds == 1

    async def test_a_timed_out_rebuild_keeps_serving_the_last_ranking(self, client, monkeypatch) -> None:
        ranked = await _clip()
        await _engaged(ranked, "play")
        assert await _ids(client, sort="trending_7d") == [str(ranked.id)]

        async def timed_out(sort: str):
            raise ExecutionTimeout("operation exceeded time limit")

        monkeypatch.setattr(discovery, "_rank_trending", timed_out)
        monkeypatch.setattr(discovery, "TRENDING_TTL_SECONDS", 0.0)

        assert await _ids(client, sort="trending_7d") == [str(ranked.id)]

    async def test_a_ranked_clip_that_went_private_is_skipped(self, client) -> None:
        hidden, shown = await _clip(), await _clip()
        for _ in range(3):
            await _engaged(hidden, "play")
        await _engaged(shown, "play")
        assert await _ids(client, sort="trending_7d") == [str(hidden.id), str(shown.id)]

        await Clip.find_one(Clip.id == hidden.id).update({"$set": {"is_public": False, "visibility": "private"}})

        assert await _ids(client, sort="trending_7d") == [str(shown.id)]

    async def test_trending_cannot_be_searched(self, client) -> None:
        resp = await client.get(DISCOVER, params={"sort": "trending_7d", "q": "song"})

        assert resp.status_code == 422

    async def test_a_cursor_from_one_window_is_refused_by_the_other(self, client) -> None:
        for _ in range(2):
            await _engaged(await _clip(), "play")
        cursor = (await client.get(DISCOVER, params={"sort": "trending_24h", "limit": 1})).json()["next_cursor"]

        resp = await client.get(DISCOVER, params={"sort": "trending_7d", "cursor": cursor})

        assert resp.status_code == 422


class TestStaffPicks:
    async def test_admins_pick_and_unpick_and_picks_list_newest_first(self, client, settings) -> None:
        admin = await _user(is_admin=True)
        first, second, never = await _clip(), await _clip(), await _clip()
        await client.put(f"{ADMIN}/{first.id}/staff-pick", headers=_auth(admin, settings))
        await client.put(f"{ADMIN}/{second.id}/staff-pick", headers=_auth(admin, settings))

        assert await _all_pages(client, sort="staff_picks") == [str(second.id), str(first.id)]
        assert str(never.id) not in await _ids(client, sort="staff_picks")

        resp = await client.delete(f"{ADMIN}/{second.id}/staff-pick", headers=_auth(admin, settings))
        assert resp.json() == {"staff_picked_at": None}
        assert await _ids(client, sort="staff_picks") == [str(first.id)]
        log = await ModerationLogEntry.find(ModerationLogEntry.target_id == str(second.id)).sort("created_at").to_list()
        assert [(entry.action, entry.actor_id) for entry in log] == [
            ("staff_pick", admin.id),
            ("staff_unpick", admin.id),
        ]

    async def test_a_private_pick_stays_out_of_the_listing(self, client, settings) -> None:
        admin = await _user(is_admin=True)
        private = await _clip(visibility=VisibilityState.PRIVATE)
        await client.put(f"{ADMIN}/{private.id}/staff-pick", headers=_auth(admin, settings))

        assert await _ids(client, sort="staff_picks") == []

    async def test_only_admins_pick(self, client, settings) -> None:
        clip = await _clip()

        resp = await client.put(f"{ADMIN}/{clip.id}/staff-pick", headers=_auth(await _user(), settings))

        assert resp.status_code == 403

    async def test_an_unknown_clip_is_404(self, client, settings) -> None:
        admin = await _user(is_admin=True)

        resp = await client.put(f"{ADMIN}/{PydanticObjectId()}/staff-pick", headers=_auth(admin, settings))

        assert resp.status_code == 404


class TestAdminEngagement:
    async def test_admins_see_shares(self, client, settings) -> None:
        clip, fan, admin = await _clip(), await _user(), await _user(is_admin=True)
        await client.post(f"{CLIPS}/{clip.id}/share", headers=_auth(fan, settings))

        resp = await client.get(f"{ADMIN}/{clip.id}/engagement", headers=_auth(admin, settings))

        assert resp.json() == {"play_count": 0, "like_count": 0, "share_count": 1, "staff_picked_at": None}
