"""Unit tests for ElevenLabsClient (US-2.5)."""

from __future__ import annotations

import io
import zipfile
from unittest.mock import MagicMock, patch

import httpx
import pytest

from acemusic.elevenlabs_client import (
    DURATION_MAX_S,
    DURATION_MIN_S,
    ELEVENLABS_STEM_LABELS,
    ElevenLabsClient,
    ElevenLabsError,
)

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


class TestElevenLabsClientDurationValidation:
    """Tests for duration validation in ElevenLabsClient.generate() (issue #96)."""

    @pytest.mark.parametrize("duration", [DURATION_MIN_S, DURATION_MAX_S, 30.0])
    def test_generate_accepts_durations_within_limits(self, duration):
        """generate() accepts durations at and within the API limits."""
        client = ElevenLabsClient(api_key="test-key")
        resp = _mock_response(200, FAKE_MP3)

        with patch("acemusic.elevenlabs_client.httpx.post", return_value=resp) as mock_post:
            client.generate(prompt="pop", duration=duration)

        body = mock_post.call_args.kwargs.get("json", {})
        assert body.get("music_length_ms") == int(duration * 1000)

    @pytest.mark.parametrize("duration", [2.9, 0.0, -1.0, 600.1, 9999.0])
    def test_generate_rejects_durations_outside_limits(self, duration):
        """generate() raises ElevenLabsError without calling the API for out-of-range durations."""
        client = ElevenLabsClient(api_key="test-key")

        with patch("acemusic.elevenlabs_client.httpx.post") as mock_post:
            with pytest.raises(ElevenLabsError):
                client.generate(prompt="pop", duration=duration)

        mock_post.assert_not_called()

    def test_duration_error_message_states_valid_range(self):
        """The validation error message includes the valid range."""
        client = ElevenLabsClient(api_key="test-key")

        with pytest.raises(ElevenLabsError, match=r"3.*600"):
            client.generate(prompt="pop", duration=1.0)


FAKE_PLAN = {
    "positive_global_styles": ["upbeat pop", "120 BPM"],
    "negative_global_styles": ["metal"],
    "sections": [
        {
            "section_name": "Intro",
            "positive_local_styles": ["atmospheric build"],
            "negative_local_styles": ["vocals"],
            "duration_ms": 8000,
            "lines": [],
        },
        {
            "section_name": "Chorus",
            "positive_local_styles": ["hook", "energetic"],
            "negative_local_styles": [],
            "duration_ms": 16000,
            "lines": ["Breaking through", "Nothing stops me now"],
        },
    ],
}


