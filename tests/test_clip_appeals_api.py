"""Appeals of moderation decisions (US-27.4).

A creator appeals the latest removal or content-warning flag on their own clip, once per
decision. Admins work the appeals queue: uphold, reverse (restoring the clip) or ask for more
information. Each outcome records a notice for the creator and a moderation log entry.
"""

import itertools
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

import httpx
import pytest
from beanie import PydanticObjectId

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.models import (
    Clip,
    ClipAppeal,
    ModerationLogEntry,
    NotificationEvent,
    Release,
    SoundCloudUnshare,
    User,
    VisibilityState,
    Workspace,
)
from acemusic.api.services import releases as release_service, soundcloud
from acemusic.api.settings import ApiSettings
from tests.test_moderation_dashboard_api import _release, _sc_connection
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


def _naive(iso: str) -> datetime:
    return datetime.fromisoformat(iso).replace(tzinfo=None)


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

    async def test_a_new_flag_is_stamped_so_the_library_can_tell_it_from_the_appealed_one(self, client, settings):
        owner, clip, appeal = await _appealed(client, settings, action="flag")
        assert (await _decide(client, settings, appeal["id"], "uphold")).status_code == 200
        await _moderate(client, settings, "flag", clip, reason="Flagged again")

        resp = await client.get(f"{CLIPS_URL}/{clip.id}", headers=_auth(owner, settings))

        flagged_at = _naive(resp.json()["flagged_at"])
        assert flagged_at > _naive(appeal["created_at"])
        assert (await _appeal(client, settings, owner, clip)).status_code == 201

    async def test_an_unflagged_clip_has_no_flag_stamp(self, client, settings):
        owner = await _user()
        clip = await _clip(owner)

        resp = await client.get(f"{CLIPS_URL}/{clip.id}", headers=_auth(owner, settings))

        assert resp.json()["flagged_at"] is None

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
        # The removal recorded the clip's visibility, so the reversal puts it back where it was.
        assert restored.visibility == VisibilityState.PUBLIC
        assert restored.is_public is True
        notice = await NotificationEvent.find_one({"user_id": owner.id, "event_type": "moderation_appeal_reversed"})
        assert notice is not None
        assert notice.clip_id == clip.id
        assert notice.payload["note"] == "Sample was licensed"
        assert notice.payload["appeal_id"] == appeal["id"]

    async def test_reverse_of_a_removal_that_predates_the_snapshot_leaves_the_clip_private(self, client, settings):
        owner, clip, appeal = await _appealed(client, settings)
        await ModerationLogEntry.find({"target_id": str(clip.id)}).update({"$set": {"details": {}}})

        assert (await _decide(client, settings, appeal["id"], "reverse")).status_code == 200

        restored = await Clip.get(clip.id)
        assert restored.removed_at is None
        assert restored.visibility == VisibilityState.PRIVATE
        republish = await client.patch(
            f"{CLIPS_URL}/{clip.id}", json={"visibility": "public"}, headers=_auth(owner, settings)
        )
        assert republish.status_code == 200, republish.text

    async def test_a_superseded_decision_cannot_be_reversed(self, client, settings):
        owner, clip, appeal = await _appealed(client, settings, action="flag")
        await _moderate(client, settings, "remove", clip, reason="Removed after review")

        resp = await _decide(client, settings, appeal["id"], "reverse")

        assert resp.status_code == 409
        assert resp.json()["detail"] == "A newer moderation decision has replaced the one appealed."
        restored = await Clip.get(clip.id)
        assert restored.content_warning is True and restored.removed_at is not None
        assert (await ClipAppeal.get(appeal["id"])).status == "pending"
        assert (
            await NotificationEvent.find_one({"user_id": owner.id, "event_type": "moderation_appeal_reversed"}) is None
        )
        # It can still be closed without touching the newer decision.
        assert (await _decide(client, settings, appeal["id"], "uphold")).status_code == 200

    async def test_the_queue_marks_an_appeal_a_newer_decision_replaced(self, client, settings):
        _, clip, stale = await _appealed(client, settings)
        _, _, live = await _appealed(client, settings)
        await _moderate(client, settings, "remove", clip, reason="Removed again")

        by_id = {item["id"]: item for item in await _queue(client, settings)}

        assert by_id[stale["id"]]["superseded"] is True
        assert by_id[live["id"]]["superseded"] is False

    async def test_a_flag_back_in_force_after_a_reversed_removal_is_not_superseded(self, client, settings):
        owner, clip, flag_appeal = await _appealed(client, settings, action="flag")
        await _moderate(client, settings, "remove", clip)
        removal = (await _appeal(client, settings, owner, clip)).json()
        assert (await _decide(client, settings, removal["id"], "reverse")).status_code == 200

        [item] = await _queue(client, settings)

        assert item["id"] == flag_appeal["id"]
        assert item["superseded"] is False

    async def test_an_appeal_on_a_deleted_clip_is_not_marked_superseded(self, client, settings):
        _, clip, appeal = await _appealed(client, settings)
        await clip.delete()

        [item] = await _queue(client, settings)

        assert item["id"] == appeal["id"]
        assert item["clip_deleted"] is True and item["superseded"] is False

    async def test_more_information_cannot_be_requested_on_a_superseded_decision(self, client, settings):
        owner, clip, appeal = await _appealed(client, settings)
        await _moderate(client, settings, "remove", clip, reason="Removed again")

        resp = await _decide(client, settings, appeal["id"], "request_info", note="Which license?")

        assert resp.status_code == 409
        assert resp.json()["detail"] == "A newer moderation decision has replaced the one appealed."
        assert (await ClipAppeal.get(appeal["id"])).status == "pending"
        assert (
            await NotificationEvent.find_one({"user_id": owner.id, "event_type": "moderation_appeal_info_requested"})
            is None
        )

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
    async def test_request_info_needs_a_note(self, client, settings):
        _, _, appeal = await _appealed(client, settings)

        resp = await _decide(client, settings, appeal["id"], "request_info")

        assert resp.status_code == 422
        assert (await ClipAppeal.get(appeal["id"])).status == "pending"

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

    async def test_answer_keeps_the_original_context(self, client, settings):
        owner = await _user()
        clip = await _clip(owner)
        await _moderate(client, settings, "remove", clip)
        appeal = (await _appeal(client, settings, owner, clip, context="Original note")).json()
        await _decide(client, settings, appeal["id"], "request_info", note="More?")

        answer = await client.patch(
            f"{CLIPS_URL}/{clip.id}/appeal", json={"context": "Follow-up"}, headers=_auth(owner, settings)
        )

        assert answer.json()["context"] == "Original note\n\nFollow-up"

    async def test_a_blank_answer_is_422(self, client, settings):
        owner, clip, appeal = await _appealed(client, settings)
        await _decide(client, settings, appeal["id"], "request_info", note="?")

        resp = await client.patch(
            f"{CLIPS_URL}/{clip.id}/appeal", json={"context": "   "}, headers=_auth(owner, settings)
        )

        assert resp.status_code == 422

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


