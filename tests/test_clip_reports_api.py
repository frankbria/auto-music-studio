"""User reporting of clips (US-27.2).

A signed-in listener reports someone else's reachable clip with a category and
optional details; the report lands in the admin moderation queue. One report per
user per clip — a repeat is a 409 the UI shows verbatim.
"""

import itertools

import httpx
import pytest
from beanie import PydanticObjectId
from fastapi.testclient import TestClient

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.models import Clip, ClipReport, VisibilityState, Workspace
from acemusic.api.settings import ApiSettings
from tests.users import make_user

CLIPS_URL = f"{API_V1_PREFIX}/clips"
QUEUE_URL = f"{API_V1_PREFIX}/admin/moderation/reports"

_SEQ = itertools.count(1)


class TestAuthGate:
    def test_report_requires_auth(self) -> None:
        resp = TestClient(create_app()).post(f"{CLIPS_URL}/{PydanticObjectId()}/report", json={"category": "spam"})
        assert resp.status_code == 401


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


async def _user(**fields):
    return await make_user(f"report-{next(_SEQ)}@example.com", **fields)


async def _clip(owner, visibility: VisibilityState = VisibilityState.PUBLIC) -> Clip:
    workspace = Workspace(name=f"WS-{next(_SEQ)}", user_id=owner.id)
    await workspace.insert()
    clip_id = PydanticObjectId()
    clip = Clip(
        id=clip_id,
        user_id=owner.id,
        workspace_id=workspace.id,
        file_path=f"{owner.id}/{workspace.id}/clips/{clip_id}.wav",
        format="wav",
        title="Reported",
        visibility=visibility,
    )
    await clip.insert()
    return clip


@pytest.mark.integration
class TestReportClip:
    async def test_report_is_stored_and_confirmed(self, client, settings):
        owner, reporter = await _user(), await _user()
        clip = await _clip(owner)

        resp = await client.post(
            f"{CLIPS_URL}/{clip.id}/report",
            json={"category": "copyright", "details": "  This is my song  "},
            headers=_auth(reporter, settings),
        )

        assert resp.status_code == 201, resp.text
        assert resp.json()["detail"] == "Report received. Our team will review it."
        report = await ClipReport.find_one(ClipReport.clip_id == clip.id)
        assert report.reporter_id == reporter.id
        assert report.category == "copyright"
        assert report.details == "This is my song"

    async def test_duplicate_report_is_409(self, client, settings):
        owner, reporter = await _user(), await _user()
        clip = await _clip(owner)
        url = f"{CLIPS_URL}/{clip.id}/report"

        first = await client.post(url, json={"category": "spam"}, headers=_auth(reporter, settings))
        second = await client.post(url, json={"category": "other"}, headers=_auth(reporter, settings))

        assert first.status_code == 201
        assert second.status_code == 409
        assert second.json()["detail"] == "You have already reported this clip."
        assert await ClipReport.find(ClipReport.clip_id == clip.id).count() == 1

    async def test_different_users_can_each_report(self, client, settings):
        owner = await _user()
        clip = await _clip(owner)
        for _ in range(2):
            resp = await client.post(
                f"{CLIPS_URL}/{clip.id}/report", json={"category": "spam"}, headers=_auth(await _user(), settings)
            )
            assert resp.status_code == 201
        assert await ClipReport.find(ClipReport.clip_id == clip.id).count() == 2

    async def test_unlisted_clip_is_reportable(self, client, settings):
        clip = await _clip(await _user(), VisibilityState.UNLISTED)
        resp = await client.post(
            f"{CLIPS_URL}/{clip.id}/report", json={"category": "spam"}, headers=_auth(await _user(), settings)
        )
        assert resp.status_code == 201

    async def test_private_clip_is_403(self, client, settings):
        clip = await _clip(await _user(), VisibilityState.PRIVATE)
        resp = await client.post(
            f"{CLIPS_URL}/{clip.id}/report", json={"category": "spam"}, headers=_auth(await _user(), settings)
        )
        assert resp.status_code == 403
        assert await ClipReport.find(ClipReport.clip_id == clip.id).count() == 0

    async def test_unknown_clip_is_404(self, client, settings):
        resp = await client.post(
            f"{CLIPS_URL}/{PydanticObjectId()}/report",
            json={"category": "spam"},
            headers=_auth(await _user(), settings),
        )
        assert resp.status_code == 404

    async def test_own_clip_is_400(self, client, settings):
        owner = await _user()
        clip = await _clip(owner)
        resp = await client.post(
            f"{CLIPS_URL}/{clip.id}/report", json={"category": "spam"}, headers=_auth(owner, settings)
        )
        assert resp.status_code == 400
        assert await ClipReport.find(ClipReport.clip_id == clip.id).count() == 0

    async def test_own_private_clip_is_400_not_403(self, client, settings):
        owner = await _user()
        clip = await _clip(owner, VisibilityState.PRIVATE)
        resp = await client.post(
            f"{CLIPS_URL}/{clip.id}/report", json={"category": "spam"}, headers=_auth(owner, settings)
        )
        assert resp.status_code == 400

    async def test_whitespace_only_details_store_none(self, client, settings):
        clip = await _clip(await _user())
        resp = await client.post(
            f"{CLIPS_URL}/{clip.id}/report",
            json={"category": "spam", "details": "   "},
            headers=_auth(await _user(), settings),
        )
        assert resp.status_code == 201
        assert (await ClipReport.find_one(ClipReport.clip_id == clip.id)).details is None

    @pytest.mark.parametrize(
        "body",
        [{"category": "rude"}, {}, {"category": "spam", "details": "x" * 1001}],
    )
    async def test_invalid_body_is_422(self, client, settings, body):
        clip = await _clip(await _user())
        resp = await client.post(f"{CLIPS_URL}/{clip.id}/report", json=body, headers=_auth(await _user(), settings))
        assert resp.status_code == 422


@pytest.mark.integration
class TestModerationQueue:
    async def test_admin_sees_reports_newest_first(self, client, settings):
        owner, admin = await _user(), await _user(is_admin=True)
        first, second = await _clip(owner), await _clip(owner)
        reporter = await _user()
        for clip, category in ((first, "spam"), (second, "inappropriate")):
            await client.post(
                f"{CLIPS_URL}/{clip.id}/report",
                json={"category": category, "details": "why"},
                headers=_auth(reporter, settings),
            )

        resp = await client.get(QUEUE_URL, headers=_auth(admin, settings))

        assert resp.status_code == 200, resp.text
        reports = resp.json()["reports"]
        assert [r["clip_id"] for r in reports] == [str(second.id), str(first.id)]
        assert reports[0]["category"] == "inappropriate"
        assert reports[0]["reporter_id"] == str(reporter.id)
        assert reports[0]["details"] == "why"
        assert reports[0]["created_at"]

    async def test_non_admin_is_403(self, client, settings):
        resp = await client.get(QUEUE_URL, headers=_auth(await _user(), settings))
        assert resp.status_code == 403
