"""US-26.2: the backend actually refuses a free account (AC4).

Before this story **no endpoint checked the tier**. The Pro badges in the UI stopped an
honest user and nobody else — a free account that called `POST /clips/{id}/stems` directly
got stems. These tests are the difference between gating and decoration, so each one drives
the real HTTP surface rather than the policy table.
"""

import httpx
import pytest
from beanie import PydanticObjectId

from acemusic.api.auth.tokens import create_access_token
from acemusic.api.main import API_V1_PREFIX, create_app
from acemusic.api.models import Clip, Job, User, VisibilityState
from acemusic.api.services import credits as credits_service, tiers, users as user_service
from acemusic.api.settings import ApiSettings

pytestmark = pytest.mark.integration


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
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings)), base_url="http://testserver"
    ) as ac:
        yield ac


def _auth(user: User, settings: ApiSettings) -> dict[str, str]:
    token = create_access_token(
        user_id=str(user.id),
        email=user.email,
        subscription_tier=user.subscription_tier,
        settings=settings,
    )
    return {"Authorization": f"Bearer {token}"}


async def _user(label: str, tier: str = "free", credits: float = 500.0) -> User:
    email = f"{label}-{PydanticObjectId()}@example.com"
    user = await user_service.get_or_create_user(email=email, provider="google", oauth_id=email, name="T")
    user.subscription_tier = tier
    user.credits_balance = credits
    await user.save()
    return user


async def _wav_clip(user: User) -> Clip:
    workspace_id = PydanticObjectId()
    clip = Clip(
        user_id=user.id,
        workspace_id=workspace_id,
        file_path=f"{user.id}/{workspace_id}/clips/source.wav",
        format="wav",
        duration=30.0,
    )
    await clip.insert()
    return clip


async def _mp3_clip(user: User) -> Clip:
    """A clip stored lossily, so asking for wav/flac is a genuine conversion."""
    workspace_id = PydanticObjectId()
    clip = Clip(
        user_id=user.id,
        workspace_id=workspace_id,
        file_path=f"{user.id}/{workspace_id}/clips/source.mp3",
        format="mp3",
        duration=30.0,
    )
    await clip.insert()
    return clip


def _pro_actions(clip_id: str) -> list[tuple[str, str, dict | None]]:
    """Every Pro-only action, as (label, url, body)."""
    return [
        ("stems", f"{API_V1_PREFIX}/clips/{clip_id}/stems", None),
        ("midi", f"{API_V1_PREFIX}/clips/{clip_id}/midi", None),
        (
            "mastering",
            f"{API_V1_PREFIX}/mastering/jobs",
            {"clip_id": clip_id, "profile": "streaming", "service": "dolby", "format": "wav"},
        ),
        (
            "mastering batch",
            f"{API_V1_PREFIX}/mastering/batch",
            {"clip_ids": [clip_id], "profile": "streaming", "service": "dolby", "format": "wav"},
        ),
        ("studio mixdown", f"{API_V1_PREFIX}/studio/mixdown", {"tracks": []}),
        ("studio daw export", f"{API_V1_PREFIX}/studio/export/daw", {"tracks": []}),
    ]


