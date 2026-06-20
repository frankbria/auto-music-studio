"""Demo driver for US-11.x remote audio delivery (issue #150).

Exercises the *real* handler and platform-client logic. Only the genuinely external
pieces are simulated, because no GPU / RunPod / S3 credentials are available here:
  - S3 is a real in-memory store (records the bytes actually uploaded, mints a
    presigned-style URL) so we can show clip bytes moving OFF the worker.
  - The ACE-Step HTTP server and clip bytes are stubbed.
The download -> upload -> presign logic, the localhost filtering, the serverless guard,
and the token-scoping are all the shipped code, run unmodified.

Run a single scenario:  python docs/demos/us-11.x-runpod-s3-delivery.py <scenario>
where <scenario> in {deliver, filter, serverless, token}.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx

from acemusic.runpod_client import _extract_audio_urls

_HANDLER_PATH = Path(__file__).resolve().parents[2] / "docker" / "handler.py"


def _load_handler():
    spec = importlib.util.spec_from_file_location("acestep_handler", _HANDLER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class InMemoryS3:
    """A minimal stand-in for an S3 client backed by a real dict, so the demo can show
    the exact bytes that landed in the bucket and the URL handed back."""

    def __init__(self):
        self.store: dict[str, bytes] = {}

    def put_object(self, *, Bucket, Key, Body, ContentType):
        self.store[f"{Bucket}/{Key}"] = Body

    def generate_presigned_url(self, op, *, Params, ExpiresIn):
        # Illustrative placeholder, not a real AWS presigned URL (no signature params).
        return f"https://{Params['Bucket']}.s3.example.test/{Params['Key']}?demo-presigned&expires={ExpiresIn}"


def _http_resp(json_data=None, content=b""):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json.return_value = json_data or {}
    resp.content = content
    resp.raise_for_status.return_value = None
    return resp


_TWO_CLIPS = '[{"file": "/v1/audio?path=track-a.wav"}, {"file": "/v1/audio?path=track-b.wav"}]'


def _run_handler(handler_mod, s3_client, clip_bytes=b"FAKE_WAV_AUDIO", result=_TWO_CLIPS):
    """Run the real handler end-to-end with ACE-Step + S3 simulated."""
    boto3_mod = MagicMock()
    boto3_mod.client.return_value = s3_client
    post = MagicMock(
        side_effect=[
            _http_resp({"data": {"task_id": "job-42"}, "code": 200}),
            _http_resp({"data": [{"status": 1, "result": result, "error": None}], "code": 200}),
        ]
    )
    get = MagicMock(return_value=_http_resp(content=clip_bytes))
    with (
        patch.object(handler_mod, "boto3", boto3_mod),
        patch.object(handler_mod, "start_api_server", return_value=True),
        patch.object(handler_mod.httpx, "post", post),
        patch.object(handler_mod.httpx, "get", get),
        patch.object(handler_mod.time, "sleep"),
    ):
        out = handler_mod.handler({"input": {"prompt": "warm analog synthwave, 30s"}})
    return out, get


def scenario_deliver():
    """AC1: a remote generation returns audio the platform can actually download."""
    handler_mod = _load_handler()
    s3 = InMemoryS3()
    with patch.dict("os.environ", {"ACEMUSIC_S3_BUCKET": "ace-clips", "ACEMUSIC_S3_PREFIX": "renders"}):
        out, _ = _run_handler(handler_mod, s3)

    print("Handler output status :", out["status"])
    print("audio_urls returned to the platform:")
    for url in out["audio_urls"]:
        print("  -", url)
    print()
    print("Bytes actually uploaded into S3 (key -> size):")
    for key, body in s3.store.items():
        print(f"  - {key}  ({len(body)} bytes)")
    print()
    localhost_leaks = [u for u in out["audio_urls"] if "localhost" in u]
    print("OUTCOME: clip bytes moved off the worker into S3, presigned URLs returned.")
    print("         worker-local URLs escaping to platform:", len(localhost_leaks))


def scenario_filter():
    """AC2: no worker-local URLs escape — the platform client drops them."""
    payload = {
        "audio_urls": [
            "http://localhost:8001/v1/audio?path=track-a.wav",
            "http://127.0.0.1:8001/v1/audio?path=track-b.wav",
            "https://ace-clips.s3.example.test/renders/runpod/job-42/0.wav?demo-presigned",
        ]
    }
    print("Raw output a stale worker might emit:")
    for url in payload["audio_urls"]:
        print("  -", url)
    print()
    reachable = _extract_audio_urls(payload)
    print("After _extract_audio_urls (platform side):")
    for url in reachable:
        print("  -", url)
    print()
    print("OUTCOME: 2 worker-local URLs dropped, only the platform-reachable S3 URL survives.")


def scenario_serverless():
    """A serverless worker with no bucket fails loudly instead of returning dead URLs."""
    handler_mod = _load_handler()
    with patch.dict("os.environ", {"RUNPOD_ENDPOINT_ID": "ep-abc"}, clear=False):
        import os

        os.environ.pop("ACEMUSIC_S3_BUCKET", None)
        out, _ = _run_handler(handler_mod, InMemoryS3())
    print("Serverless worker (RUNPOD_ENDPOINT_ID set), ACEMUSIC_S3_BUCKET unset:")
    print("  status :", out["status"])
    print("  error  :", out["error"])
    print("  audio_urls:", out["audio_urls"])
    print()
    print("OUTCOME: misconfiguration surfaces as a clean failure, not a silent 'no audio'.")


def scenario_token():
    """The ACE-Step token is never sent to an external/spoofed result host."""
    handler_mod = _load_handler()
    spoof = "http://localhost@attacker.example/x.wav"
    with patch.dict("os.environ", {"ACEMUSIC_S3_BUCKET": "ace-clips", "ACESTEP_API_KEY": "demo-token"}):
        out, get = _run_handler(handler_mod, InMemoryS3(), result=f'[{{"file": "{spoof}"}}]')
    fetched_url = get.call_args.args[0]
    sent_headers = get.call_args.kwargs["headers"]
    print("ACE-Step returned an absolute, userinfo-spoofed URL:")
    print("  ", fetched_url)
    print("  (httpx would connect to host: attacker.example, NOT the worker)")
    print()
    print("Headers the handler attached to that download:", sent_headers)
    print()
    leaked = "Authorization" in sent_headers
    print("OUTCOME: ACESTEP_API_KEY leaked to external host:", leaked)


if __name__ == "__main__":
    {
        "deliver": scenario_deliver,
        "filter": scenario_filter,
        "serverless": scenario_serverless,
        "token": scenario_token,
    }[sys.argv[1]]()
