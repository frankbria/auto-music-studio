"""Unit tests for the RunPod serverless handler (US-11.3, ``docker/handler.py``).

The handler lives in ``docker/`` (it is copied into the Docker image), not inside the
``acemusic`` package, so it is loaded by path. All HTTP (httpx), the subprocess spawn,
and ``time.sleep`` are patched so these tests run in CI without Docker, a GPU, model
weights, or the network.

The handler must speak the *real* ACE-Step API contract (mirroring
:class:`acemusic.client.AceStepClient`): the ``{"data": ..., "code": 200}`` envelope,
``/query_result`` with ``{"task_id_list": [...]}``, and integer status codes
(0=pending, 1=completed, 2=failed). Its returned ``output`` uses the
``{"status", "audio_urls"}`` shape the platform's ``RunPodClient._extract_audio_urls``
(US-11.2) already understands.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

_HANDLER_PATH = Path(__file__).resolve().parent.parent / "docker" / "handler.py"


def _load_handler():
    """Load docker/handler.py as a standalone module (fresh globals each call)."""
    spec = importlib.util.spec_from_file_location("acestep_handler", _HANDLER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def handler_mod():
    return _load_handler()


def _resp(json_data: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.text = str(json_data)
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError("error", request=MagicMock(), response=resp)
    else:
        resp.raise_for_status.return_value = None
    return resp


def _release(task_id: str = "task-1") -> MagicMock:
    """A /release_task response in the real `{data: {...}, code: 200}` envelope."""
    return _resp({"data": {"task_id": task_id}, "code": 200, "error": None})


def _query(status: int, *, result: str = "[]", error=None) -> MagicMock:
    """A /query_result response: data is a list of items with integer status."""
    return _resp({"data": [{"status": status, "result": result, "error": error}], "code": 200})


_RESULT_TWO_CLIPS = '[{"file": "/v1/audio?path=a.wav"}, {"file": "/v1/audio?path=b.wav"}]'
_RESULT_ONE_CLIP = '[{"file": "/v1/audio?path=a.wav"}]'


def _audio_resp(body: bytes) -> MagicMock:
    """A /v1/audio download response carrying raw clip bytes."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.content = body
    resp.raise_for_status.return_value = None
    return resp


def _mock_boto3():
    """A stand-in boto3 whose S3 client records uploads and mints predictable URLs."""
    client = MagicMock()
    client.generate_presigned_url.side_effect = lambda op, Params, ExpiresIn: f"https://s3.test/{Params['Key']}?sig"
    module = MagicMock()
    module.client.return_value = client
    return module, client


class TestStartApiServer:
    def test_spawns_from_app_dir_with_api_key_and_hf_home(self, handler_mod, monkeypatch):
        monkeypatch.setenv("ACESTEP_API_KEY", "secret-key")
        monkeypatch.delenv("HF_HOME", raising=False)
        popen = MagicMock()
        popen.return_value.poll.return_value = None
        with (
            patch.object(handler_mod.subprocess, "Popen", popen),
            patch.object(handler_mod.httpx, "get", return_value=_resp({"data": {}})),
            patch.object(handler_mod.time, "sleep"),
        ):
            assert handler_mod.start_api_server() is True
        args, kwargs = popen.call_args
        assert args[0] == ["uv", "run", "acestep-api"]
        # Runs from the installed project (has the venv), NOT the weights volume.
        assert kwargs["cwd"] == handler_mod.APP_DIR
        assert kwargs["env"]["ACESTEP_API_KEY"] == "secret-key"
        # Weights load from the Network Volume cache via HF_HOME.
        assert kwargs["env"]["HF_HOME"] == handler_mod.MODEL_CACHE

    def test_respects_preset_hf_home(self, handler_mod, monkeypatch):
        monkeypatch.setenv("HF_HOME", "/custom/cache")
        popen = MagicMock()
        popen.return_value.poll.return_value = None
        with (
            patch.object(handler_mod.subprocess, "Popen", popen),
            patch.object(handler_mod.httpx, "get", return_value=_resp({"data": {}})),
            patch.object(handler_mod.time, "sleep"),
        ):
            handler_mod.start_api_server()
        assert popen.call_args.kwargs["env"]["HF_HOME"] == "/custom/cache"

    def test_returns_false_when_never_healthy(self, handler_mod):
        with (
            patch.object(handler_mod.subprocess, "Popen", MagicMock()),
            patch.object(handler_mod.httpx, "get", side_effect=httpx.ConnectError("down")),
            patch.object(handler_mod.time, "sleep") as sleep,
        ):
            assert handler_mod.start_api_server() is False
        # Polled the full budget before giving up.
        assert sleep.call_count == handler_mod._HEALTH_ATTEMPTS

    def test_reuses_already_running_process(self, handler_mod):
        running = MagicMock()
        running.poll.return_value = None  # still alive
        handler_mod.api_process = running
        popen = MagicMock()
        with (
            patch.object(handler_mod.subprocess, "Popen", popen),
            patch.object(handler_mod.httpx, "get", return_value=_resp({"data": {}})),
            patch.object(handler_mod.time, "sleep"),
        ):
            assert handler_mod.start_api_server() is True
        popen.assert_not_called()


