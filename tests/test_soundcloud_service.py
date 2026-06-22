"""Unit tests for the SoundCloud distribution service (US-13.2).

Pure helpers (PKCE, state) run with no I/O; the OAuth/upload HTTP calls are
mocked with ``respx`` (the same library the login OAuth tests use). The
DB-backed ``get_valid_connection`` is exercised end-to-end in
``tests/test_distribution_api.py``.
"""

import base64
import hashlib

import httpx
import pytest
import respx

from acemusic.api.services import soundcloud as sc
from acemusic.api.settings import ApiSettings


def _settings(**overrides) -> ApiSettings:
    base = {
        "jwt_secret_key": "test-secret-key-at-least-32-bytes-long-xx",
        "soundcloud_client_id": "sc-id",
        "soundcloud_client_secret": "sc-secret",
        "soundcloud_redirect_uri": "https://app.test/distribution/soundcloud/callback",
    }
    base.update(overrides)
    return ApiSettings(_env_file=None, **base)


class TestPkce:
    def test_pair_is_base64url_and_challenge_matches_verifier(self) -> None:
        verifier, challenge = sc.generate_pkce_pair()
        # base64url, no padding
        assert "=" not in verifier and "=" not in challenge
        assert "+" not in verifier and "/" not in verifier
        expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        assert challenge == expected

    def test_pairs_are_unique(self) -> None:
        assert sc.generate_pkce_pair()[0] != sc.generate_pkce_pair()[0]


class TestBuildConnectRequest:
    def test_url_carries_pkce_and_state(self) -> None:
        settings = _settings()
        link = sc.build_connect_request("user-1", settings)
        assert link.url.startswith(sc.SOUNDCLOUD_AUTHORIZE_URL + "?")
        assert "code_challenge_method=S256" in link.url
        assert "response_type=code" in link.url
        # The raw nonce/verifier are returned for cookies, never placed in the URL.
        assert link.state_nonce not in link.url
        assert link.code_verifier not in link.url
        assert link.nonce_cookie_name.startswith(sc.NONCE_COOKIE_PREFIX)
        assert link.verifier_cookie_name.startswith(sc.VERIFIER_COOKIE_PREFIX)

    def test_unconfigured_raises(self) -> None:
        settings = _settings(soundcloud_client_id=None)
        with pytest.raises(sc.SoundCloudNotConfiguredError):
            sc.build_connect_request("user-1", settings)


class TestStateRoundTrip:
    def test_valid_state_returns_verifier(self) -> None:
        settings = _settings()
        link = sc.build_connect_request("user-1", settings)
        cookies = {link.nonce_cookie_name: link.state_nonce, link.verifier_cookie_name: link.code_verifier}
        state = link.url.split("state=", 1)[1].split("&", 1)[0]
        # urlencode percent-encodes nothing JWT-relevant here, but decode to be safe.
        from urllib.parse import unquote

        validated = sc.validate_link_state(unquote(state), "user-1", settings, cookies)
        assert validated.code_verifier == link.code_verifier

    def test_wrong_user_rejected(self) -> None:
        settings = _settings()
        link = sc.build_connect_request("user-1", settings)
        cookies = {link.nonce_cookie_name: link.state_nonce, link.verifier_cookie_name: link.code_verifier}
        from urllib.parse import unquote

        state = unquote(link.url.split("state=", 1)[1].split("&", 1)[0])
        with pytest.raises(sc.SoundCloudError):
            sc.validate_link_state(state, "user-2", settings, cookies)

    def test_missing_nonce_cookie_rejected(self) -> None:
        settings = _settings()
        link = sc.build_connect_request("user-1", settings)
        from urllib.parse import unquote

        state = unquote(link.url.split("state=", 1)[1].split("&", 1)[0])
        cookies = {link.verifier_cookie_name: link.code_verifier}  # nonce missing
        with pytest.raises(sc.SoundCloudError):
            sc.validate_link_state(state, "user-1", settings, cookies)

    def test_tampered_nonce_rejected(self) -> None:
        settings = _settings()
        link = sc.build_connect_request("user-1", settings)
        from urllib.parse import unquote

        state = unquote(link.url.split("state=", 1)[1].split("&", 1)[0])
        cookies = {link.nonce_cookie_name: "not-the-nonce", link.verifier_cookie_name: link.code_verifier}
        with pytest.raises(sc.SoundCloudError):
            sc.validate_link_state(state, "user-1", settings, cookies)


@respx.mock
async def test_exchange_code_posts_pkce_params() -> None:
    settings = _settings()
    route = respx.post(sc.SOUNDCLOUD_TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "at", "refresh_token": "rt", "expires_in": 3600})
    )
    tokens = await sc.exchange_code("the-code", "the-verifier", settings)
    assert tokens["access_token"] == "at"
    sent = route.calls.last.request
    body = sent.content.decode()
    assert "grant_type=authorization_code" in body
    assert "code_verifier=the-verifier" in body
    assert "code=the-code" in body