@pytest.mark.integration
class TestPagination:
    async def test_the_open_queue_pages_oldest_first_and_survives_a_decision_between_pages(self, client, settings):
        ids = [(await _appealed(client, settings))[2]["id"] for _ in range(3)]
        admin = _auth(await _user(is_admin=True), settings)

        first = (await client.get(APPEALS_URL, params={"limit": 2}, headers=admin)).json()
        await _decide(client, settings, ids[0], "uphold")
        second = await client.get(APPEALS_URL, params={"limit": 2, "cursor": first["next_cursor"]}, headers=admin)

        assert [a["id"] for a in first["appeals"]] == ids[:2]
        assert [a["id"] for a in second.json()["appeals"]] == ids[2:]
        assert second.json()["next_cursor"] is None

    async def test_all_appeals_page_newest_first(self, client, settings):
        ids = [(await _appealed(client, settings))[2]["id"] for _ in range(3)]
        admin = _auth(await _user(is_admin=True), settings)

        first = (await client.get(APPEALS_URL, params={"status": "all", "limit": 2}, headers=admin)).json()
        params = {"status": "all", "limit": 2, "cursor": first["next_cursor"]}
        second = (await client.get(APPEALS_URL, params=params, headers=admin)).json()

        assert [a["id"] for a in first["appeals"] + second["appeals"]] == ids[::-1]
        assert second["next_cursor"] is None

    async def test_my_appeals_page_newest_first(self, client, settings):
        owner = await _user()
        ids = []
        for _ in range(3):
            clip = await _clip(owner)
            await _moderate(client, settings, "remove", clip)
            ids.append((await _appeal(client, settings, owner, clip)).json()["id"])
        headers = _auth(owner, settings)

        first = (await client.get(MY_APPEALS_URL, params={"limit": 2}, headers=headers)).json()
        second = await client.get(MY_APPEALS_URL, params={"limit": 2, "cursor": first["next_cursor"]}, headers=headers)

        assert [a["id"] for a in first["appeals"] + second.json()["appeals"]] == ids[::-1]
        assert second.json()["next_cursor"] is None

    @pytest.mark.parametrize("url", [APPEALS_URL, MY_APPEALS_URL])
    @pytest.mark.parametrize("params", [{"cursor": "not-a-cursor"}, {"limit": 0}, {"limit": 501}])
    async def test_a_bad_cursor_or_limit_is_422(self, client, settings, url, params):
        resp = await client.get(url, params=params, headers=_auth(await _user(is_admin=True), settings))

        assert resp.status_code == 422

    async def test_an_open_queue_cursor_is_rejected_by_the_all_view(self, client, settings):
        for _ in range(2):
            await _appealed(client, settings)
        admin = _auth(await _user(is_admin=True), settings)
        cursor = (await client.get(APPEALS_URL, params={"limit": 1}, headers=admin)).json()["next_cursor"]

        resp = await client.get(APPEALS_URL, params={"status": "all", "cursor": cursor}, headers=admin)

        assert resp.status_code == 422