class TestElevenLabsClientCreatePlan:
    """Tests for ElevenLabsClient.create_plan() (issue #96)."""

    def test_create_plan_returns_parsed_json(self):
        """create_plan() returns the parsed composition plan dict."""
        client = ElevenLabsClient(api_key="test-key")
        resp = _mock_response(200, b"", json_data=FAKE_PLAN)

        with patch("acemusic.elevenlabs_client.httpx.post", return_value=resp):
            plan = client.create_plan(prompt="an upbeat pop anthem")

        assert plan == FAKE_PLAN

    def test_create_plan_posts_to_plan_endpoint_with_prompt(self):
        """create_plan() POSTs the prompt to /v1/music/plan."""
        client = ElevenLabsClient(api_key="test-key")
        resp = _mock_response(200, b"", json_data=FAKE_PLAN)

        with patch("acemusic.elevenlabs_client.httpx.post", return_value=resp) as mock_post:
            client.create_plan(prompt="an upbeat pop anthem")

        url = mock_post.call_args.args[0] if mock_post.call_args.args else mock_post.call_args.kwargs.get("url")
        assert url.endswith("/v1/music/plan")
        body = mock_post.call_args.kwargs.get("json", {})
        assert body.get("prompt") == "an upbeat pop anthem"
        assert "music_length_ms" not in body

    def test_create_plan_converts_duration_to_music_length_ms(self):
        """create_plan() converts duration seconds to music_length_ms."""
        client = ElevenLabsClient(api_key="test-key")
        resp = _mock_response(200, b"", json_data=FAKE_PLAN)

        with patch("acemusic.elevenlabs_client.httpx.post", return_value=resp) as mock_post:
            client.create_plan(prompt="anthem", duration=120.0)

        body = mock_post.call_args.kwargs.get("json", {})
        assert body.get("music_length_ms") == 120000

    def test_create_plan_sends_model_id_when_provided(self):
        """create_plan() includes model_id in the body when given."""
        client = ElevenLabsClient(api_key="test-key")
        resp = _mock_response(200, b"", json_data=FAKE_PLAN)

        with patch("acemusic.elevenlabs_client.httpx.post", return_value=resp) as mock_post:
            client.create_plan(prompt="anthem", model_id="music_v1")

        body = mock_post.call_args.kwargs.get("json", {})
        assert body.get("model_id") == "music_v1"

    def test_create_plan_sends_api_key_header(self):
        """create_plan() sends the xi-api-key header."""
        client = ElevenLabsClient(api_key="plan-key")
        resp = _mock_response(200, b"", json_data=FAKE_PLAN)

        with patch("acemusic.elevenlabs_client.httpx.post", return_value=resp) as mock_post:
            client.create_plan(prompt="anthem")

        headers = mock_post.call_args.kwargs.get("headers", {})
        assert headers.get("xi-api-key") == "plan-key"

    def test_create_plan_rejects_out_of_range_duration(self):
        """create_plan() validates duration against the API limits."""
        client = ElevenLabsClient(api_key="test-key")

        with patch("acemusic.elevenlabs_client.httpx.post") as mock_post:
            with pytest.raises(ElevenLabsError, match=r"3.*600"):
                client.create_plan(prompt="anthem", duration=601.0)

        mock_post.assert_not_called()

    def test_create_plan_raises_elevenlabs_error_on_http_error(self):
        """create_plan() raises ElevenLabsError on API errors."""
        client = ElevenLabsClient(api_key="bad-key")

        with patch("acemusic.elevenlabs_client.httpx.post", return_value=_error_response(422)):
            with pytest.raises(ElevenLabsError, match="422"):
                client.create_plan(prompt="anthem")

    def test_create_plan_raises_elevenlabs_error_on_connection_failure(self):
        """create_plan() raises ElevenLabsError when the request fails."""
        client = ElevenLabsClient(api_key="test-key")

        with patch(
            "acemusic.elevenlabs_client.httpx.post",
            side_effect=httpx.ConnectError("connection refused"),
        ):
            with pytest.raises(ElevenLabsError):
                client.create_plan(prompt="anthem")

    def test_create_plan_raises_elevenlabs_error_on_malformed_json(self):
        """A 2xx response with unparseable JSON raises ElevenLabsError, not ValueError."""
        client = ElevenLabsClient(api_key="test-key")
        resp = _mock_response(200, b"not json")
        resp.json.side_effect = ValueError("Expecting value")

        with patch("acemusic.elevenlabs_client.httpx.post", return_value=resp):
            with pytest.raises(ElevenLabsError, match="invalid"):
                client.create_plan(prompt="anthem")

    def test_create_plan_raises_elevenlabs_error_on_non_dict_payload(self):
        """A 2xx response whose JSON is not an object raises ElevenLabsError."""
        client = ElevenLabsClient(api_key="test-key")
        resp = _mock_response(200, b"[]")
        resp.json.return_value = ["not", "a", "plan"]

        with patch("acemusic.elevenlabs_client.httpx.post", return_value=resp):
            with pytest.raises(ElevenLabsError, match="invalid"):
                client.create_plan(prompt="anthem")