class TestFreeTierIsRefused:
    async def test_every_pro_action_returns_403(self, client, settings) -> None:
        user = await _user("free")
        clip = await _wav_clip(user)

        for label, url, body in _pro_actions(str(clip.id)):
            resp = await client.post(url, json=body, headers=_auth(user, settings))
            assert resp.status_code == 403, f"{label} was not gated: {resp.status_code} {resp.text}"

    async def test_the_403_says_what_is_locked_and_where_to_go(self, client, settings) -> None:
        # A refusal that does not explain itself is just a wall.
        user = await _user("free-shape")
        clip = await _wav_clip(user)

        resp = await client.post(f"{API_V1_PREFIX}/clips/{clip.id}/stems", headers=_auth(user, settings))

        detail = resp.json()["detail"]
        assert detail["error"] == "upgrade_required"
        assert detail["capability"] == "stems"
        assert detail["feature"] == "Stem separation"
        assert detail["tier"] == "free"
        assert detail["required_tier"] == "pro"
        assert detail["upgrade_url"] == credits_service.UPGRADE_URL
        assert "Pro feature" in detail["message"]

    async def test_a_refused_action_costs_nothing_and_queues_nothing(self, client, settings) -> None:
        # The gate runs before the charge, so being on the wrong plan is never billed.
        user = await _user("free-nocharge", credits=100.0)
        clip = await _wav_clip(user)

        await client.post(f"{API_V1_PREFIX}/clips/{clip.id}/stems", headers=_auth(user, settings))

        assert (await User.get(user.id)).credits_balance == 100.0
        assert await Job.find(Job.user_id == user.id).count() == 0

    async def test_voice_training_is_refused(self, client, settings) -> None:
        user = await _user("free-voice")

        resp = await client.post(
            f"{API_V1_PREFIX}/voice-models/train",
            files=[("files", ("a.wav", b"RIFF", "audio/wav"))],
            data={"name": "My Voice"},
            headers=_auth(user, settings),
        )

        assert resp.status_code == 403, resp.text
        assert resp.json()["detail"]["capability"] == "voice_models"

    async def test_distribution_upload_is_refused(self, client, settings) -> None:
        user = await _user("free-dist")
        clip = await _wav_clip(user)

        resp = await client.post(
            f"{API_V1_PREFIX}/distribution/soundcloud/upload",
            json={"clip_id": str(clip.id)},
            headers=_auth(user, settings),
        )

        assert resp.status_code == 403, resp.text
        assert resp.json()["detail"]["capability"] == "distribution"


class TestProTierIsNotRefused:
    async def test_no_pro_action_returns_403(self, client, settings) -> None:
        # AC3. These may fail for other reasons (unconfigured backends, empty payloads);
        # what must never happen is a tier refusal.
        user = await _user("pro", tier="pro")
        clip = await _wav_clip(user)

        for label, url, body in _pro_actions(str(clip.id)):
            resp = await client.post(url, json=body, headers=_auth(user, settings))
            assert resp.status_code != 403, f"{label} refused a Pro account: {resp.text}"

    async def test_a_pro_account_actually_gets_stems_queued(self, client, settings) -> None:
        user = await _user("pro-stems", tier="pro")
        clip = await _wav_clip(user)

        resp = await client.post(f"{API_V1_PREFIX}/clips/{clip.id}/stems", headers=_auth(user, settings))

        assert resp.status_code == 202, resp.text


class TestTierComesFromTheDatabase:
    async def test_an_upgrade_takes_effect_before_the_token_expires(self, client, settings) -> None:
        # Someone who has just paid should not have to wait out their access token.
        user = await _user("upgraded")
        clip = await _wav_clip(user)
        stale_free_token = _auth(user, settings)

        refused = await client.post(f"{API_V1_PREFIX}/clips/{clip.id}/stems", headers=stale_free_token)
        assert refused.status_code == 403

        user.subscription_tier = "pro"
        await user.save()

        allowed = await client.post(f"{API_V1_PREFIX}/clips/{clip.id}/stems", headers=stale_free_token)
        assert allowed.status_code == 202, "the upgrade did not take effect until the token expired"

    async def test_a_stale_pro_token_does_not_survive_a_downgrade(self, client, settings) -> None:
        # The same rule in the direction that matters for revenue.
        user = await _user("downgraded", tier="pro")
        clip = await _wav_clip(user)
        stale_pro_token = _auth(user, settings)

        user.subscription_tier = "free"
        await user.save()

        resp = await client.post(f"{API_V1_PREFIX}/clips/{clip.id}/stems", headers=stale_pro_token)
        assert resp.status_code == 403, "a Pro token kept Pro access after the downgrade"

    @pytest.mark.parametrize("tier", ["", "PRO", "premium", "pro "])
    async def test_a_tier_that_is_not_exactly_pro_is_refused(self, client, settings, tier) -> None:
        # Fails closed: a typo in the field must not hand out Pro.
        user = await _user("odd-tier", tier=tier)
        clip = await _wav_clip(user)

        resp = await client.post(f"{API_V1_PREFIX}/clips/{clip.id}/stems", headers=_auth(user, settings))

        assert resp.status_code == 403, f"tier {tier!r} was treated as Pro"


class TestReadsStayOpen:
    async def test_a_free_account_can_still_read_its_voice_models(self, client, settings) -> None:
        # Downgrading must not lock someone out of data they already own.
        user = await _user("free-reads")

        resp = await client.get(f"{API_V1_PREFIX}/voice-models", headers=_auth(user, settings))

        assert resp.status_code == 200, resp.text

    async def test_a_free_account_can_still_read_its_credits(self, client, settings) -> None:
        user = await _user("free-balance")

        resp = await client.get(f"{API_V1_PREFIX}/credits/balance", headers=_auth(user, settings))

        assert resp.status_code == 200
        assert resp.json()["tier"] == tiers.FREE