class _SoundCloudStandIn:
    """A real HTTP server in place of api.soundcloud.com's ``PUT /tracks/{id}``: records each call, answers ``status``."""

    def __init__(self) -> None:
        self.puts: list[tuple[str, str]] = []
        self.status = 200
        stand_in = self

        class Handler(BaseHTTPRequestHandler):
            def do_PUT(self) -> None:
                body = parse_qs(self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode())
                stand_in.puts.append((self.path.rsplit("/", 1)[-1], body["track[sharing]"][0]))
                self.send_response(stand_in.status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *_args) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


@pytest.fixture
def soundcloud_stand_in(monkeypatch):
    stand_in = _SoundCloudStandIn()
    monkeypatch.setattr(soundcloud, "SOUNDCLOUD_UPLOAD_URL", f"http://127.0.0.1:{stand_in.server.server_port}/tracks")
    yield stand_in
    stand_in.server.shutdown()


async def _removed_with_releases(client, settings):
    """A public clip with a public, an unlisted and a private release (the first two on SoundCloud), then removed."""
    owner = await _user()
    await _sc_connection(owner)
    clip = await _clip(owner)
    public = await _release(clip, visibility=VisibilityState.PUBLIC, soundcloud_track_id="t-public")
    unlisted = await _release(clip, visibility=VisibilityState.UNLISTED, soundcloud_track_id="t-unlisted")
    private = await _release(clip, visibility=VisibilityState.PRIVATE)
    await _moderate(client, settings, "remove", clip)
    resp = await _appeal(client, settings, owner, clip)
    assert resp.status_code == 201, resp.text
    return clip, (public, unlisted, private), resp.json()


async def _visibilities(releases) -> list[str]:
    return [(await Release.get(r.id)).visibility.value for r in releases]


