"""Tests for the clip lineage endpoints (US-10.6, issue #86).

Covers ``GET /clips/{id}/lineage`` (full ancestry tree, parents → grandparents →
… up to the original generation) and ``GET /clips/{id}/children`` (clips derived
from a clip). The lineage graph is already written by every derive operation
(extend/cover/remix/mashup/stems set ``parent_clip_ids``); these endpoints only
read it back.

The 401 auth-gate tests run in CI (no DB); the rest are ``integration`` and drive
the real app with ``httpx.AsyncClient`` over a local MongoDB.
"""

import itertools
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from beanie import PydanticObjectId
from fastapi.testclient import TestClient

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.models import Clip, Workspace
from acemusic.api.services import users as user_service
from acemusic.api.services.clips import MAX_LINEAGE_DEPTH
from acemusic.api.settings import ApiSettings

CLIPS_URL = f"{API_V1_PREFIX}/clips"


# ---------------------------------------------------------------------------
# Auth gate — runs in CI (no DB)
# ---------------------------------------------------------------------------


class TestAuthGate:
    @pytest.mark.parametrize(
        "url",
        [
            f"{CLIPS_URL}/{PydanticObjectId()}/lineage",
            f"{CLIPS_URL}/{PydanticObjectId()}/children",
        ],
    )
    def test_missing_auth_header_returns_401(self, url: str) -> None:
        client = TestClient(create_app())
        resp = client.get(url)
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
    parents: list[Clip] | None = None,
    generation_mode: str | None = None,
    created_at: datetime | None = None,
) -> Clip:
    # Monotonic created_at keeps ordering deterministic across clips inserted
    # within the same millisecond.
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
        parent_clip_ids=[p.id for p in (parents or [])],
        generation_mode=generation_mode,
        created_at=created_at,
    )
    await clip.insert()
    return clip


