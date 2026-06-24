"""Tests for the similar-clips endpoint (US-14.4, issue #141).

``GET /clips/{id}/similar`` returns up to 50 clips ranked by similarity to a
seed clip — shared style tags, BPM proximity (±10%), related key, and matching
model/generation-mode. Scope filters the candidate pool to the caller's own
clips, public clips, or both.

The 401 auth-gate and the pure scoring helpers run in CI (no DB); the endpoint
behaviour is ``integration`` and drives the real app over a local MongoDB.
"""

import itertools
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest
from beanie import PydanticObjectId
from fastapi.testclient import TestClient

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.models import Clip, Workspace
from acemusic.api.services import users as user_service
from acemusic.api.services.clips import (
    compute_similarity_score,
    keys_are_related,
)
from acemusic.api.settings import ApiSettings

CLIPS_URL = f"{API_V1_PREFIX}/clips"


# ---------------------------------------------------------------------------
# Auth gate — runs in CI (no DB)
# ---------------------------------------------------------------------------


class TestAuthGate:
    def test_missing_auth_header_returns_401(self) -> None:
        client = TestClient(create_app())
        resp = client.get(f"{CLIPS_URL}/{PydanticObjectId()}/similar")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Pure scoring helpers — run in CI (no DB)
# ---------------------------------------------------------------------------


class TestKeysAreRelated:
    def test_exact_match_case_insensitive(self) -> None:
        assert keys_are_related("C major", "c MAJOR") is True

    def test_relative_pair(self) -> None:
        assert keys_are_related("C major", "A minor") is True
        assert keys_are_related("A minor", "C major") is True

    def test_unrelated_keys(self) -> None:
        assert keys_are_related("C major", "G major") is False

    def test_none_inputs(self) -> None:
        assert keys_are_related(None, "C major") is False
        assert keys_are_related("C major", None) is False
        assert keys_are_related(None, None) is False


def _clip(**kwargs):
    # The scoring helpers read plain attributes only; a namespace avoids the
    # Beanie collection init that constructing a real Clip needs (no DB in CI).
    base = dict(style_tags=[], bpm=None, key=None, model=None, generation_mode=None)
    base.update(kwargs)
    return SimpleNamespace(**base)


class TestComputeSimilarityScore:
    def test_style_tag_overlap_counts_each_match(self) -> None:
        seed = _clip(style_tags=["lofi", "chill", "jazzy"])
        cand = _clip(style_tags=["LOFI", "CHILL", "trap"])
        # two overlapping tags (case-insensitive), nothing else set on seed
        assert compute_similarity_score(seed, cand) == 2

    def test_bpm_within_ten_percent(self) -> None:
        seed = _clip(bpm=100)
        assert compute_similarity_score(seed, _clip(bpm=109)) == 1
        assert compute_similarity_score(seed, _clip(bpm=91)) == 1

    def test_bpm_outside_ten_percent(self) -> None:
        seed = _clip(bpm=100)
        assert compute_similarity_score(seed, _clip(bpm=120)) == 0
        assert compute_similarity_score(seed, _clip(bpm=80)) == 0

    def test_related_key_adds_point(self) -> None:
        seed = _clip(key="C major")
        assert compute_similarity_score(seed, _clip(key="A minor")) == 1
        assert compute_similarity_score(seed, _clip(key="G major")) == 0

    def test_model_and_generation_mode_must_both_match(self) -> None:
        seed = _clip(model="ace-step-v1", generation_mode="text2music")
        assert compute_similarity_score(seed, _clip(model="ace-step-v1", generation_mode="text2music")) == 1
        # only model matches -> no point
        assert compute_similarity_score(seed, _clip(model="ace-step-v1", generation_mode="cover")) == 0

    def test_null_seed_fields_are_skipped(self) -> None:
        # seed has no metadata at all -> every criterion skipped -> score 0
        seed = _clip()
        cand = _clip(style_tags=["lofi"], bpm=100, key="C major", model="m", generation_mode="g")
        assert compute_similarity_score(seed, cand) == 0


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


async def _make_workspace(user, name: str = "WS") -> Workspace:
    workspace = Workspace(name=name, user_id=user.id)
    await workspace.insert()
    return workspace


_SEQ = itertools.count(1)


