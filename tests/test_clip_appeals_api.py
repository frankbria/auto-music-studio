"""Appeals of moderation decisions (US-27.4).

A creator appeals the latest removal or content-warning flag on their own clip, once per
decision. Admins work the appeals queue: uphold, reverse (restoring the clip) or ask for more
information. Each outcome records a notice for the creator and a moderation log entry.
"""

import itertools

import httpx
import pytest
from beanie import PydanticObjectId

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.models import Clip, ClipAppeal, ModerationLogEntry, NotificationEvent, VisibilityState, Workspace
from acemusic.api.settings import ApiSettings
from tests.users import make_user

CLIPS_URL = f"{API_V1_PREFIX}/clips"
MY_APPEALS_URL = f"{API_V1_PREFIX}/users/me/appeals"
MODERATION_URL = f"{API_V1_PREFIX}/admin/moderation"
APPEALS_URL = f"{MODERATION_URL}/appeals"

_SEQ = itertools.count(1)


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
    return await make_user(f"appeal-{next(_SEQ)}@example.com", **fields)


async def _clip(owner, **fields) -> Clip:
    workspace = Workspace(name=f"WS-{next(_SEQ)}", user_id=owner.id)
    await workspace.insert()
    clip_id = PydanticObjectId()
    clip = Clip(
        id=clip_id,
        user_id=owner.id,
        workspace_id=workspace.id,
        file_path=f"{owner.id}/{workspace.id}/clips/{clip_id}.wav",
        format="wav",
        title=fields.pop("title", "Appealed"),
        visibility=fields.pop("visibility", VisibilityState.PUBLIC),
        style_tags=["house"],
        **fields,
    )
    await clip.insert()
    return clip


async def _moderate(client, settings, action, clip, reason="Breaks the rules"):
    resp = await client.post(
        f"{MODERATION_URL}/clips",
        json={"action": action, "clip_ids": [str(clip.id)], "reason": reason},
        headers=_auth(await _user(is_admin=True), settings),
    )
    assert resp.status_code == 200 and resp.json()["results"][0]["ok"], resp.text


async def _appeal(client, settings, owner, clip, reason="It's my own original work", **extra):
    return await client.post(
        f"{CLIPS_URL}/{clip.id}/appeal", json={"reason": reason, **extra}, headers=_auth(owner, settings)
    )


async def _appealed(client, settings, action="remove"):
    owner = await _user()
    clip = await _clip(owner)
    await _moderate(client, settings, action, clip)
    resp = await _appeal(client, settings, owner, clip)
    assert resp.status_code == 201, resp.text
    return owner, clip, resp.json()


async def _decide(client, settings, appeal_id, decision, note=None, admin=None):
    body = {"decision": decision} | ({"note": note} if note is not None else {})
    return await client.post(
        f"{APPEALS_URL}/{appeal_id}", json=body, headers=_auth(admin or await _user(is_admin=True), settings)
    )


async def _queue(client, settings, status=None):
    params = {"status": status} if status else {}
    resp = await client.get(APPEALS_URL, params=params, headers=_auth(await _user(is_admin=True), settings))
    assert resp.status_code == 200, resp.text
    return resp.json()["appeals"]