class TestArgumentDependentGates:
    """Gates a router dependency cannot express, because they turn on an argument."""

    async def test_generating_without_a_voice_is_free_tier_work(self, client, settings) -> None:
        user = await _user("free-plain", credits=10.0)

        resp = await client.post(
            f"{API_V1_PREFIX}/generate",
            json={"prompt": "a warm ballad"},
            headers=_auth(user, settings),
        )

        assert resp.status_code != 403, "ordinary generation was gated"

    async def test_generating_with_a_custom_voice_is_refused(self, client, settings) -> None:
        # Same endpoint, same account — only the argument differs.
        user = await _user("free-voice-gen", credits=10.0)

        resp = await client.post(
            f"{API_V1_PREFIX}/generate",
            json={"prompt": "a warm ballad", "voice_model_id": str(PydanticObjectId())},
            headers=_auth(user, settings),
        )

        assert resp.status_code == 403, resp.text
        assert resp.json()["detail"]["capability"] == "voice_models"

    async def test_the_voice_gate_does_not_leak_whether_the_voice_exists(self, client, settings) -> None:
        # The tier is checked before the lookup, so a free account gets the same 403 for a
        # real voice and an imaginary one — otherwise the status code becomes an oracle.
        owner = await _user("voice-owner", tier="pro")
        intruder = await _user("free-prober", credits=10.0)

        from acemusic.api.models import VoiceModel

        real = VoiceModel(user_id=owner.id, name="Theirs", status="ready", weights_path="./x/adapter")
        await real.insert()

        for voice_id in (str(real.id), str(PydanticObjectId())):
            resp = await client.post(
                f"{API_V1_PREFIX}/generate",
                json={"prompt": "x", "voice_model_id": voice_id},
                headers=_auth(intruder, settings),
            )
            assert resp.status_code == 403, f"{voice_id} leaked a different status"

    async def test_a_pro_account_may_generate_with_a_voice(self, client, settings) -> None:
        # The gate must not become a wall for the tier that paid for it. An unknown voice
        # still 404s — that is the US-25.4 rule, reached only once the tier check passes.
        user = await _user("pro-voice-gen", tier="pro", credits=10.0)

        resp = await client.post(
            f"{API_V1_PREFIX}/generate",
            json={"prompt": "x", "voice_model_id": str(PydanticObjectId())},
            headers=_auth(user, settings),
        )

        assert resp.status_code == 404, resp.text


class TestResolutionAndFormatGates:
    """The two capabilities that were declared but not enforced until codex flagged it.

    Both turn on an argument, and both were reachable by calling the API directly while
    only the UI held the line — which is the definition of a gate that is not one.
    """

    async def test_a_free_account_may_render_720p(self, client, settings) -> None:
        # The free tier keeps a working video path; the boundary is the resolution.
        user = await _user("free-720", credits=100.0)
        clip = await _wav_clip(user)

        resp = await client.post(
            f"{API_V1_PREFIX}/videos/generate",
            json={"clip_id": str(clip.id), "resolution": "720p", "prompt": "neon city"},
            headers=_auth(user, settings),
        )

        # 503 here, because no video provider is configured in the test environment.
        # That is the point: the request got *past* the tier gate to the deployment
        # check, which a refusal never would.
        assert resp.status_code == 503, resp.text

    @pytest.mark.parametrize("resolution", ["1080p", "4k"])
    async def test_a_free_account_is_refused_above_720p(self, client, settings, resolution) -> None:
        user = await _user(f"free-{resolution}", credits=100.0)
        clip = await _wav_clip(user)

        resp = await client.post(
            f"{API_V1_PREFIX}/videos/generate",
            json={"clip_id": str(clip.id), "resolution": resolution, "prompt": "neon city"},
            headers=_auth(user, settings),
        )

        assert resp.status_code == 403, resp.text
        assert resp.json()["detail"]["capability"] == "high_res_video"

    async def test_a_refused_resolution_costs_nothing(self, client, settings) -> None:
        # The gate runs before the charge — video is the most expensive action there is.
        user = await _user("free-4k-nocharge", credits=100.0)
        clip = await _wav_clip(user)

        await client.post(
            f"{API_V1_PREFIX}/videos/generate",
            json={"clip_id": str(clip.id), "resolution": "4k", "prompt": "neon city"},
            headers=_auth(user, settings),
        )

        assert (await User.get(user.id)).credits_balance == 100.0

    @pytest.mark.parametrize("resolution", ["720p", "1080p", "4k"])
    async def test_a_pro_account_may_render_any_resolution(self, client, settings, resolution) -> None:
        user = await _user(f"pro-{resolution}", tier="pro", credits=100.0)
        clip = await _wav_clip(user)

        resp = await client.post(
            f"{API_V1_PREFIX}/videos/generate",
            json={"clip_id": str(clip.id), "resolution": resolution, "prompt": "neon city"},
            headers=_auth(user, settings),
        )

        assert resp.status_code != 403, resp.text