class TestHandlerHappyPath:
    def test_returns_completed_with_audio_urls(self, handler_mod):
        post = MagicMock(side_effect=[_release("t9"), _query(1, result=_RESULT_TWO_CLIPS)])
        with (
            patch.object(handler_mod, "start_api_server", return_value=True),
            patch.object(handler_mod.httpx, "post", post),
            patch.object(handler_mod.time, "sleep"),
        ):
            out = handler_mod.handler({"input": {"prompt": "lofi beats"}})
        assert out["status"] == "completed"
        assert out["audio_urls"] == [
            "http://localhost:8001/v1/audio?path=a.wav",
            "http://localhost:8001/v1/audio?path=b.wav",
        ]

    def test_submit_unwraps_data_envelope_and_uses_task_id_list(self, handler_mod):
        post = MagicMock(side_effect=[_release("abc"), _query(1, result=_RESULT_TWO_CLIPS)])
        with (
            patch.object(handler_mod, "start_api_server", return_value=True),
            patch.object(handler_mod.httpx, "post", post),
            patch.object(handler_mod.time, "sleep"),
        ):
            handler_mod.handler({"input": {"prompt": "x"}})
        release_call, query_call = post.call_args_list
        assert release_call.args[0].endswith("/release_task")
        assert release_call.kwargs["json"] == {"prompt": "x"}
        assert query_call.args[0].endswith("/query_result")
        assert query_call.kwargs["json"] == {"task_id_list": ["abc"]}

    def test_polls_while_pending_then_completes(self, handler_mod):
        post = MagicMock(side_effect=[_release("t"), _query(0), _query(0), _query(1, result=_RESULT_TWO_CLIPS)])
        with (
            patch.object(handler_mod, "start_api_server", return_value=True),
            patch.object(handler_mod.httpx, "post", post),
            patch.object(handler_mod.time, "sleep") as sleep,
        ):
            out = handler_mod.handler({"input": {}})
        assert out["status"] == "completed"
        assert sleep.call_count == 2  # slept between the two pending polls