# ---------------------------------------------------------------------------
# Lineage (ancestry)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestLineage:
    async def test_extend_child_shows_its_parent(self, client, settings) -> None:
        """AC: a clip created via extend shows its parent in the lineage response."""
        user = await _make_user("lineage-extend@example.com")
        ws = await _make_workspace(user)
        original = await _insert_clip(user, ws, title="original")
        extended = await _insert_clip(user, ws, title="extended", parents=[original], generation_mode="extend")

        resp = await client.get(f"{CLIPS_URL}/{extended.id}/lineage", headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        body = resp.json()
        assert body["clip_id"] == str(extended.id)
        assert body["max_depth"] == MAX_LINEAGE_DEPTH
        assert body["truncated"] is False

        by_depth = {n["depth"]: n for n in body["nodes"]}
        # depth 0 is the queried clip itself; depth 1 is its parent.
        assert by_depth[0]["id"] == str(extended.id)
        assert by_depth[0]["generation_mode"] == "extend"
        assert by_depth[1]["id"] == str(original.id)
        assert by_depth[1]["title"] == "original"
        assert by_depth[1]["created_at"]

    async def test_mashup_child_shows_all_sources(self, client, settings) -> None:
        """AC: a clip with multiple parents (mashup) shows all sources."""
        user = await _make_user("lineage-mashup@example.com")
        ws = await _make_workspace(user)
        a = await _insert_clip(user, ws, title="A")
        b = await _insert_clip(user, ws, title="B")
        c = await _insert_clip(user, ws, title="C")
        mashup = await _insert_clip(user, ws, title="mashup", parents=[a, b, c], generation_mode="mashup")

        resp = await client.get(f"{CLIPS_URL}/{mashup.id}/lineage", headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        nodes = resp.json()["nodes"]
        depth1_ids = {n["id"] for n in nodes if n["depth"] == 1}
        assert depth1_ids == {str(a.id), str(b.id), str(c.id)}

    async def test_full_chain_returned_to_original(self, client, settings) -> None:
        """AC: lineage traversal returns the full tree up to the original generation."""
        user = await _make_user("lineage-chain@example.com")
        ws = await _make_workspace(user)
        clips = [await _insert_clip(user, ws, title="gen-0")]
        for i in range(1, 6):
            clips.append(await _insert_clip(user, ws, title=f"gen-{i}", parents=[clips[-1]], generation_mode="extend"))

        resp = await client.get(f"{CLIPS_URL}/{clips[-1].id}/lineage", headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        body = resp.json()
        assert body["truncated"] is False
        # All six generations are present, each at its own depth.
        depth_by_id = {n["id"]: n["depth"] for n in body["nodes"]}
        assert depth_by_id[str(clips[-1].id)] == 0
        assert depth_by_id[str(clips[0].id)] == 5
        assert len(body["nodes"]) == 6

    async def test_diamond_lineage_lists_shared_ancestor_once(self, client, settings) -> None:
        """A clip whose two parents share a grandparent lists the grandparent once."""
        user = await _make_user("lineage-diamond@example.com")
        ws = await _make_workspace(user)
        root = await _insert_clip(user, ws, title="root")
        left = await _insert_clip(user, ws, title="left", parents=[root], generation_mode="cover")
        right = await _insert_clip(user, ws, title="right", parents=[root], generation_mode="remix")
        merged = await _insert_clip(user, ws, title="merged", parents=[left, right], generation_mode="mashup")

        resp = await client.get(f"{CLIPS_URL}/{merged.id}/lineage", headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        ids = [n["id"] for n in resp.json()["nodes"]]
        assert ids.count(str(root.id)) == 1

    async def test_depth_cap_truncates(self, client, settings) -> None:
        """AC: maximum lineage depth is 50; deeper chains report truncated=True."""
        user = await _make_user("lineage-cap@example.com")
        ws = await _make_workspace(user)
        clip = await _insert_clip(user, ws, title="origin")
        # One more generation than the cap so an ancestor sits beyond depth 50.
        for i in range(MAX_LINEAGE_DEPTH + 1):
            clip = await _insert_clip(user, ws, title=f"g{i}", parents=[clip], generation_mode="extend")

        resp = await client.get(f"{CLIPS_URL}/{clip.id}/lineage", headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        body = resp.json()
        assert body["truncated"] is True
        assert max(n["depth"] for n in body["nodes"]) == MAX_LINEAGE_DEPTH

    async def test_original_clip_has_empty_lineage(self, client, settings) -> None:
        user = await _make_user("lineage-root@example.com")
        ws = await _make_workspace(user)
        clip = await _insert_clip(user, ws, title="solo")

        resp = await client.get(f"{CLIPS_URL}/{clip.id}/lineage", headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        body = resp.json()
        assert [n["id"] for n in body["nodes"]] == [str(clip.id)]
        assert body["nodes"][0]["depth"] == 0
        assert body["truncated"] is False

    async def test_twenty_level_chain_resolves_quickly(self, client, settings) -> None:
        """AC: lineage queries complete within 500ms for chains up to 20 levels deep."""
        user = await _make_user("lineage-perf@example.com")
        ws = await _make_workspace(user)
        clip = await _insert_clip(user, ws, title="g0")
        for i in range(1, 21):
            clip = await _insert_clip(user, ws, title=f"g{i}", parents=[clip], generation_mode="extend")

        headers = _auth_headers(user, settings)
        start = time.perf_counter()
        resp = await client.get(f"{CLIPS_URL}/{clip.id}/lineage", headers=headers)
        elapsed = time.perf_counter() - start
        assert resp.status_code == 200
        assert len(resp.json()["nodes"]) == 21
        assert elapsed < 0.5

    async def test_unknown_clip_returns_404(self, client, settings) -> None:
        user = await _make_user("lineage-unknown@example.com")
        resp = await client.get(f"{CLIPS_URL}/{PydanticObjectId()}/lineage", headers=_auth_headers(user, settings))
        assert resp.status_code == 404

    async def test_malformed_id_returns_404(self, client, settings) -> None:
        user = await _make_user("lineage-malformed@example.com")
        resp = await client.get(f"{CLIPS_URL}/not-an-object-id/lineage", headers=_auth_headers(user, settings))
        assert resp.status_code == 404

    async def test_other_users_clip_returns_404(self, client, settings) -> None:
        owner = await _make_user("lineage-owner@example.com")
        other = await _make_user("lineage-other@example.com")
        ws = await _make_workspace(owner)
        clip = await _insert_clip(owner, ws, title="theirs")

        resp = await client.get(f"{CLIPS_URL}/{clip.id}/lineage", headers=_auth_headers(other, settings))
        assert resp.status_code == 404

    async def test_other_users_ancestors_are_excluded(self, client, settings) -> None:
        """Lineage is owner-scoped: an ancestor owned by another user is not leaked."""
        owner = await _make_user("lineage-scope-owner@example.com")
        other = await _make_user("lineage-scope-other@example.com")
        owner_ws = await _make_workspace(owner)
        other_ws = await _make_workspace(other)
        foreign_root = await _insert_clip(other, other_ws, title="foreign")
        child = await _insert_clip(owner, owner_ws, title="mine", parents=[foreign_root], generation_mode="cover")

        resp = await client.get(f"{CLIPS_URL}/{child.id}/lineage", headers=_auth_headers(owner, settings))
        assert resp.status_code == 200
        ids = {n["id"] for n in resp.json()["nodes"]}
        assert str(foreign_root.id) not in ids
        assert ids == {str(child.id)}


# ---------------------------------------------------------------------------
# Children (descendants — direct)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestChildren:
    async def test_returns_all_derived_clips(self, client, settings) -> None:
        """AC: children endpoint returns all clips derived from a given clip."""
        user = await _make_user("children-all@example.com")
        ws = await _make_workspace(user)
        source = await _insert_clip(user, ws, title="source")
        extended = await _insert_clip(user, ws, title="extended", parents=[source], generation_mode="extend")
        covered = await _insert_clip(user, ws, title="covered", parents=[source], generation_mode="cover")
        # A grandchild (child of `extended`) is NOT a direct child of `source`.
        await _insert_clip(user, ws, title="grandchild", parents=[extended], generation_mode="extend")

        resp = await client.get(f"{CLIPS_URL}/{source.id}/children", headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        body = resp.json()
        assert body["clip_id"] == str(source.id)
        assert body["total"] == 2
        assert {c["id"] for c in body["children"]} == {str(extended.id), str(covered.id)}

    async def test_includes_mashup_children(self, client, settings) -> None:
        """A clip used as one of several mashup sources counts the mashup as its child."""
        user = await _make_user("children-mashup@example.com")
        ws = await _make_workspace(user)
        a = await _insert_clip(user, ws, title="A")
        b = await _insert_clip(user, ws, title="B")
        mashup = await _insert_clip(user, ws, title="mashup", parents=[a, b], generation_mode="mashup")

        resp = await client.get(f"{CLIPS_URL}/{a.id}/children", headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        assert [c["id"] for c in resp.json()["children"]] == [str(mashup.id)]

    async def test_leaf_clip_has_no_children(self, client, settings) -> None:
        user = await _make_user("children-leaf@example.com")
        ws = await _make_workspace(user)
        clip = await _insert_clip(user, ws, title="leaf")

        resp = await client.get(f"{CLIPS_URL}/{clip.id}/children", headers=_auth_headers(user, settings))
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["children"] == []

    async def test_children_are_owner_scoped(self, client, settings) -> None:
        """Another user's derived clip never appears in the owner's children view."""
        owner = await _make_user("children-owner@example.com")
        other = await _make_user("children-other@example.com")
        owner_ws = await _make_workspace(owner)
        other_ws = await _make_workspace(other)
        source = await _insert_clip(owner, owner_ws, title="shared-source")
        mine = await _insert_clip(owner, owner_ws, title="mine", parents=[source], generation_mode="extend")
        # Another user derived from the same source id (e.g. a public clip).
        await _insert_clip(other, other_ws, title="theirs", parents=[source], generation_mode="extend")

        resp = await client.get(f"{CLIPS_URL}/{source.id}/children", headers=_auth_headers(owner, settings))
        assert resp.status_code == 200
        assert [c["id"] for c in resp.json()["children"]] == [str(mine.id)]

    async def test_unknown_clip_returns_404(self, client, settings) -> None:
        user = await _make_user("children-unknown@example.com")
        resp = await client.get(f"{CLIPS_URL}/{PydanticObjectId()}/children", headers=_auth_headers(user, settings))
        assert resp.status_code == 404

    async def test_other_users_clip_returns_404(self, client, settings) -> None:
        owner = await _make_user("children-404-owner@example.com")
        other = await _make_user("children-404-other@example.com")
        ws = await _make_workspace(owner)
        clip = await _insert_clip(owner, ws, title="theirs")

        resp = await client.get(f"{CLIPS_URL}/{clip.id}/children", headers=_auth_headers(other, settings))
        assert resp.status_code == 404
