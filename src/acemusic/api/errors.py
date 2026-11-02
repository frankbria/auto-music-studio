"""One error shape for every API response (#339): ``{"detail": ..., "code": ...}``.

``detail`` keeps what each endpoint already says, which every client reads; ``code`` is a stable, machine-readable
name for the kind of failure. An unhandled exception becomes a generic 500 that names a reference to quote to
support, and its traceback goes to the log only, never the response.
"""

import logging
import secrets

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

_CODES: dict[int, str] = {
    400: "bad_request",
    401: "not_authenticated",
    402: "payment_required",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "too_large",
    422: "invalid_request",
    429: "rate_limited",
    502: "upstream_error",
    503: "unavailable",
    504: "upstream_timeout",
}


def code_for(status_code: int) -> str:
    """The ``code`` for a status with no more specific name."""
    return _CODES.get(status_code, "server_error" if status_code >= 500 else "error")


def error_response(status_code: int, detail: object, code: str, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": detail, "code": code}, headers=headers)


def install(app: FastAPI) -> None:
    """Register the shared handlers; domain handlers in ``main`` name their own codes."""

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return error_response(exc.status_code, exc.detail, code_for(exc.status_code), exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _invalid_request(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(422, jsonable_encoder(exc.errors()), "invalid_request")

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, _exc: Exception) -> JSONResponse:
        # Starlette answers this outside every middleware, so the request id comes from the scope (#342).
        reference = getattr(request.state, "request_id", None) or secrets.token_hex(4)
        logger.exception(
            "Unhandled error %s on %s %s",
            reference,
            request.method,
            request.url.path,
            extra={"fields": {"request_id": reference}},
        )
        return error_response(
            500,
            f"Something went wrong on our side. Try again, and if it keeps happening, contact support "
            f"and quote reference {reference}.",
            "internal_error",
            {"X-Request-ID": reference},
        )