class TestHandlerFailurePaths:
    def test_failed_status_surfaces_error(self, handler_mod):
        post = MagicMock(side_effect=[_release("t"), _query(2, error="OOM on GPU")])
        with (
            patch.object(handler_mod, "start_api_server", return_value=True),
            patch.object(handler_mod.httpx, "post", post),
            patch.object(handler_mod.time, "sleep"),
        ):
            out = handler_mod.handler({"input": {}})
        assert out["status"] == "failed"
        assert "OOM on GPU" in out["error"]
        assert out["audio_urls"] == []

    def test_missing_task_id_returns_failed(self, handler_mod):
        post = MagicMock(return_value=_resp({"data": {}, "code": 200}))
        with (
            patch.object(handler_mod, "start_api_server", return_value=True),
            patch.object(handler_mod.httpx, "post", post),
        ):
            out = handler_mod.handler({"input": {}})
        assert out["status"] == "failed"
        assert out["audio_urls"] == []

    def test_api_server_down_returns_failed_without_http(self, handler_mod):
        post = MagicMock()
        with (
            patch.object(handler_mod, "start_api_server", return_value=False),
            patch.object(handler_mod.httpx, "post", post),
        ):
            out = handler_mod.handler({"input": {}})
        assert out["status"] == "failed"
        post.assert_not_called()

    def test_http_error_returns_failed(self, handler_mod):
        with (
            patch.object(handler_mod, "start_api_server", return_value=True),
            patch.object(handler_mod.httpx, "post", side_effect=httpx.ConnectError("refused")),
        ):
            out = handler_mod.handler({"input": {}})
        assert out["status"] == "failed"
        assert out["audio_urls"] == []

    def test_timeout_returns_failed(self, handler_mod):
        post = MagicMock(side_effect=[_release("t")] + [_query(0)] * 50)
        # monotonic jumps past the deadline after the first poll.
        clock = iter([0.0] + [handler_mod._POLL_TIMEOUT + 1] * 50)
        with (
            patch.object(handler_mod, "start_api_server", return_value=True),
            patch.object(handler_mod.httpx, "post", post),
            patch.object(handler_mod.time, "sleep"),
            patch.object(handler_mod.time, "monotonic", lambda: next(clock)),
        ):
            out = handler_mod.handler({"input": {}})
        assert out["status"] == "failed"
        assert "timed out" in out["error"].lower()


class TestAudioUrlExtraction:
    def test_parses_json_string_result(self, handler_mod):
        urls = handler_mod._extract_audio_urls({"result": _RESULT_TWO_CLIPS})
        assert urls == [
            "http://localhost:8001/v1/audio?path=a.wav",
            "http://localhost:8001/v1/audio?path=b.wav",
        ]

    def test_malformed_result_yields_empty(self, handler_mod):
        assert handler_mod._extract_audio_urls({"result": "not-json"}) == []

    def test_absolute_url_passed_through(self, handler_mod):
        item = {"result": '[{"file": "https://cdn.test/x.wav"}]'}
        assert handler_mod._extract_audio_urls(item) == ["https://cdn.test/x.wav"]