class TestElevenLabsClientGenerateFromPlan:
    """Tests for ElevenLabsClient.generate_from_plan() (issue #96)."""

    def test_generate_from_plan_returns_audio_bytes(self):
        """generate_from_plan() returns raw audio bytes on success."""
        client = ElevenLabsClient(api_key="test-key")
        resp = _mock_response(200, FAKE_MP3)

        with patch("acemusic.elevenlabs_client.httpx.post", return_value=resp):
            result = client.generate_from_plan(FAKE_PLAN)

        assert result == FAKE_MP3

    def test_generate_from_plan_sends_plan_in_body(self):
        """generate_from_plan() sends composition_plan (and no prompt) in the body."""
        client = ElevenLabsClient(api_key="test-key")
        resp = _mock_response(200, FAKE_MP3)

        with patch("acemusic.elevenlabs_client.httpx.post", return_value=resp) as mock_post:
            client.generate_from_plan(FAKE_PLAN)

        url = mock_post.call_args.args[0] if mock_post.call_args.args else mock_post.call_args.kwargs.get("url")
        assert url.endswith("/v1/music")
        body = mock_post.call_args.kwargs.get("json", {})
        assert body.get("composition_plan") == FAKE_PLAN
        assert "prompt" not in body
        assert "force_instrumental" not in body

    def test_generate_from_plan_sends_respect_sections_durations(self):
        """generate_from_plan() includes respect_sections_durations in the body."""
        client = ElevenLabsClient(api_key="test-key")
        resp = _mock_response(200, FAKE_MP3)

        with patch("acemusic.elevenlabs_client.httpx.post", return_value=resp) as mock_post:
            client.generate_from_plan(FAKE_PLAN, respect_durations=False)

        body = mock_post.call_args.kwargs.get("json", {})
        assert body.get("respect_sections_durations") is False

    def test_generate_from_plan_sends_seed_when_provided(self):
        """generate_from_plan() forwards the seed (valid only in plan mode)."""
        client = ElevenLabsClient(api_key="test-key")
        resp = _mock_response(200, FAKE_MP3)

        with patch("acemusic.elevenlabs_client.httpx.post", return_value=resp) as mock_post:
            client.generate_from_plan(FAKE_PLAN, seed=42)

        body = mock_post.call_args.kwargs.get("json", {})
        assert body.get("seed") == 42

    def test_generate_from_plan_sends_output_format_as_query_param(self):
        """generate_from_plan() sends output_format as a query parameter."""
        client = ElevenLabsClient(api_key="test-key", output_format="mp3_44100_192")
        resp = _mock_response(200, FAKE_MP3)

        with patch("acemusic.elevenlabs_client.httpx.post", return_value=resp) as mock_post:
            client.generate_from_plan(FAKE_PLAN)

        params = mock_post.call_args.kwargs.get("params", {})
        assert params.get("output_format") == "mp3_44100_192"

    def test_generate_from_plan_raises_elevenlabs_error_on_http_error(self):
        """generate_from_plan() raises ElevenLabsError on API errors."""
        client = ElevenLabsClient(api_key="test-key")

        with patch("acemusic.elevenlabs_client.httpx.post", return_value=_error_response(422)):
            with pytest.raises(ElevenLabsError, match="422"):
                client.generate_from_plan(FAKE_PLAN)

    def test_generate_from_plan_raises_elevenlabs_error_on_connection_failure(self):
        """generate_from_plan() raises ElevenLabsError when the request fails."""
        client = ElevenLabsClient(api_key="test-key")

        with patch(
            "acemusic.elevenlabs_client.httpx.post",
            side_effect=httpx.ConnectError("connection refused"),
        ):
            with pytest.raises(ElevenLabsError):
                client.generate_from_plan(FAKE_PLAN)


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


