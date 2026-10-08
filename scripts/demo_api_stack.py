"""Live API stack for Showboat demos: a throwaway Mongo database, a seeded Pro user, and a SoundCloud stand-in.

Every API demo used to rebuild this by hand (#538, #555). One process runs all of it, so one ``kill`` stops it::

    setsid uv run python scripts/demo_api_stack.py --dir /tmp/demo-555 --db acemusic_demo_555 --clips 4 &
    . /tmp/demo-555/env.sh       # TOKEN, USER_ID, WORKSPACE_ID, CLIP_1..N, plus the helpers below
    api POST /releases '{"clip_id": "'$CLIP_1'", ...}'   # prints "HTTP <code>" and the body
    M 'db.clips.findOne()'       # mongosh against the demo database
    soundcloud_uploads           # how many tracks reached the stand-in
    kill $(cat /tmp/demo-555/pid)

The script writes its own pid: ``$!`` names ``setsid`` or ``uv``, and killing either leaves the server up.

The database is dropped and re-seeded on every start, so only ``acemusic_demo_*`` names on the local mongod
are accepted. ``--dir`` must sit outside the repo: ``env.sh`` holds a live JWT. The seeded user is a Pro
musician with 50 credits, a workspace, ``--clips`` clips with real WAV audio in local storage, and a linked
SoundCloud account. SoundCloud calls go to a local stand-in on ``--port + 1`` that answers ``POST /tracks``
and ``PUT /tracks/{id}`` and logs one line per request to ``$DIR/soundcloud.log``.
"""

import argparse
import asyncio
import io
import itertools
import json
import os
import secrets
import shlex
import socket
import sys
import threading
import wave
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MONGO_URL = "mongodb://localhost:27017"


def soundcloud_stand_in(port: int, log: Path) -> ThreadingHTTPServer:
    track_ids = itertools.count(4242)

    class Handler(BaseHTTPRequestHandler):
        def _answer(self, status: int, body: dict) -> None:
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            with log.open("a") as f:
                f.write(f"{self.command} {self.path}\n")
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self) -> None:
            # A fresh id per upload, as SoundCloud gives, so a demo can tell two clips' tracks apart.
            self._answer(201, {"id": next(track_ids), "permalink_url": "https://soundcloud.example/demo"})

        def do_PUT(self) -> None:
            self._answer(200, {})

        def log_message(self, *_args) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def silent_wav() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\0\0" * 8000)
    return buffer.getvalue()


async def seed(settings, clips: int) -> dict[str, str]:
    from beanie import PydanticObjectId
    from pymongo import AsyncMongoClient

    from acemusic.api.auth.tokens import create_access_token
    from acemusic.api.database import close_db, init_db
    from acemusic.api.models import Clip, SoundCloudConnection, User, Workspace
    from acemusic.api.models.common import utcnow
    from acemusic.api.services import users as user_service
    from acemusic.api.services.tiers import PRO
    from acemusic.storage import get_storage_backend

    client = AsyncMongoClient(MONGO_URL)
    await client.drop_database(settings.mongodb_db_name)
    await client.close()
    await init_db(settings)
    user = await user_service.get_or_create_user(
        email="musician@example.com", provider="google", oauth_id="g-demo-musician", name="Demo Musician"
    )
    await user.set({User.subscription_tier: PRO, User.credits_balance: 50.0})
    workspace = Workspace(name="Demo", user_id=user.id)
    await workspace.insert()
    ids = {"USER_ID": str(user.id), "WORKSPACE_ID": str(workspace.id)}
    for n in range(1, clips + 1):
        clip_id = PydanticObjectId()
        path = f"{user.id}/{workspace.id}/clips/{clip_id}.wav"
        get_storage_backend().upload(path, silent_wav())
        await Clip(
            id=clip_id,
            user_id=user.id,
            workspace_id=workspace.id,
            file_path=path,
            format="wav",
            duration=1.0,
            title=f"Demo clip {n}",
        ).insert()
        ids[f"CLIP_{n}"] = str(clip_id)
    await SoundCloudConnection(
        user_id=user.id,
        soundcloud_user_id="sc-demo",
        soundcloud_username="demo",
        access_token="demo-access",
        refresh_token="demo-refresh",
        token_expires_at=utcnow() + timedelta(days=1),
    ).insert()
    ids["TOKEN"] = create_access_token(user_id=str(user.id), email=user.email, subscription_tier=PRO, settings=settings)
    await close_db()
    return ids


