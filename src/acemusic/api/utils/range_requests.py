"""HTTP Range header parsing for byte-range (206) responses (US-9.3).

Implements the single-range subset of RFC 9110 §14: explicit (``bytes=0-99``),
open-ended (``bytes=100-``), and suffix (``bytes=-100``) ranges. Multipart
ranges and non-``bytes`` units are out of scope — per the RFC a server MAY
ignore the Range header, so those serve the full body with 200.
"""

import re

from fastapi import HTTPException, status

# One range-spec in the bytes unit: "bytes=<start?>-<end?>".
_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)$")


def _unsatisfiable(content_length: int) -> HTTPException:
    # RFC 9110 §15.5.17: a 416 SHOULD carry the selected representation's
    # length so the client can retry with a valid range, and Accept-Ranges so
    # it knows the bytes unit is understood (§14.3).
    return HTTPException(
        status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE,
        detail="Requested range not satisfiable.",
        headers={"Content-Range": f"bytes */{content_length}", "Accept-Ranges": "bytes"},
    )


def parse_range_header(range_header: str, content_length: int) -> tuple[int, int] | None:
    """Parse a ``Range`` header into an inclusive ``(start, end)`` byte pair.

    Returns ``None`` when the header is malformed, uses an unsupported unit,
    or requests multiple ranges — the caller should ignore it and serve the
    full body (RFC 9110 permits ignoring Range entirely). Raises a 416
    :class:`HTTPException` when the header is well-formed but unsatisfiable
    (start beyond the end of the representation, or an empty suffix).
    """
    if content_length <= 0:
        return None

    match = _RANGE_RE.match(range_header.strip())
    if match is None:
        return None
    start_s, end_s = match.groups()

    if not start_s and not end_s:  # "bytes=-"
        return None

    if not start_s:
        # Suffix range: the last N bytes of the representation.
        suffix = int(end_s)
        if suffix == 0:
            raise _unsatisfiable(content_length)
        return max(0, content_length - suffix), content_length - 1

    start = int(start_s)
    if start >= content_length:
        raise _unsatisfiable(content_length)
    end = int(end_s) if end_s else content_length - 1
    if end < start:  # "bytes=5-2" is syntactically invalid — ignore the header
        return None
    return start, min(end, content_length - 1)