@pytest.mark.integration
class TestReversalRestoresReleases:
    async def test_reverse_restores_release_visibility_and_reshares_the_public_track(
        self, client, settings, soundcloud_stand_in
    ):
        clip, releases, appeal = await _removed_with_releases(client, settings)
        assert await _visibilities(releases) == ["private", "private", "private"]
        assert await SoundCloudUnshare.find({"clip_id": clip.id}).count() == 2

        assert (await _decide(client, settings, appeal["id"], "reverse")).status_code == 200

        assert await _visibilities(releases) == ["public", "unlisted", "private"]
        # The poller must not make the track private again after the reversal.
        assert await SoundCloudUnshare.find({"clip_id": clip.id}).count() == 0
        # SoundCloud has only public/private: the unlisted release's track stays private.
        assert soundcloud_stand_in.puts == [("t-public", "public")]
        entry = await ModerationLogEntry.find_one(ModerationLogEntry.action == "appeal_reversed")
        assert entry.details["releases_restored"] == 2
        assert "soundcloud_reshare_failed" not in entry.details

    async def test_a_failed_reshare_is_recorded_and_the_release_still_restored(
        self, client, settings, soundcloud_stand_in
    ):
        soundcloud_stand_in.status = 500
        _clip_, releases, appeal = await _removed_with_releases(client, settings)

        assert (await _decide(client, settings, appeal["id"], "reverse")).status_code == 200

        assert await _visibilities(releases) == ["public", "unlisted", "private"]
        entry = await ModerationLogEntry.find_one(ModerationLogEntry.action == "appeal_reversed")
        assert entry.details["soundcloud_reshare_failed"] == ["t-public"]

    async def test_releases_of_a_removal_logged_before_the_snapshot_stay_private(
        self, client, settings, soundcloud_stand_in
    ):
        clip, releases, appeal = await _removed_with_releases(client, settings)
        await ModerationLogEntry.find({"target_id": str(clip.id), "action": "remove"}).update(
            {"$unset": {"details.previous_release_visibility": ""}}
        )

        assert (await _decide(client, settings, appeal["id"], "reverse")).status_code == 200

        assert await _visibilities(releases) == ["private", "private", "private"]
        assert soundcloud_stand_in.puts == []

    async def test_a_release_the_owner_changed_since_the_removal_is_left_alone(
        self, client, settings, soundcloud_stand_in
    ):
        clip, (public, unlisted, private), appeal = await _removed_with_releases(client, settings)
        await Release.find_one(Release.id == unlisted.id).update({"$set": {"title": "Renamed"}})
        await Release.find_one(Release.id == public.id).update({"$set": {"visibility": "unlisted"}})

        assert (await _decide(client, settings, appeal["id"], "reverse")).status_code == 200

        # Only a release still private (as the removal left it) is put back.
        assert await _visibilities((public, unlisted, private)) == ["unlisted", "unlisted", "private"]
        assert soundcloud_stand_in.puts == []

    async def test_an_unexpected_reshare_error_is_recorded_not_raised(self, client, settings, monkeypatch):
        clip, releases, appeal = await _removed_with_releases(client, settings)

        async def broken(*_args):
            raise RuntimeError("connection pool exhausted")

        # The appeal is marked reversed before the re-share, so an error escaping here could never be retried.
        monkeypatch.setattr(soundcloud, "get_valid_connection", broken)

        assert (await _decide(client, settings, appeal["id"], "reverse")).status_code == 200

        assert await _visibilities(releases) == ["public", "unlisted", "private"]
        entry = await ModerationLogEntry.find_one(ModerationLogEntry.action == "appeal_reversed")
        assert entry.details["soundcloud_reshare_failed"] == ["t-public"]

    async def test_a_banned_owners_releases_and_tracks_stay_down(self, client, settings, soundcloud_stand_in):
        clip, releases, appeal = await _removed_with_releases(client, settings)
        await User.find_one(User.id == clip.user_id).update({"$set": {"banned_at": datetime.now(timezone.utc)}})

        assert (await _decide(client, settings, appeal["id"], "reverse")).status_code == 200

        assert await _visibilities(releases) == ["private", "private", "private"]
        assert await SoundCloudUnshare.find({"clip_id": clip.id}).count() == 2
        assert soundcloud_stand_in.puts == []
        entry = await ModerationLogEntry.find_one(ModerationLogEntry.action == "appeal_reversed")
        assert entry.details["releases_restore_skipped"] == "owner banned"

    async def test_a_cover_dropped_since_the_removal_keeps_the_tracks_down(self, client, settings, soundcloud_stand_in):
        clip, releases, appeal = await _removed_with_releases(client, settings)
        await ModerationLogEntry(
            actor_id=None,
            action="drop",
            target_type="artwork",
            target_id=str(PydanticObjectId()),
            details={"clip_id": str(clip.id), "was_cover": True},
        ).insert()

        assert (await _decide(client, settings, appeal["id"], "reverse")).status_code == 200

        assert await _visibilities(releases) == ["private", "private", "private"]
        assert await SoundCloudUnshare.find({"clip_id": clip.id}).count() == 2
        assert soundcloud_stand_in.puts == []
        entry = await ModerationLogEntry.find_one(ModerationLogEntry.action == "appeal_reversed")
        assert entry.details["releases_restore_skipped"] == "cover dropped since the removal"

    async def test_a_removal_landing_mid_reversal_takes_the_reshared_track_down_again(
        self, client, settings, soundcloud_stand_in, monkeypatch
    ):
        clip, _releases, appeal = await _removed_with_releases(client, settings)
        real_update = soundcloud.update_track_sharing

        async def share_then_removed(token, track_id, sharing):
            result = await real_update(token, track_id, sharing)
            now = datetime.now(timezone.utc)
            await Clip.find_one(Clip.id == clip.id).update({"$set": {"removed_at": now, "moderation_reviewed_at": now}})
            return result

        monkeypatch.setattr(soundcloud, "update_track_sharing", share_then_removed)

        assert (await _decide(client, settings, appeal["id"], "reverse")).status_code == 200

        assert soundcloud_stand_in.puts == [("t-public", "public")]
        queued = await SoundCloudUnshare.find({"clip_id": clip.id}).to_list()
        assert {row.track_id for row in queued} == {"t-public", "t-unlisted"}

    async def test_a_release_restore_error_is_recorded_not_raised(self, client, settings, monkeypatch):
        clip, releases, appeal = await _removed_with_releases(client, settings)

        async def broken(*_args):
            raise RuntimeError("Mongo went away")

        monkeypatch.setattr(release_service, "restore_releases", broken)

        resp = await _decide(client, settings, appeal["id"], "reverse")

        assert resp.status_code == 200
        assert (await Clip.get(clip.id)).removed_at is None
        entry = await ModerationLogEntry.find_one(ModerationLogEntry.action == "appeal_reversed")
        assert entry.details["releases_restore_failed"] is True