@respx.mock
async def test_refresh_access_token_uses_refresh_grant() -> None:
    settings = _settings()
    route = respx.post(sc.SOUNDCLOUD_TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "at2", "refresh_token": "rt2", "expires_in": 3600})
    )
    tokens = await sc.refresh_access_token("old-refresh", settings)
    assert tokens["access_token"] == "at2"
    body = route.calls.last.request.content.decode()
    assert "grant_type=refresh_token" in body
    assert "refresh_token=old-refresh" in body


@respx.mock
async def test_rejected_grant_raises_auth_error() -> None:
    settings = _settings()
    respx.post(sc.SOUNDCLOUD_TOKEN_URL).mock(return_value=httpx.Response(400, json={"error": "invalid_grant"}))
    with pytest.raises(sc.SoundCloudAuthError):
        await sc.refresh_access_token("revoked", settings)


@respx.mock
async def test_transient_token_failure_is_not_auth_error() -> None:
    settings = _settings()
    respx.post(sc.SOUNDCLOUD_TOKEN_URL).mock(return_value=httpx.Response(503))
    with pytest.raises(sc.SoundCloudError) as excinfo:
        await sc.refresh_access_token("good", settings)
    # A 5xx is retryable: it must NOT be the auth subclass that deletes the link.
    assert not isinstance(excinfo.value, sc.SoundCloudAuthError)


@respx.mock
async def test_get_soundcloud_user_uses_oauth_header() -> None:
    route = respx.get(sc.SOUNDCLOUD_ME_URL).mock(return_value=httpx.Response(200, json={"id": 42, "username": "dj"}))
    profile = await sc.get_soundcloud_user("tok")
    assert profile["username"] == "dj"
    assert route.calls.last.request.headers["Authorization"] == "OAuth tok"


@respx.mock
async def test_upload_track_sends_multipart_metadata_and_audio() -> None:
    route = respx.post(sc.SOUNDCLOUD_UPLOAD_URL).mock(
        return_value=httpx.Response(201, json={"id": 999, "permalink_url": "https://snd.sc/x"})
    )
    metadata = {"title": "My Song", "genre": "house", "bpm": 128, "key_signature": "Am", "sharing": "public"}
    track = await sc.upload_track("tok", b"RIFFxxxx", "song.wav", metadata, artwork=b"\x89PNGdata")
    assert track["id"] == 999
    request = route.calls.last.request
    assert request.headers["Authorization"] == "OAuth tok"
    body = request.content  # multipart body bytes
    assert b'name="track[title]"' in body and b"My Song" in body
    assert b'name="track[genre]"' in body and b"house" in body
    assert b'name="track[bpm]"' in body and b"128" in body
    assert b'name="track[key_signature]"' in body and b"Am" in body
    assert b'name="track[sharing]"' in body and b"public" in body
    assert b'name="track[asset_data]"' in body and b"RIFFxxxx" in body
    assert b'name="track[artwork_data]"' in body and b"PNGdata" in body


@respx.mock
async def test_upload_track_omits_absent_optional_fields() -> None:
    route = respx.post(sc.SOUNDCLOUD_UPLOAD_URL).mock(return_value=httpx.Response(201, json={"id": 1}))
    await sc.upload_track("tok", b"audio", "a.wav", {"title": "T"}, artwork=None)
    body = route.calls.last.request.content
    assert b"track[genre]" not in body
    assert b"track[artwork_data]" not in body


@respx.mock
async def test_get_track_status_uses_oauth_header() -> None:
    track_url = f"{sc.SOUNDCLOUD_UPLOAD_URL}/555"
    route = respx.get(track_url).mock(
        return_value=httpx.Response(200, json={"id": 555, "state": "finished", "sharing": "public"})
    )
    track = await sc.get_track_status("tok", "555")
    assert track["state"] == "finished"
    assert route.calls.last.request.headers["Authorization"] == "OAuth tok"


@respx.mock
async def test_get_track_status_wraps_http_error() -> None:
    respx.get(f"{sc.SOUNDCLOUD_UPLOAD_URL}/555").mock(return_value=httpx.Response(404))
    with pytest.raises(sc.SoundCloudError):
        await sc.get_track_status("tok", "555")


@respx.mock
async def test_update_track_sharing_puts_sharing_field() -> None:
    track_url = f"{sc.SOUNDCLOUD_UPLOAD_URL}/555"
    route = respx.put(track_url).mock(return_value=httpx.Response(200, json={"id": 555, "sharing": "private"}))
    await sc.update_track_sharing("tok", "555", "private")
    request = route.calls.last.request
    assert request.headers["Authorization"] == "OAuth tok"
    assert b"track%5Bsharing%5D=private" in request.content  # urlencoded track[sharing]=private


async def test_update_track_sharing_rejects_invalid_value() -> None:
    with pytest.raises(sc.SoundCloudError):
        await sc.update_track_sharing("tok", "555", "secret")


class TestTokenExpiry:
    def test_uses_expires_in_seconds(self) -> None:
        from datetime import datetime, timezone

        before = datetime.now(timezone.utc)
        expiry = sc.token_expiry(3600)
        assert 3500 < (expiry - before).total_seconds() < 3700

    def test_defaults_to_one_hour_when_unparseable(self) -> None:
        from datetime import datetime, timezone

        expiry = sc.token_expiry(None)
        assert expiry > datetime.now(timezone.utc)