class TestS3Delivery:
    """US-11.x: when S3 is configured the handler re-hosts clips and returns presigned URLs."""

    def test_no_bucket_returns_worker_local_urls(self, handler_mod, monkeypatch):
        # Local / pod use (not a serverless worker): localhost is reachable, so the
        # worker-local URLs pass through unchanged.
        monkeypatch.delenv("ACEMUSIC_S3_BUCKET", raising=False)
        monkeypatch.delenv("RUNPOD_ENDPOINT_ID", raising=False)
        post = MagicMock(side_effect=[_release("t"), _query(1, result=_RESULT_TWO_CLIPS)])
        with (
            patch.object(handler_mod, "start_api_server", return_value=True),
            patch.object(handler_mod.httpx, "post", post),
            patch.object(handler_mod.time, "sleep"),
        ):
            out = handler_mod.handler({"input": {}})
        assert out["audio_urls"] == [
            "http://localhost:8001/v1/audio?path=a.wav",
            "http://localhost:8001/v1/audio?path=b.wav",
        ]

    def test_serverless_without_bucket_fails_loudly(self, handler_mod, monkeypatch):
        # On a real serverless worker the platform is remote; missing storage is a
        # misconfiguration, not a silent fall-back to unreachable localhost URLs.
        monkeypatch.delenv("ACEMUSIC_S3_BUCKET", raising=False)
        monkeypatch.setenv("RUNPOD_ENDPOINT_ID", "ep-123")
        post = MagicMock(side_effect=[_release("t"), _query(1, result=_RESULT_ONE_CLIP)])
        with (
            patch.object(handler_mod, "start_api_server", return_value=True),
            patch.object(handler_mod.httpx, "post", post),
            patch.object(handler_mod.time, "sleep"),
        ):
            out = handler_mod.handler({"input": {}})
        assert out["status"] == "failed"
        assert "ACEMUSIC_S3_BUCKET" in out["error"]
        assert out["audio_urls"] == []

    def test_token_not_sent_to_external_result_host(self, handler_mod, monkeypatch):
        # ACE-Step can return an absolute third-party URL; the ACE-Step token must not
        # be disclosed to it (only the worker-local server gets the bearer header).
        monkeypatch.setenv("ACEMUSIC_S3_BUCKET", "b")
        monkeypatch.setenv("ACESTEP_API_KEY", "secret")
        boto3_mod, _ = _mock_boto3()
        post = MagicMock(side_effect=[_release("job"), _query(1, result='[{"file": "https://cdn.test/x.wav"}]')])
        get = MagicMock(return_value=_audio_resp(b"x"))
        with (
            patch.object(handler_mod, "boto3", boto3_mod),
            patch.object(handler_mod, "start_api_server", return_value=True),
            patch.object(handler_mod.httpx, "post", post),
            patch.object(handler_mod.httpx, "get", get),
            patch.object(handler_mod.time, "sleep"),
        ):
            handler_mod.handler({"input": {}})
        assert get.call_args.args[0] == "https://cdn.test/x.wav"
        assert get.call_args.kwargs["headers"] == {}

    def test_token_not_leaked_via_userinfo_spoofed_host(self, handler_mod, monkeypatch):
        # A userinfo-spoofed URL parses to an attacker-controlled host, so the parsed
        # origin (not a string prefix) decides whether the token is attached.
        monkeypatch.setenv("ACEMUSIC_S3_BUCKET", "b")
        monkeypatch.setenv("ACESTEP_API_KEY", "secret")
        boto3_mod, _ = _mock_boto3()
        spoof = "http://localhost@attacker.example/x.wav"
        post = MagicMock(side_effect=[_release("job"), _query(1, result=f'[{{"file": "{spoof}"}}]')])
        get = MagicMock(return_value=_audio_resp(b"x"))
        with (
            patch.object(handler_mod, "boto3", boto3_mod),
            patch.object(handler_mod, "start_api_server", return_value=True),
            patch.object(handler_mod.httpx, "post", post),
            patch.object(handler_mod.httpx, "get", get),
            patch.object(handler_mod.time, "sleep"),
        ):
            handler_mod.handler({"input": {}})
        assert get.call_args.args[0] == spoof
        assert get.call_args.kwargs["headers"] == {}

    def test_origin_check_rejects_port_prefixed_spoof(self, handler_mod):
        # Regression for the codex finding: a string-prefix check would accept a URL of
        # the form <local-base>@otherhost (it starts with the base) yet httpx connects to
        # otherhost. Built from parts so no literal credential string is committed.
        port_spoof = handler_mod.API_BASE_URL + "@attacker.example/x.wav"
        assert port_spoof.startswith(handler_mod.API_BASE_URL)  # the trap a prefix check falls into
        assert handler_mod._is_worker_local(port_spoof) is False

    def test_uploads_clips_to_s3_and_returns_presigned_urls(self, handler_mod, monkeypatch):
        monkeypatch.setenv("ACEMUSIC_S3_BUCKET", "clips-bucket")
        monkeypatch.delenv("ACEMUSIC_S3_PREFIX", raising=False)
        monkeypatch.delenv("ACESTEP_API_KEY", raising=False)
        boto3_mod, client = _mock_boto3()
        post = MagicMock(side_effect=[_release("job7"), _query(1, result=_RESULT_TWO_CLIPS)])
        get = MagicMock(return_value=_audio_resp(b"RIFFdata"))
        with (
            patch.object(handler_mod, "boto3", boto3_mod),
            patch.object(handler_mod, "start_api_server", return_value=True),
            patch.object(handler_mod.httpx, "post", post),
            patch.object(handler_mod.httpx, "get", get),
            patch.object(handler_mod.time, "sleep"),
        ):
            out = handler_mod.handler({"input": {"prompt": "x"}})
        assert out["status"] == "completed"
        # Presigned S3 URLs replace the unreachable worker-local URLs.
        assert out["audio_urls"] == [
            "https://s3.test/runpod/job7/0.wav?sig",
            "https://s3.test/runpod/job7/1.wav?sig",
        ]
        # Each clip was fetched from the worker-local ACE-Step server...
        assert [c.args[0] for c in get.call_args_list] == [
            "http://localhost:8001/v1/audio?path=a.wav",
            "http://localhost:8001/v1/audio?path=b.wav",
        ]
        # ...then uploaded under runpod/<task_id>/<i><ext> with bytes + audio content type.
        first = client.put_object.call_args_list[0].kwargs
        assert [c.kwargs["Key"] for c in client.put_object.call_args_list] == [
            "runpod/job7/0.wav",
            "runpod/job7/1.wav",
        ]
        assert first["Bucket"] == "clips-bucket"
        assert first["Body"] == b"RIFFdata"
        assert first["ContentType"].startswith("audio/")

    def test_prefix_prepended_to_s3_key(self, handler_mod, monkeypatch):
        monkeypatch.setenv("ACEMUSIC_S3_BUCKET", "b")
        monkeypatch.setenv("ACEMUSIC_S3_PREFIX", "audio/")
        boto3_mod, client = _mock_boto3()
        post = MagicMock(side_effect=[_release("job"), _query(1, result=_RESULT_ONE_CLIP)])
        with (
            patch.object(handler_mod, "boto3", boto3_mod),
            patch.object(handler_mod, "start_api_server", return_value=True),
            patch.object(handler_mod.httpx, "post", post),
            patch.object(handler_mod.httpx, "get", MagicMock(return_value=_audio_resp(b"x"))),
            patch.object(handler_mod.time, "sleep"),
        ):
            handler_mod.handler({"input": {}})
        assert client.put_object.call_args.kwargs["Key"] == "audio/runpod/job/0.wav"

    def test_clip_download_sends_api_key(self, handler_mod, monkeypatch):
        monkeypatch.setenv("ACEMUSIC_S3_BUCKET", "b")
        monkeypatch.setenv("ACESTEP_API_KEY", "secret")
        boto3_mod, _ = _mock_boto3()
        post = MagicMock(side_effect=[_release("job"), _query(1, result=_RESULT_ONE_CLIP)])
        get = MagicMock(return_value=_audio_resp(b"x"))
        with (
            patch.object(handler_mod, "boto3", boto3_mod),
            patch.object(handler_mod, "start_api_server", return_value=True),
            patch.object(handler_mod.httpx, "post", post),
            patch.object(handler_mod.httpx, "get", get),
            patch.object(handler_mod.time, "sleep"),
        ):
            handler_mod.handler({"input": {}})
        assert get.call_args.kwargs["headers"] == {"Authorization": "Bearer secret"}

    def test_s3_upload_failure_returns_failed(self, handler_mod, monkeypatch):
        monkeypatch.setenv("ACEMUSIC_S3_BUCKET", "b")
        boto3_mod, client = _mock_boto3()
        client.put_object.side_effect = RuntimeError("AccessDenied")
        post = MagicMock(side_effect=[_release("job"), _query(1, result=_RESULT_ONE_CLIP)])
        with (
            patch.object(handler_mod, "boto3", boto3_mod),
            patch.object(handler_mod, "start_api_server", return_value=True),
            patch.object(handler_mod.httpx, "post", post),
            patch.object(handler_mod.httpx, "get", MagicMock(return_value=_audio_resp(b"x"))),
            patch.object(handler_mod.time, "sleep"),
        ):
            out = handler_mod.handler({"input": {}})
        assert out["status"] == "failed"
        assert "deliver audio to s3" in out["error"].lower()
        assert out["audio_urls"] == []

    def test_bucket_set_but_boto3_missing_returns_failed(self, handler_mod, monkeypatch):
        monkeypatch.setenv("ACEMUSIC_S3_BUCKET", "b")
        post = MagicMock(side_effect=[_release("job"), _query(1, result=_RESULT_ONE_CLIP)])
        with (
            patch.object(handler_mod, "boto3", None),
            patch.object(handler_mod, "start_api_server", return_value=True),
            patch.object(handler_mod.httpx, "post", post),
            patch.object(handler_mod.time, "sleep"),
        ):
            out = handler_mod.handler({"input": {}})
        assert out["status"] == "failed"
        assert "boto3" in out["error"].lower()
        assert out["audio_urls"] == []


class TestModuleContract:
    def test_importable_without_runpod_and_exposes_callables(self, handler_mod):
        # The module imported via the fixture without the runpod SDK installed,
        # proving runpod.serverless.start is not invoked at import time.
        assert callable(handler_mod.handler)
        assert callable(handler_mod.start_api_server)
