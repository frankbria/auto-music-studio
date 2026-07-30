"""Stand-in for an ACE-Step server, for plugin demos.

Implements the endpoints the VST3 plugin actually uses, with the same envelope the
real server sends (see ``src/acemusic/client.py``):

- ``GET  /v1/stats``     availability probe + model list          (US-23.2)
- ``POST /release_task`` submit a generation, returns a task id   (US-23.3)
- ``POST /query_result`` poll a task; status 0/1/2                (US-23.3)
- ``GET  /v1/audio``     download a generated clip                (US-23.3)

Generation is faked: a task reports "running" for ``--generate-seconds`` and then
returns two clips of real (synthesised) WAV audio, so the plugin's download and
file handling are exercised for real rather than stubbed out.
"""

import argparse
import json
import math
import struct
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

STATS = {
    "data": {
        "models": [
            {"name": "ace-step-1.5"},
            {"name": "ace-step-1.5-turbo"},
            {"name": "ace-step-mini"},
        ],
        "jobs": {"running": 0, "queued": 0},
        "avg_job_time": 12.4,
    },
    "code": 200,
    "error": None,
}

# task_id -> {"submitted_at": float, "payload": dict}
TASKS: dict[str, dict] = {}
TASKS_LOCK = threading.Lock()

DEFAULT_GENERATE_SECONDS = 6.0
GENERATE_SECONDS = DEFAULT_GENERATE_SECONDS


def make_wav(seconds: float = 2.0, freq: float = 220.0, rate: int = 44100) -> bytes:
    """A real mono 16-bit WAV, so the plugin downloads something it can actually open."""
    frames = int(seconds * rate)
    samples = b"".join(struct.pack("<h", int(12000 * math.sin(2 * math.pi * freq * n / rate))) for n in range(frames))
    header = b"RIFF" + struct.pack("<I", 36 + len(samples)) + b"WAVE"
    header += b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
    header += b"data" + struct.pack("<I", len(samples))
    return header + samples


class Handler(BaseHTTPRequestHandler):
    def _send(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _log(self, extra: str = "") -> None:
        # Report only whether a key was sent, never its value — this script can be
        # pointed at a real config.
        auth = "present" if self.headers.get("Authorization") else "absent"
        print(f"{self.command} {self.path} auth={auth} {extra}".rstrip(), flush=True)

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler's naming
        self._log()

        if self.path == "/v1/stats":
            self._send(STATS)
            return

        if self.path.startswith("/v1/audio"):
            audio = make_wav(freq=220.0 if "clip-1" in self.path else 330.0)
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(audio)))
            self.end_headers()
            self.wfile.write(audio)
            return

        self.send_error(404)

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {}

        if self.path == "/release_task":
            task_id = f"task-{len(TASKS) + 1}"

            with TASKS_LOCK:
                TASKS[task_id] = {"submitted_at": time.monotonic(), "payload": payload}

            # The whole point of the demo: show exactly what the plugin sent.
            self._log(f"-> {task_id}")
            print("  payload: " + json.dumps(payload, sort_keys=True), flush=True)
            self._send({"data": {"task_id": task_id}, "code": 200, "error": None})
            return

        if self.path == "/query_result":
            task_id = (payload.get("task_id_list") or [None])[0]

            with TASKS_LOCK:
                task = TASKS.get(task_id)

            if task is None:
                self._send({"data": [], "code": 200, "error": None})
                return

            elapsed = time.monotonic() - task["submitted_at"]

            if elapsed < GENERATE_SECONDS:
                self._log(f"{task_id} running {elapsed:.1f}s")
                self._send({"data": [{"status": 0}], "code": 200, "error": None})
                return

            # `result` is a JSON *string* in the real API, not a nested array.
            clips = json.dumps(
                [
                    {"file": f"/v1/audio?path={task_id}-clip-1.wav"},
                    {"file": f"/v1/audio?path={task_id}-clip-2.wav"},
                ]
            )
            self._log(f"{task_id} complete")
            self._send({"data": [{"status": 1, "result": clips}], "code": 200, "error": None})
            return

        self.send_error(404)

    def log_message(self, *args):
        pass


def main() -> None:
    global GENERATE_SECONDS

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", nargs="?", type=int, default=8001)
    parser.add_argument(
        "--generate-seconds",
        type=float,
        default=DEFAULT_GENERATE_SECONDS,
        help="how long a task reports as running before returning clips",
    )
    args = parser.parse_args()
    GENERATE_SECONDS = args.generate_seconds

    print(
        f"stub ACE-Step listening on :{args.port} " f"(generation takes {GENERATE_SECONDS:.0f}s)",
        flush=True,
    )
    HTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    sys.exit(main())