@pytest.mark.integration
class TestSubmitAppeal:
    async def test_appeal_on_a_removed_clip_enters_the_admin_queue(self, client, settings):
        owner = await _user(display_name="Creator")
        clip = await _clip(owner, title="Takedown")
        await _moderate(client, settings, "remove", clip, reason="Copyrighted sample")

        resp = await _appeal(client, settings, owner, clip, reason="  I cleared the sample  ", context="License #42")

        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["status"] == "pending"
        assert body["clip_id"] == str(clip.id)
        assert body["action"] == "remove"
        assert body["reason"] == "I cleared the sample"
        [item] = await _queue(client, settings)
        assert item["id"] == body["id"]
        assert item["clip_title"] == "Takedown"
        assert item["creator_name"] == "Creator"
        assert item["action"] == "remove"
        assert item["action_reason"] == "Copyrighted sample"
        assert item["context"] == "License #42"

    async def test_a_content_warning_flag_is_appealable(self, client, settings):
        _, _, appeal = await _appealed(client, settings, action="flag")
        assert appeal["action"] == "flag"

    async def test_clip_without_a_moderation_decision_cannot_be_appealed(self, client, settings):
        owner = await _user()
        clip = await _clip(owner)

        resp = await _appeal(client, settings, owner, clip)

        assert resp.status_code == 400
        assert resp.json()["detail"] == "This clip has no moderation decision to appeal."

    async def test_approved_clip_cannot_be_appealed(self, client, settings):
        owner = await _user()
        clip = await _clip(owner)
        await _moderate(client, settings, "approve", clip)

        assert (await _appeal(client, settings, owner, clip)).status_code == 400

    async def test_only_the_owner_can_appeal(self, client, settings):
        clip = await _clip(await _user())
        await _moderate(client, settings, "remove", clip)

        resp = await _appeal(client, settings, await _user(), clip)

        assert resp.status_code == 404
        assert await ClipAppeal.find_all().count() == 0

    async def test_repeat_appeal_on_the_same_decision_is_409(self, client, settings):
        owner, clip, _ = await _appealed(client, settings)

        resp = await _appeal(client, settings, owner, clip, reason="Please look again")

        assert resp.status_code == 409
        assert resp.json()["detail"] == "You have already appealed this decision."
        assert await ClipAppeal.find_all().count() == 1

    async def test_repeat_appeal_after_an_upheld_decision_is_still_409(self, client, settings):
        owner, clip, appeal = await _appealed(client, settings)
        assert (await _decide(client, settings, appeal["id"], "uphold")).status_code == 200

        assert (await _appeal(client, settings, owner, clip)).status_code == 409

    async def test_a_new_removal_is_a_new_decision_and_can_be_appealed(self, client, settings):
        owner, clip, appeal = await _appealed(client, settings)
        assert (await _decide(client, settings, appeal["id"], "reverse")).status_code == 200
        await _moderate(client, settings, "remove", clip, reason="Again")

        assert (await _appeal(client, settings, owner, clip)).status_code == 201

    @pytest.mark.parametrize("reason", ["", "   ", "x" * 2001])
    async def test_reason_is_required_and_bounded(self, client, settings, reason):
        owner = await _user()
        clip = await _clip(owner)
        await _moderate(client, settings, "remove", clip)

        assert (await _appeal(client, settings, owner, clip, reason=reason)).status_code == 422

    async def test_the_library_shows_which_clips_moderation_removed(self, client, settings):
        owner = await _user()
        removed = await _clip(owner, title="Gone")
        await _clip(owner, title="Kept")
        await _moderate(client, settings, "remove", removed)

        resp = await client.get(CLIPS_URL, headers=_auth(owner, settings))

        by_title = {c["title"]: c for c in resp.json()["clips"]}
        assert by_title["Gone"]["removed_at"] is not None
        assert by_title["Kept"]["removed_at"] is None

    async def test_my_appeals_lists_only_the_callers_appeals(self, client, settings):
        owner, clip, appeal = await _appealed(client, settings)
        await _appealed(client, settings)

        resp = await client.get(MY_APPEALS_URL, headers=_auth(owner, settings))

        assert resp.status_code == 200
        [mine] = resp.json()["appeals"]
        assert mine["id"] == appeal["id"]
        assert mine["clip_id"] == str(clip.id)