class TestLosslessExportGate:
    async def test_a_free_account_may_download_mp3(self, client, settings) -> None:
        user = await _user("free-mp3")
        clip = await _wav_clip(user)

        resp = await client.get(f"{API_V1_PREFIX}/clips/{clip.id}/audio?format=mp3", headers=_auth(user, settings))

        assert resp.status_code != 403, resp.text

    @pytest.mark.parametrize("fmt", ["wav", "flac"])
    async def test_a_free_account_is_refused_a_lossless_conversion(self, client, settings, fmt) -> None:
        # Reachable by calling the API directly until this gate existed — the menu was
        # the only thing holding the line, and a menu is not a gate.
        user = await _user(f"free-{fmt}")
        clip = await _wav_clip(user)
        # Stored as mp3 so the requested format is a genuine conversion.
        clip.format = "mp3"
        clip.file_path = clip.file_path.replace(".wav", ".mp3")
        await clip.save()

        resp = await client.get(f"{API_V1_PREFIX}/clips/{clip.id}/audio?format={fmt}", headers=_auth(user, settings))

        assert resp.status_code == 403, resp.text
        assert resp.json()["detail"]["capability"] == "lossless_export"

    async def test_playing_a_clip_in_its_stored_format_is_never_gated(self, client, settings) -> None:
        # A wav clip streamed as wav is playback, not an export. Gating that would break
        # the free tier's own library.
        user = await _user("free-native")
        clip = await _wav_clip(user)

        resp = await client.get(f"{API_V1_PREFIX}/clips/{clip.id}/audio?format=wav", headers=_auth(user, settings))

        assert resp.status_code != 403, resp.text

    @pytest.mark.parametrize("fmt", ["wav", "flac", "mp3"])
    async def test_a_pro_account_may_request_any_format(self, client, settings, fmt) -> None:
        user = await _user(f"pro-{fmt}", tier="pro")
        clip = await _wav_clip(user)

        resp = await client.get(f"{API_V1_PREFIX}/clips/{clip.id}/audio?format={fmt}", headers=_auth(user, settings))

        assert resp.status_code != 403, resp.text

    async def test_the_stream_endpoint_is_not_a_way_around_the_gate(self, client, settings) -> None:
        # /stream offers the same on-the-fly conversion as /audio. Gating one and not the
        # other makes the refusal a URL away from being undone.
        user = await _user("free-stream")
        clip = await _mp3_clip(user)

        resp = await client.get(f"{API_V1_PREFIX}/clips/{clip.id}/stream?format=wav", headers=_auth(user, settings))

        assert resp.status_code == 403, resp.text
        assert resp.json()["detail"]["capability"] == "lossless_export"

    async def test_signing_out_is_not_a_way_around_the_gate(self, client) -> None:
        # /stream serves public clips anonymously. No account is no plan, so the anonymous
        # path has to refuse too — otherwise logging out beats the gate.
        user = await _user("free-anon-stream")
        clip = await _mp3_clip(user)
        clip.visibility = VisibilityState.PUBLIC
        await clip.save()

        resp = await client.get(f"{API_V1_PREFIX}/clips/{clip.id}/stream?format=wav")

        assert resp.status_code == 403, resp.text
        assert resp.json()["detail"]["capability"] == "lossless_export"

    async def test_streaming_a_clip_in_its_stored_format_is_never_gated(self, client, settings) -> None:
        # Playback, not export — the free tier still plays its own library.
        user = await _user("free-stream-native")
        clip = await _wav_clip(user)

        resp = await client.get(f"{API_V1_PREFIX}/clips/{clip.id}/stream?format=wav", headers=_auth(user, settings))

        assert resp.status_code != 403, resp.text

    async def test_a_pro_account_may_stream_a_lossless_conversion(self, client, settings) -> None:
        user = await _user("pro-stream", tier="pro")
        clip = await _mp3_clip(user)

        resp = await client.get(f"{API_V1_PREFIX}/clips/{clip.id}/stream?format=wav", headers=_auth(user, settings))

        assert resp.status_code != 403, resp.text