async def _insert_clip(
    user,
    workspace: Workspace,
    *,
    title: str | None = None,
    style_tags: list[str] | None = None,
    bpm: int | None = None,
    key: str | None = None,
    model: str | None = None,
    generation_mode: str | None = None,
    is_public: bool = False,
    created_at: datetime | None = None,
) -> Clip:
    if created_at is None:
        created_at = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=next(_SEQ))
    clip_id = PydanticObjectId()
    clip = Clip(
        id=clip_id,
        user_id=user.id,
        workspace_id=workspace.id,
        file_path=f"{user.id}/{workspace.id}/clips/{clip_id}.wav",
        format="wav",
        title=title,
        style_tags=style_tags or [],
        bpm=bpm,
        key=key,
        model=model,
        generation_mode=generation_mode,
        is_public=is_public,
        created_at=created_at,
    )
    await clip.insert()
    return clip


def _ids(payload) -> list[str]:
    return [c["id"] for c in payload["clips"]]


@pytest.mark.integration
class TestSimilarClips:
    async def test_shared_style_tag_appears(self, client, settings) -> None:
        user = await _make_user("sim-tag@example.com")
        ws = await _make_workspace(user)
        seed = await _insert_clip(user, ws, style_tags=["lofi", "chill"], bpm=100)
        match = await _insert_clip(user, ws, style_tags=["lofi"], bpm=200)
        await _insert_clip(user, ws, style_tags=["metal"], bpm=200)  # no overlap, far bpm

        resp = await client.get(f"{CLIPS_URL}/{seed.id}/similar", headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        assert _ids(resp.json()) == [str(match.id)]

    async def test_style_tag_match_is_case_insensitive(self, client, settings) -> None:
        # Candidate qualifies only by a differently-cased tag (BPM far apart),
        # so the DB filter — not just the scorer — must match case-insensitively.
        user = await _make_user("sim-tagcase@example.com")
        ws = await _make_workspace(user)
        seed = await _insert_clip(user, ws, style_tags=["LoFi"], bpm=100)
        match = await _insert_clip(user, ws, style_tags=["lofi"], bpm=300)

        resp = await client.get(f"{CLIPS_URL}/{seed.id}/similar", headers=_auth_headers(user, settings))
        assert _ids(resp.json()) == [str(match.id)]

    async def test_bpm_proximity_appears(self, client, settings) -> None:
        user = await _make_user("sim-bpm@example.com")
        ws = await _make_workspace(user)
        seed = await _insert_clip(user, ws, style_tags=["a"], bpm=100)
        near = await _insert_clip(user, ws, style_tags=["z"], bpm=108)  # within 10%, no tag overlap
        await _insert_clip(user, ws, style_tags=["z"], bpm=140)  # too far, no tag overlap

        resp = await client.get(f"{CLIPS_URL}/{seed.id}/similar", headers=_auth_headers(user, settings))
        assert _ids(resp.json()) == [str(near.id)]

    async def test_ordered_by_score_descending(self, client, settings) -> None:
        user = await _make_user("sim-order@example.com")
        ws = await _make_workspace(user)
        seed = await _insert_clip(user, ws, style_tags=["a", "b", "c"], bpm=100, key="C major")
        low = await _insert_clip(user, ws, style_tags=["a"], bpm=300)  # 1 tag
        high = await _insert_clip(user, ws, style_tags=["a", "b", "c"], bpm=100, key="A minor")  # 3 tags+bpm+key

        resp = await client.get(f"{CLIPS_URL}/{seed.id}/similar", headers=_auth_headers(user, settings))
        assert _ids(resp.json()) == [str(high.id), str(low.id)]

    async def test_seed_excluded(self, client, settings) -> None:
        user = await _make_user("sim-seed@example.com")
        ws = await _make_workspace(user)
        seed = await _insert_clip(user, ws, style_tags=["lofi"], bpm=100)

        resp = await client.get(f"{CLIPS_URL}/{seed.id}/similar", headers=_auth_headers(user, settings))
        assert str(seed.id) not in _ids(resp.json())

    async def test_scope_mine_excludes_others_public(self, client, settings) -> None:
        owner = await _make_user("sim-owner@example.com")
        other = await _make_user("sim-other@example.com")
        ws = await _make_workspace(owner)
        ws_other = await _make_workspace(other)
        seed = await _insert_clip(owner, ws, style_tags=["lofi"], bpm=100)
        mine = await _insert_clip(owner, ws, style_tags=["lofi"], bpm=100)
        await _insert_clip(other, ws_other, style_tags=["lofi"], bpm=100, is_public=True)

        resp = await client.get(f"{CLIPS_URL}/{seed.id}/similar?scope=mine", headers=_auth_headers(owner, settings))
        assert _ids(resp.json()) == [str(mine.id)]

    async def test_scope_public_includes_others_public_only(self, client, settings) -> None:
        owner = await _make_user("sim-pub-owner@example.com")
        other = await _make_user("sim-pub-other@example.com")
        ws = await _make_workspace(owner)
        ws_other = await _make_workspace(other)
        seed = await _insert_clip(owner, ws, style_tags=["lofi"], bpm=100)
        await _insert_clip(owner, ws, style_tags=["lofi"], bpm=100, is_public=False)  # own private, excluded
        pub = await _insert_clip(other, ws_other, style_tags=["lofi"], bpm=100, is_public=True)

        resp = await client.get(f"{CLIPS_URL}/{seed.id}/similar?scope=public", headers=_auth_headers(owner, settings))
        assert _ids(resp.json()) == [str(pub.id)]

    async def test_scope_all_includes_both(self, client, settings) -> None:
        owner = await _make_user("sim-all-owner@example.com")
        other = await _make_user("sim-all-other@example.com")
        ws = await _make_workspace(owner)
        ws_other = await _make_workspace(other)
        seed = await _insert_clip(owner, ws, style_tags=["lofi"], bpm=100)
        mine = await _insert_clip(owner, ws, style_tags=["lofi"], bpm=100, is_public=False)
        pub = await _insert_clip(other, ws_other, style_tags=["lofi"], bpm=100, is_public=True)

        resp = await client.get(f"{CLIPS_URL}/{seed.id}/similar?scope=all", headers=_auth_headers(owner, settings))
        assert set(_ids(resp.json())) == {str(mine.id), str(pub.id)}

    async def test_limit_respected(self, client, settings) -> None:
        user = await _make_user("sim-limit@example.com")
        ws = await _make_workspace(user)
        seed = await _insert_clip(user, ws, style_tags=["lofi"], bpm=100)
        for _ in range(3):
            await _insert_clip(user, ws, style_tags=["lofi"], bpm=100)

        resp = await client.get(f"{CLIPS_URL}/{seed.id}/similar?limit=2", headers=_auth_headers(user, settings))
        body = resp.json()
        assert len(body["clips"]) == 2
        assert body["total"] == 3
        assert body["limit"] == 2

    async def test_limit_over_max_returns_422(self, client, settings) -> None:
        user = await _make_user("sim-422@example.com")
        ws = await _make_workspace(user)
        seed = await _insert_clip(user, ws, style_tags=["lofi"], bpm=100)
        resp = await client.get(f"{CLIPS_URL}/{seed.id}/similar?limit=51", headers=_auth_headers(user, settings))
        assert resp.status_code == 422

    async def test_unknown_clip_returns_404(self, client, settings) -> None:
        user = await _make_user("sim-404@example.com")
        resp = await client.get(f"{CLIPS_URL}/{PydanticObjectId()}/similar", headers=_auth_headers(user, settings))
        assert resp.status_code == 404

    async def test_others_private_seed_returns_403(self, client, settings) -> None:
        owner = await _make_user("sim-403-owner@example.com")
        other = await _make_user("sim-403-other@example.com")
        ws = await _make_workspace(owner)
        seed = await _insert_clip(owner, ws, style_tags=["lofi"], bpm=100, is_public=False)

        resp = await client.get(f"{CLIPS_URL}/{seed.id}/similar", headers=_auth_headers(other, settings))
        assert resp.status_code == 403

    async def test_no_matches_returns_empty_200(self, client, settings) -> None:
        user = await _make_user("sim-empty@example.com")
        ws = await _make_workspace(user)
        seed = await _insert_clip(user, ws, style_tags=["unique-tag"], bpm=100)
        await _insert_clip(user, ws, style_tags=["nothing"], bpm=300)

        resp = await client.get(f"{CLIPS_URL}/{seed.id}/similar", headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        body = resp.json()
        assert body["clips"] == []
        assert body["total"] == 0

    async def test_seed_without_tags_or_bpm_returns_empty(self, client, settings) -> None:
        # A seed with no style tags and no BPM has no base-similarity criteria.
        user = await _make_user("sim-nullseed@example.com")
        ws = await _make_workspace(user)
        seed = await _insert_clip(user, ws, key="C major")
        await _insert_clip(user, ws, key="A minor")

        resp = await client.get(f"{CLIPS_URL}/{seed.id}/similar", headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        assert resp.json()["clips"] == []

    async def test_null_metadata_candidate_handled(self, client, settings) -> None:
        # A candidate that shares a tag but has null bpm/key/model must not error.
        user = await _make_user("sim-nullcand@example.com")
        ws = await _make_workspace(user)
        seed = await _insert_clip(user, ws, style_tags=["lofi"], bpm=100, key="C major", model="m")
        bare = await _insert_clip(user, ws, style_tags=["lofi"])

        resp = await client.get(f"{CLIPS_URL}/{seed.id}/similar", headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        assert _ids(resp.json()) == [str(bare.id)]