@pytest.mark.integration
class TestDecideAppeal:
    async def test_reverse_restores_a_removed_clip_and_notifies_the_creator(self, client, settings):
        owner, clip, appeal = await _appealed(client, settings)

        resp = await _decide(client, settings, appeal["id"], "reverse", note="Sample was licensed")

        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "reversed"
        restored = await Clip.get(clip.id)
        assert restored.removed_at is None
        assert restored.visibility == VisibilityState.PRIVATE
        # The owner can publish it again: the removal no longer blocks the PATCH.
        republish = await client.patch(
            f"{CLIPS_URL}/{clip.id}", json={"visibility": "public"}, headers=_auth(owner, settings)
        )
        assert republish.status_code == 200, republish.text
        notice = await NotificationEvent.find_one({"user_id": owner.id, "event_type": "moderation_appeal_reversed"})
        assert notice is not None
        assert notice.clip_id == clip.id
        assert notice.payload["note"] == "Sample was licensed"
        assert notice.payload["appeal_id"] == appeal["id"]

    async def test_reverse_clears_a_content_warning(self, client, settings):
        _, clip, appeal = await _appealed(client, settings, action="flag")

        assert (await _decide(client, settings, appeal["id"], "reverse")).status_code == 200

        assert (await Clip.get(clip.id)).content_warning is False

    async def test_uphold_keeps_the_clip_down_and_notifies_the_creator(self, client, settings):
        owner, clip, appeal = await _appealed(client, settings)

        resp = await _decide(client, settings, appeal["id"], "uphold", note="Still infringing")

        assert resp.status_code == 200
        assert resp.json()["status"] == "upheld"
        assert (await Clip.get(clip.id)).removed_at is not None
        notice = await NotificationEvent.find_one({"user_id": owner.id, "event_type": "moderation_appeal_upheld"})
        assert notice.payload["note"] == "Still infringing"

    async def test_a_decided_appeal_cannot_be_decided_again(self, client, settings):
        _, clip, appeal = await _appealed(client, settings)
        assert (await _decide(client, settings, appeal["id"], "uphold")).status_code == 200

        resp = await _decide(client, settings, appeal["id"], "reverse")

        assert resp.status_code == 409
        assert (await Clip.get(clip.id)).removed_at is not None

    async def test_decision_is_logged(self, client, settings):
        admin = await _user(is_admin=True)
        _, clip, appeal = await _appealed(client, settings)

        await _decide(client, settings, appeal["id"], "reverse", note="Fine", admin=admin)

        entry = await ModerationLogEntry.find_one({"action": "appeal_reversed"})
        assert entry.actor_id == admin.id
        assert entry.target_type == "clip"
        assert entry.target_id == str(clip.id)
        assert entry.reason == "Fine"
        assert entry.details == {"appeal_id": appeal["id"], "appealed_action": "remove"}

    async def test_decided_appeals_leave_the_open_queue(self, client, settings):
        _, _, decided = await _appealed(client, settings)
        _, _, still_open = await _appealed(client, settings)
        await _decide(client, settings, decided["id"], "uphold")

        assert [a["id"] for a in await _queue(client, settings)] == [still_open["id"]]
        assert {a["id"] for a in await _queue(client, settings, status="all")} == {decided["id"], still_open["id"]}

    async def test_unknown_appeal_is_404(self, client, settings):
        assert (await _decide(client, settings, str(PydanticObjectId()), "uphold")).status_code == 404
        assert (await _decide(client, settings, "not-an-id", "uphold")).status_code == 404


@pytest.mark.integration
class TestRequestMoreInformation:
    async def test_request_info_notifies_and_the_creator_can_answer(self, client, settings):
        owner, clip, appeal = await _appealed(client, settings)

        resp = await _decide(client, settings, appeal["id"], "request_info", note="Send the license")

        assert resp.status_code == 200
        assert resp.json()["status"] == "info_requested"
        notice = await NotificationEvent.find_one(
            {"user_id": owner.id, "event_type": "moderation_appeal_info_requested"}
        )
        assert notice.payload["note"] == "Send the license"
        [still_open] = await _queue(client, settings)
        assert still_open["status"] == "info_requested"

        answer = await client.patch(
            f"{CLIPS_URL}/{clip.id}/appeal", json={"context": "License attached"}, headers=_auth(owner, settings)
        )

        assert answer.status_code == 200, answer.text
        assert answer.json()["status"] == "pending"
        assert answer.json()["context"] == "License attached"

    async def test_answering_without_a_request_is_409(self, client, settings):
        owner, clip, _ = await _appealed(client, settings)

        resp = await client.patch(
            f"{CLIPS_URL}/{clip.id}/appeal", json={"context": "More"}, headers=_auth(owner, settings)
        )

        assert resp.status_code == 409

    async def test_info_request_still_allows_a_final_decision(self, client, settings):
        _, _, appeal = await _appealed(client, settings)
        await _decide(client, settings, appeal["id"], "request_info", note="?")

        assert (await _decide(client, settings, appeal["id"], "reverse")).json()["status"] == "reversed"


@pytest.mark.integration
class TestAdminGate:
    async def test_non_admin_cannot_list_or_decide(self, client, settings):
        _, _, appeal = await _appealed(client, settings)
        headers = _auth(await _user(), settings)

        assert (await client.get(APPEALS_URL, headers=headers)).status_code == 403
        resp = await client.post(f"{APPEALS_URL}/{appeal['id']}", json={"decision": "reverse"}, headers=headers)
        assert resp.status_code == 403
