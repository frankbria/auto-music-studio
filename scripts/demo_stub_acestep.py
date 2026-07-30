"""Minimal stand-in for an ACE-Step server: just the /v1/stats probe endpoint."""
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer

PAYLOAD = {
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


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        print(f"{self.command} {self.path} auth={self.headers.get('Authorization')!r}", flush=True)
        if self.path != "/v1/stats":
            self.send_error(404)
            return
        body = json.dumps(PAYLOAD).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8001
    print(f"stub ACE-Step listening on :{port}", flush=True)
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
