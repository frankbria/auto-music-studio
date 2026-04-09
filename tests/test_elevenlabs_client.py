"""Unit tests for ElevenLabsClient (US-2.5)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from acemusic.elevenlabs_client import ElevenLabsClient, ElevenLabsError

FAKE_MP3 = b"ID3" + b"\x00" * 100  # minimal fake MP3 bytes


def _mock_response(status_code: int, content: bytes = FAKE_MP3, json_data: dict | None = None) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.content = content
    resp.json.return_value = json_data or {}
    resp.text = str(json_data or {})
    resp.raise_for_status.return_value = None
    return resp


def _error_response(status_code: int) -> MagicMock:
    resp = _mock_response(status_code, b"")
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        str(status_code),
        request=MagicMock(),
        response=resp,
    )
    return resp


class TestElevenLabsClientGenerate:
    """Tests for ElevenLabsClient.generate()."""

    def test_generate_returns_audio_bytes(self):
        """generate() returns bytes of audio data."""
        client = ElevenLabsClient(api_key="test-key")
        resp = _mock_response(200, FAKE_MP3)

        with patch("acemusic.elevenlabs_client.httpx.post", return_value=resp) as mock_post:
            result = client.generate(prompt="upbeat pop")

        assert isinstance(result, bytes)
        assert len(result) > 0
        mock_post.assert_called_once()

    def test_generate_sends_prompt_in_body(self):
        """generate() sends the prompt in the POST body."""
        client = ElevenLabsClient(api_key="test-key")
        resp = _mock_response(200, FAKE_MP3)

        with patch("acemusic.elevenlabs_client.httpx.post", return_value=resp) as mock_post:
            client.generate(prompt="jazz fusion")

        call_kwargs = mock_post.call_args
        body = call_kwargs.kwargs.get("json", {})
        assert body.get("prompt") == "jazz fusion"

    def test_generate_sends_api_key_header(self):
        """generate() sends xi-api-key in request headers."""
        client = ElevenLabsClient(api_key="secret-key-123")
        resp = _mock_response(200, FAKE_MP3)

        with patch("acemusic.elevenlabs_client.httpx.post", return_value=resp) as mock_post:
            client.generate(prompt="ambient")

        headers = mock_post.call_args.kwargs.get("headers", {})
        assert headers.get("xi-api-key") == "secret-key-123"

    def test_generate_sends_output_format_as_query_param(self):
        """generate() sends output_format as a query parameter."""
        client = ElevenLabsClient(api_key="test-key", output_format="mp3_44100_128")
        resp = _mock_response(200, FAKE_MP3)

        with patch("acemusic.elevenlabs_client.httpx.post", return_value=resp) as mock_post:
            client.generate(prompt="pop")

        params = mock_post.call_args.kwargs.get("params", {})
        assert params.get("output_format") == "mp3_44100_128"

    def test_generate_sends_duration_as_music_length_ms(self):
        """generate() converts --duration seconds to music_length_ms in body."""
        client = ElevenLabsClient(api_key="test-key")
        resp = _mock_response(200, FAKE_MP3)

        with patch("acemusic.elevenlabs_client.httpx.post", return_value=resp) as mock_post:
            client.generate(prompt="pop", duration=30.0)

        body = mock_post.call_args.kwargs.get("json", {})
        assert body.get("music_length_ms") == 30000

    def test_generate_sends_force_instrumental_when_set(self):
        """generate() sends force_instrumental: true when instrumental=True."""
        client = ElevenLabsClient(api_key="test-key")
        resp = _mock_response(200, FAKE_MP3)

        with patch("acemusic.elevenlabs_client.httpx.post", return_value=resp) as mock_post:
            client.generate(prompt="beat", instrumental=True)

        body = mock_post.call_args.kwargs.get("json", {})
        assert body.get("force_instrumental") is True

    def test_generate_raises_elevenlabs_error_on_401(self):
        """generate() raises ElevenLabsError on 401 Unauthorized."""
        client = ElevenLabsClient(api_key="bad-key")

        with patch("acemusic.elevenlabs_client.httpx.post", return_value=_error_response(401)):
            with pytest.raises(ElevenLabsError, match="401"):
                client.generate(prompt="test")

    def test_generate_raises_elevenlabs_error_on_connection_failure(self):
        """generate() raises ElevenLabsError when HTTP request fails."""
        client = ElevenLabsClient(api_key="test-key")

        with patch(
            "acemusic.elevenlabs_client.httpx.post",
            side_effect=httpx.ConnectError("connection refused"),
        ):
            with pytest.raises(ElevenLabsError):
                client.generate(prompt="test")


class TestElevenLabsClientValidateKey:
    """Tests for ElevenLabsClient.validate_key()."""

    def test_validate_key_returns_true_on_200(self):
        """validate_key() returns True when API key is valid (200)."""
        client = ElevenLabsClient(api_key="valid-key")
        resp = _mock_response(200, b"", json_data={"subscription": {}})

        with patch("acemusic.elevenlabs_client.httpx.get", return_value=resp):
            assert client.validate_key() is True

    def test_validate_key_returns_false_on_401(self):
        """validate_key() returns False when API key is rejected (401)."""
        client = ElevenLabsClient(api_key="bad-key")
        resp = _error_response(401)

        with patch("acemusic.elevenlabs_client.httpx.get", return_value=resp):
            assert client.validate_key() is False

    def test_validate_key_returns_false_on_connection_error(self):
        """validate_key() returns False when ElevenLabs is unreachable."""
        client = ElevenLabsClient(api_key="test-key")

        with patch(
            "acemusic.elevenlabs_client.httpx.get",
            side_effect=httpx.ConnectError("unreachable"),
        ):
            assert client.validate_key() is False

    def test_validate_key_sends_api_key_header(self):
        """validate_key() sends xi-api-key header."""
        client = ElevenLabsClient(api_key="my-key")
        resp = _mock_response(200, b"", json_data={})

        with patch("acemusic.elevenlabs_client.httpx.get", return_value=resp) as mock_get:
            client.validate_key()

        headers = mock_get.call_args.kwargs.get("headers", {})
        assert headers.get("xi-api-key") == "my-key"


@pytest.mark.integration
class TestElevenLabsIntegration:
    """Integration tests requiring a real ELEVENLABS_API_KEY."""

    def test_generate_returns_playable_audio(self):
        """Integration: generate() returns non-empty audio bytes from ElevenLabs."""
        import os

        key = os.environ.get("ELEVENLABS_API_KEY")
        if not key:
            pytest.skip("ELEVENLABS_API_KEY not set")

        fmt = os.environ.get("ELEVENLABS_OUTPUT_FORMAT", "mp3_44100_128")
        client = ElevenLabsClient(api_key=key, output_format=fmt)
        result = client.generate(prompt="upbeat pop", duration=10.0)

        assert isinstance(result, bytes)
        assert len(result) > 1000

    def test_validate_key_with_real_key(self):
        """Integration: validate_key() returns True with a real API key."""
        import os

        key = os.environ.get("ELEVENLABS_API_KEY")
        if not key:
            pytest.skip("ELEVENLABS_API_KEY not set")

        client = ElevenLabsClient(api_key=key)
        assert client.validate_key() is True