class TestBatchIsNotTheCheapWayIn:
    """The batch endpoints do the same Pro work in bulk, so they need the same gates.

    Found by the US-26.2 demo: every single-clip path refused a free account while
    ``POST /batch/stems`` accepted fifty at once.
    """

    async def test_a_free_account_is_refused_batch_stems(self, client, settings) -> None:
        user = await _user("free-batch-stems")
        clip = await _wav_clip(user)

        resp = await client.post(
            f"{API_V1_PREFIX}/batch/stems",
            json={"clip_ids": [str(clip.id)]},
            headers=_auth(user, settings),
        )

        assert resp.status_code == 403, resp.text
        assert resp.json()["detail"]["capability"] == "stems"

    async def test_a_pro_account_may_batch_stems(self, client, settings) -> None:
        user = await _user("pro-batch-stems", tier="pro")
        clip = await _wav_clip(user)

        resp = await client.post(
            f"{API_V1_PREFIX}/batch/stems",
            json={"clip_ids": [str(clip.id)]},
            headers=_auth(user, settings),
        )

        assert resp.status_code != 403, resp.text

    @pytest.mark.parametrize("fmt", ["wav", "wav32", "flac"])
    async def test_a_free_account_is_refused_a_lossless_batch_export(self, client, settings, fmt) -> None:
        # Note the clip here is natively wav, and this still refuses — unlike the
        # single-clip download, batch export has no native-format carve-out. A batch is a
        # set of clips with different formats and one status code, so it cannot say "some
        # of each"; refusing the lossless request over-gates rather than leaks. See the
        # comment on batch_export.
        user = await _user(f"free-batch-{fmt}")
        clip = await _wav_clip(user)

        resp = await client.post(
            f"{API_V1_PREFIX}/batch/export",
            json={"clip_ids": [str(clip.id)], "format": fmt},
            headers=_auth(user, settings),
        )

        assert resp.status_code == 403, resp.text
        assert resp.json()["detail"]["capability"] == "lossless_export"

    async def test_a_free_account_may_batch_export_mp3(self, client, settings) -> None:
        # The free tier is "MP3 download only", not "no batch export".
        user = await _user("free-batch-mp3")
        clip = await _wav_clip(user)

        resp = await client.post(
            f"{API_V1_PREFIX}/batch/export",
            json={"clip_ids": [str(clip.id)], "format": "mp3"},
            headers=_auth(user, settings),
        )

        assert resp.status_code != 403, resp.text

    async def test_a_free_account_is_refused_a_per_clip_daw_export(self, client, settings) -> None:
        # The sibling POST /studio/export/daw was gated; this one builds the same bundle
        # from a single clip and was not.
        user = await _user("free-clip-daw")
        clip = await _wav_clip(user)

        resp = await client.post(f"{API_V1_PREFIX}/clips/{clip.id}/export/daw", headers=_auth(user, settings))

        assert resp.status_code == 403, resp.text
        assert resp.json()["detail"]["capability"] == "studio_editing"

    async def test_a_pro_account_may_run_a_per_clip_daw_export(self, client, settings) -> None:
        user = await _user("pro-clip-daw", tier="pro")
        clip = await _wav_clip(user)

        resp = await client.post(f"{API_V1_PREFIX}/clips/{clip.id}/export/daw", headers=_auth(user, settings))

        assert resp.status_code != 403, resp.text

    async def test_every_lossless_export_format_is_gated(self) -> None:
        # Fails if a format is added to EXPORT_FORMATS and quietly escapes the gate.
        from acemusic.api.routers.batch import LOSSLESS_EXPORT_FORMATS
        from acemusic.audio import EXPORT_FORMATS

        assert set(EXPORT_FORMATS) - LOSSLESS_EXPORT_FORMATS == {"mp3"}