def write_env(directory: Path, port: int, db: str, ids: dict[str, str]) -> None:
    exports = {"DEMO_DIR": str(directory), "DEMO_API": f"http://127.0.0.1:{port}/api/v1", "DEMO_DB": db, **ids}
    lines = [f"export {key}={shlex.quote(value)}" for key, value in exports.items()]
    lines += [
        'api() { local code; code=$(curl -s -o "$DEMO_DIR/last_body.json" -w \'%{http_code}\' -X "$1" '
        '"$DEMO_API$2" -H "Authorization: Bearer $TOKEN" -H \'Content-Type: application/json\' ${3:+-d "$3"}); '
        'echo "HTTP $code"; cat "$DEMO_DIR/last_body.json"; echo; }',
        'M() { mongosh --quiet "$DEMO_DB" --eval "$1"; }',
        'soundcloud_uploads() { echo "uploads received by SoundCloud stand-in: '
        '$(grep -c \'^POST /tracks\' "$DEMO_DIR/soundcloud.log")"; }',
    ]
    (directory / "env.sh").write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", required=True, type=Path, help="scratch directory outside the repo")
    parser.add_argument("--db", required=True, help="database name; must start with acemusic_demo_")
    parser.add_argument("--port", type=int, default=8755, help="API port; the SoundCloud stand-in uses port + 1")
    parser.add_argument("--clips", type=int, default=0, help="clips with stored audio to seed")
    args = parser.parse_args()

    if not args.db.startswith("acemusic_demo_"):
        sys.exit("--db must start with acemusic_demo_: the database is dropped on every start")
    directory = args.dir.resolve()
    if directory.is_relative_to(REPO):
        sys.exit("--dir must be outside the repo: env.sh holds a live JWT")
    # Before any write, so a stack that is still running keeps its pid, log and database.
    pid_file = directory / "pid"
    if pid_file.exists() and running(int(pid_file.read_text())):
        sys.exit(f"a stack from this --dir is still running; stop it with kill $(cat {pid_file}) first")
    for port in (args.port, args.port + 1):
        with socket.socket() as probe:
            # As the servers do, so a stack stopped seconds ago doesn't read as running.
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                sys.exit(f"port {port} is in use")
    directory.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(os.getpid()))

    # Before any acemusic import: settings are read at import time, and the repo .env points at Atlas.
    os.environ.update(
        ACEMUSIC_API_MONGODB_URL=MONGO_URL,
        ACEMUSIC_API_MONGODB_DB_NAME=args.db,
        ACEMUSIC_API_JWT_SECRET_KEY=secrets.token_urlsafe(48),
        # A demo and a later `showboat verify` outlive the default 15-minute token.
        ACEMUSIC_API_ACCESS_TOKEN_EXPIRE_MINUTES="1440",
        ACEMUSIC_API_JOB_PROCESSOR_ENABLED="false",
        ACEMUSIC_STORAGE_BACKEND="local",
        ACEMUSIC_STORAGE_LOCAL_ROOT=str(directory / "storage"),
    )
    import uvicorn

    from acemusic.api.main import create_app
    from acemusic.api.services import soundcloud
    from acemusic.api.settings import ApiSettings

    log = directory / "soundcloud.log"
    log.write_text("")
    soundcloud_stand_in(args.port + 1, log)
    soundcloud.SOUNDCLOUD_UPLOAD_URL = f"http://127.0.0.1:{args.port + 1}/tracks"

    settings = ApiSettings()
    write_env(directory, args.port, args.db, asyncio.run(seed(settings, args.clips)))
    print(f"Demo API on http://127.0.0.1:{args.port}; source {directory / 'env.sh'}", flush=True)
    uvicorn.run(create_app(settings), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
