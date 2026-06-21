"""Tests for the OpenAI image-generation client (US-13.1, issue #132).

``ImageGenerationClient`` calls the OpenAI images REST endpoint over httpx (no
SDK, mirroring the other backend clients) and returns raw image bytes. These mock
httpx, so they run in CI; the live DALL-E path is exercised only with a real key.
"""

import base64
from unittest.mock import MagicMock, patch

import httpx
import pytest

from acemusic.image_client import ImageGenerationClient, ImageGenerationError

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
_B64 = base64.b64encode(_PNG).decode()


def _ok_response() -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json.return_value = {"data": [{"b64_json": _B64}]}
    resp.raise_for_status.return_value = None
    return resp


class TestGenerateImages:
    def test_returns_one_image_per_requested_option(self) -> None:
        client = ImageGenerationClient(api_key="sk-test")
        with patch("acemusic.image_client.httpx.post", return_value=_ok_response()) as post:
            images = client.generate_images("ambient album cover", count=4)
        assert images == [_PNG] * 4
        assert post.call_count == 4

    def test_sends_prompt_and_size_in_body(self) -> None:
        client = ImageGenerationClient(api_key="sk-test")
        with patch("acemusic.image_client.httpx.post", return_value=_ok_response()) as post:
            client.generate_images("dreamy synthwave", count=1)
        body = post.call_args.kwargs["json"]
        assert body["prompt"] == "dreamy synthwave"
        assert body["size"] == "1024x1024"
        assert body["n"] == 1
        assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer sk-test"

    def test_http_error_becomes_domain_error(self) -> None:
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 401
        resp.raise_for_status.side_effect = httpx.HTTPStatusError("unauthorized", request=MagicMock(), response=resp)
        client = ImageGenerationClient(api_key="bad")
        with patch("acemusic.image_client.httpx.post", return_value=resp):
            with pytest.raises(ImageGenerationError):
                client.generate_images("x", count=1)

    def test_connection_error_becomes_domain_error(self) -> None:
        client = ImageGenerationClient(api_key="sk-test")
        with patch("acemusic.image_client.httpx.post", side_effect=httpx.ConnectError("boom")):
            with pytest.raises(ImageGenerationError):
                client.generate_images("x", count=1)

    def test_empty_data_becomes_domain_error(self) -> None:
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.json.return_value = {"data": []}
        resp.raise_for_status.return_value = None
        client = ImageGenerationClient(api_key="sk-test")
        with patch("acemusic.image_client.httpx.post", return_value=resp):
            with pytest.raises(ImageGenerationError):
                client.generate_images("x", count=1)
