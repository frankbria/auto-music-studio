"""HTTP Range header parsing for byte-range (206) responses (US-9.3, US-14.2).

:func:`parse_range_header` implements the single-range subset of RFC 9110 §14:
explicit (``bytes=0-99``), open-ended (``bytes=100-``), and suffix
(``bytes=-100``) ranges, ignoring multipart/non-``bytes`` (serve full 200).

US-14.2 adds :func:`parse_range_header_multi` (comma-separated ranges) and
:func:`build_multipart_ranges_response` (``multipart/byteranges`` per §14.6) for
the streaming endpoint, leaving the proven single-range path above untouched.
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


# One range-spec without the unit prefix: "<start?>-<end?>" (e.g. "0-99", "-100").
_SPEC_RE = re.compile(r"(\d*)-(\d*)$")

# Cap multi-range requests: a public streaming client could otherwise send dozens
# of (overlapping) full-size ranges and force an N×-sized multipart body in memory
# before the per-minute limiter helps. Beyond the cap we ignore Range and serve the
# full body (RFC 9110 §14.2 permits ignoring Range entirely).
MAX_MULTIRANGE_SPECS = 10


def _parse_spec(start_s: str, end_s: str, content_length: int) -> tuple[int, int] | None:
    """Resolve one ``<start>-<end>`` spec to an inclusive pair, mirroring
    :func:`parse_range_header`'s single-spec rules. Returns ``None`` for an
    ignorable spec; raises 416 for a well-formed-but-unsatisfiable one."""
    if not start_s and not end_s:  # "-" alone
        return None
    if not start_s:
        suffix = int(end_s)
        if suffix == 0:
            raise _unsatisfiable(content_length)
        return max(0, content_length - suffix), content_length - 1
    start = int(start_s)
    if start >= content_length:
        raise _unsatisfiable(content_length)
    end = int(end_s) if end_s else content_length - 1
    if end < start:
        return None
    return start, min(end, content_length - 1)


def parse_range_header_multi(range_header: str, content_length: int) -> list[tuple[int, int]] | None:
    """Parse a single- or multi-range ``Range`` header into inclusive pairs.

    Accepts comma-separated specs (``bytes=0-99,200-299``). Returns ``None`` to
    ignore the header (malformed, unsupported unit, or empty — caller serves the
    full body), a one-element list for a single range, or a multi-element list.
    Overlapping ranges are returned as-is (no merging, per RFC). More than
    :data:`MAX_MULTIRANGE_SPECS` ranges are ignored (``None``, serve full body)
    to bound the multipart response size. Raises a 416 :class:`HTTPException`
    only when *every* requested range is unsatisfiable.
    """
    if content_length <= 0:
        return None

    stripped = range_header.strip()
    if not stripped.startswith("bytes="):
        return None

    specs = stripped[len("bytes=") :].split(",")
    if len(specs) > MAX_MULTIRANGE_SPECS:  # too many ranges — ignore Range, serve full body
        return None

    ranges: list[tuple[int, int]] = []
    saw_unsatisfiable = False
    for raw_spec in specs:
        match = _SPEC_RE.fullmatch(raw_spec.strip())
        if match is None:  # any malformed spec invalidates the whole header
            return None
        try:
            pair = _parse_spec(match.group(1), match.group(2), content_length)
        except HTTPException:
            saw_unsatisfiable = True
            continue
        if pair is None:
            return None
        ranges.append(pair)

    if ranges:
        # Bound the multipart body by total bytes too, not just spec count:
        # ``bytes=0-,0-,...`` stays under the count cap yet selects the whole
        # representation N times. If the ranges overlap past the full size,
        # ignore Range and serve the full body once.
        if sum(end - start + 1 for start, end in ranges) > content_length:
            return None
        return ranges
    # No satisfiable ranges: 416 if at least one was explicitly out of bounds,
    # otherwise the header was effectively empty ("bytes=-") — ignore it.
    if saw_unsatisfiable:
        raise _unsatisfiable(content_length)
    return None


def build_multipart_ranges_response(
    content: bytes, ranges: list[tuple[int, int]], content_type: str, boundary: str
) -> tuple[bytes, str]:
    """Assemble a ``multipart/byteranges`` body for ``ranges`` (RFC 9110 §14.6).

    Returns ``(body, full_content_type)`` where ``full_content_type`` is
    ``multipart/byteranges; boundary=<boundary>``. The caller must pass a
    ``boundary`` that does not occur in ``content``.
    """
    total = len(content)
    parts: list[bytes] = []
    for start, end in ranges:
        parts.append(
            (
                f"\r\n--{boundary}\r\n"
                f"Content-Type: {content_type}\r\n"
                f"Content-Range: bytes {start}-{end}/{total}\r\n\r\n"
            ).encode("ascii")
        )
        parts.append(content[start : end + 1])
    parts.append(f"\r\n--{boundary}--\r\n".encode("ascii"))
    return b"".join(parts), f"multipart/byteranges; boundary={boundary}"
