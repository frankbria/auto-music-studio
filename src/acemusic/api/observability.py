"""Structured logs with request ids, and error tracking (US-28.5, #342).

Every log line is one JSON object: ``ts``, ``level``, ``logger``, ``message``, the ``request_id`` and ``user_id`` of
the request it belongs to (when it belongs to one), and ``exc`` for an exception. The request id comes from an
incoming ``X-Request-ID`` (when it looks like one) or is generated, and goes back on the response, so a user's error
reference, the access line and the traceback can be joined. Uvicorn's own access log can't see the request id, so
this module writes the access line and the image runs uvicorn with ``--no-access-log``.

Sentry is initialised only when ``ACEMUSIC_API_SENTRY_DSN`` is set; each event is tagged with the request id.
"""

import json
import logging
import os
import re
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone

import sentry_sdk
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .settings import ApiSettings

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)

_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_access = logging.getLogger("acemusic.access")


_base_factory = logging.getLogRecordFactory()


def _stamped_record(*args, **kwargs) -> logging.LogRecord:
    """Stamp the request and user ids on each record as it is made: a handler may format it later, elsewhere."""
    record = _base_factory(*args, **kwargs)
    record.request_id = request_id_var.get()
    record.user_id = user_id_var.get()
    return record


logging.setLogRecordFactory(_stamped_record)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("request_id", "user_id"):
            value = getattr(record, key, None)
            if value:
                entry[key] = value
        entry.update(getattr(record, "fields", {}))
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def configure_logging(settings: ApiSettings) -> None:
    """Send the app's and uvicorn's logs through one JSON handler on stderr, unless plain text was asked for."""
    if settings.log_format != "json":
        return
    root = logging.getLogger()
    # Added beside any handler already there (a test runner's capture), and only once per process.
    if not any(isinstance(h.formatter, JsonFormatter) for h in root.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        root.addHandler(handler)
    root.setLevel(settings.log_level)
    # The app's and uvicorn's loggers write through the root's JSON handler, not handlers of their own. uvicorn's
    # access logger is left alone: `--no-access-log` turns it off, and the app writes its own access line.
    for name in ("acemusic", "uvicorn", "uvicorn.error"):
        named = logging.getLogger(name)
        named.handlers = [h for h in named.handlers if isinstance(h.formatter, JsonFormatter)]
        named.propagate = True


def configure_error_tracking(settings: ApiSettings) -> None:
    """Report unhandled exceptions to Sentry when a DSN is configured; nothing otherwise."""
    if not settings.sentry_dsn:
        return

    def tag_request(event: dict, _hint: dict) -> dict:
        request_id = request_id_var.get()
        if request_id:
            event.setdefault("tags", {})["request_id"] = request_id
        return event

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.sentry_environment,
        release=os.environ.get("ACEMUSIC_BUILD_SHA") or None,
        traces_sample_rate=0.0,
        send_default_pii=False,
        before_send=tag_request,
    )


class RequestIdMiddleware:
    """Give each request an id, echo it as ``X-Request-ID``, and write one access line when it finishes."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = dict(scope["headers"]).get(b"x-request-id", b"").decode("latin-1")
        request_id = incoming if _SAFE_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        # On Sentry's per-request scope too: an unhandled error is captured after this middleware's context is gone.
        sentry_sdk.set_tag("request_id", request_id)
        # Kept on the scope too: an unhandled error is answered outside this middleware, after its context is gone.
        scope.setdefault("state", {})["request_id"] = request_id
        request_token = request_id_var.set(request_id)
        user_token = user_id_var.set(None)
        started = time.perf_counter()
        status = 500

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message["headers"] = [*message.get("headers", []), (b"x-request-id", request_id.encode())]
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            _access.info(
                "%s %s %s",
                scope["method"],
                scope["path"],
                status,
                extra={
                    "fields": {
                        "method": scope["method"],
                        "path": scope["path"],
                        "status": status,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    }
                },
            )
            user_id_var.reset(user_token)
            request_id_var.reset(request_token)