def _make_stem_zip(labels: list[str], ext: str = "mp3") -> bytes:
    """Build an in-memory ZIP archive containing one fake audio file per label."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for label in labels:
            zf.writestr(f"{label}.{ext}", FAKE_MP3)
    return buf.getvalue()


class TestElevenLabsClientSeparateStems:
    """Tests for ElevenLabsClient.separate_stems() (issue #97)."""

    @pytest.fixture
    def audio_file(self, tmp_path):
        path = tmp_path / "fullmix.wav"
        path.write_bytes(b"fake audio data")
        return path

    def test_separate_stems_returns_all_six_labels(self, audio_file):
        """separate_stems() returns a dict with all six stem labels mapped to bytes."""
        client = ElevenLabsClient(api_key="test-key")
        resp = _mock_response(200, _make_stem_zip(ELEVENLABS_STEM_LABELS))

        with patch("acemusic.elevenlabs_client.httpx.post", return_value=resp):
            result = client.separate_stems(audio_file)

        assert set(result.keys()) == set(ELEVENLABS_STEM_LABELS)
        for label, data in result.items():
            assert isinstance(data, bytes), label
            assert len(data) > 0, label

    def test_separate_stems_sends_api_key_header(self, audio_file):
        """separate_stems() sends xi-api-key in request headers."""
        client = ElevenLabsClient(api_key="secret-key-123")
        resp = _mock_response(200, _make_stem_zip(ELEVENLABS_STEM_LABELS))

        with patch("acemusic.elevenlabs_client.httpx.post", return_value=resp) as mock_post:
            client.separate_stems(audio_file)

        headers = mock_post.call_args.kwargs.get("headers", {})
        assert headers.get("xi-api-key") == "secret-key-123"

    def test_separate_stems_sends_stem_variation_id_as_form_field(self, audio_file):
        """separate_stems() passes stem_variation_id as multipart form data."""
        client = ElevenLabsClient(api_key="test-key")
        resp = _mock_response(200, _make_stem_zip(ELEVENLABS_STEM_LABELS))

        with patch("acemusic.elevenlabs_client.httpx.post", return_value=resp) as mock_post:
            client.separate_stems(audio_file, stem_variation_id="two_stems_v1")

        data = mock_post.call_args.kwargs.get("data", {})
        assert data.get("stem_variation_id") == "two_stems_v1"

    def test_separate_stems_defaults_to_six_stems_variation(self, audio_file):
        """separate_stems() defaults stem_variation_id to six_stems_v1."""
        client = ElevenLabsClient(api_key="test-key")
        resp = _mock_response(200, _make_stem_zip(ELEVENLABS_STEM_LABELS))

        with patch("acemusic.elevenlabs_client.httpx.post", return_value=resp) as mock_post:
            client.separate_stems(audio_file)

        data = mock_post.call_args.kwargs.get("data", {})
        assert data.get("stem_variation_id") == "six_stems_v1"

    def test_separate_stems_uploads_file_as_multipart(self, audio_file):
        """separate_stems() uploads the audio under the 'file' multipart field."""
        client = ElevenLabsClient(api_key="test-key")
        resp = _mock_response(200, _make_stem_zip(ELEVENLABS_STEM_LABELS))

        with patch("acemusic.elevenlabs_client.httpx.post", return_value=resp) as mock_post:
            client.separate_stems(audio_file)

        files = mock_post.call_args.kwargs.get("files", {})
        assert "file" in files

    def test_separate_stems_sends_output_format_as_query_param(self, audio_file):
        """separate_stems() sends the client output_format as a query parameter."""
        client = ElevenLabsClient(api_key="test-key", output_format="mp3_44100_128")
        resp = _mock_response(200, _make_stem_zip(ELEVENLABS_STEM_LABELS))

        with patch("acemusic.elevenlabs_client.httpx.post", return_value=resp) as mock_post:
            client.separate_stems(audio_file)

        params = mock_post.call_args.kwargs.get("params", {})
        assert params.get("output_format") == "mp3_44100_128"

    def test_separate_stems_maps_unknown_filenames_to_filename_stem(self, audio_file):
        """ZIP entries with unrecognised names fall back to the filename stem as label."""
        client = ElevenLabsClient(api_key="test-key")
        resp = _mock_response(200, _make_stem_zip(["mystery_track"]))

        with patch("acemusic.elevenlabs_client.httpx.post", return_value=resp):
            result = client.separate_stems(audio_file)

        assert set(result.keys()) == {"mystery_track"}

    def test_separate_stems_matches_labels_within_longer_filenames(self, audio_file):
        """ZIP entries like 'track_01_vocals.mp3' map to the known 'vocals' label."""
        client = ElevenLabsClient(api_key="test-key")
        resp = _mock_response(200, _make_stem_zip(["track_01_vocals", "track_02_drums"]))

        with patch("acemusic.elevenlabs_client.httpx.post", return_value=resp):
            result = client.separate_stems(audio_file)

        assert set(result.keys()) == {"vocals", "drums"}

    def test_separate_stems_raises_elevenlabs_error_on_401(self, audio_file):
        """separate_stems() raises ElevenLabsError on 401 Unauthorized."""
        client = ElevenLabsClient(api_key="bad-key")

        with patch("acemusic.elevenlabs_client.httpx.post", return_value=_error_response(401)):
            with pytest.raises(ElevenLabsError, match="401"):
                client.separate_stems(audio_file)

    def test_separate_stems_raises_elevenlabs_error_on_connection_failure(self, audio_file):
        """separate_stems() raises ElevenLabsError when the request fails."""
        client = ElevenLabsClient(api_key="test-key")

        with patch(
            "acemusic.elevenlabs_client.httpx.post",
            side_effect=httpx.ConnectError("connection refused"),
        ):
            with pytest.raises(ElevenLabsError):
                client.separate_stems(audio_file)

    def test_separate_stems_raises_elevenlabs_error_on_malformed_zip(self, audio_file):
        """separate_stems() raises ElevenLabsError when the response is not a valid ZIP."""
        client = ElevenLabsClient(api_key="test-key")
        resp = _mock_response(200, b"this is not a zip archive")

        with patch("acemusic.elevenlabs_client.httpx.post", return_value=resp):
            with pytest.raises(ElevenLabsError, match="(?i)zip"):
                client.separate_stems(audio_file)

    def test_separate_stems_raises_elevenlabs_error_on_empty_zip(self, audio_file):
        """separate_stems() raises ElevenLabsError when the ZIP contains no stems."""
        client = ElevenLabsClient(api_key="test-key")
        resp = _mock_response(200, _make_stem_zip([]))

        with patch("acemusic.elevenlabs_client.httpx.post", return_value=resp):
            with pytest.raises(ElevenLabsError, match="(?i)no stems"):
                client.separate_stems(audio_file)

    def test_separate_stems_raises_elevenlabs_error_on_missing_file(self, tmp_path):
        """separate_stems() raises ElevenLabsError when the audio file does not exist."""
        client = ElevenLabsClient(api_key="test-key")

        with pytest.raises(ElevenLabsError):
            client.separate_stems(tmp_path / "does-not-exist.wav")


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

    def test_compose_plan_roundtrip_returns_playable_audio(self):
        """Integration: create_plan() → generate_from_plan() yields decodable MP3 audio."""
        import io
        import os

        key = os.environ.get("ELEVENLABS_API_KEY")
        if not key:
            pytest.skip("ELEVENLABS_API_KEY not set")

        client = ElevenLabsClient(api_key=key, output_format="mp3_44100_128")
        plan = client.create_plan(prompt="short upbeat jingle", duration=10.0)
        assert plan.get("sections"), "plan should contain sections"

        audio = client.generate_from_plan(plan)
        assert isinstance(audio, bytes)
        assert len(audio) > 1000

        from pydub import AudioSegment

        segment = AudioSegment.from_file(io.BytesIO(audio), format="mp3")
        assert segment.duration_seconds > 1.0
