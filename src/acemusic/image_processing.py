"""Cover-art image validation and upscaling helpers (US-13.1).

The artwork feature is the platform's first image path, so these helpers are the
single home for "is this a usable raster image" (format, dimensions, integrity)
and the 1024->3000 distribution upscale. They are transport-agnostic (plain
:class:`ImageValidationError`, never ``HTTPException``) like the audio helpers, so
the router maps the error to a 422 and the worker maps it to a job failure.
"""

from __future__ import annotations

import io

from PIL import Image, UnidentifiedImageError


class ImageValidationError(Exception):
    """An image is corrupt, in an unknown format, or below the required size."""


def validate_image(data: bytes) -> tuple[str, int, int]:
    """Return ``(format, width, height)`` for ``data``; raise if it is not a
    decodable image.

    ``format`` is lower-cased (``"png"``/``"jpeg"``). ``img.load()`` forces a full
    decode so truncated or corrupt bytes fail here rather than later in the worker.
    """
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()  # force decode: truncated/corrupt data raises now, not later
            fmt = (img.format or "").lower()
            width, height = img.size
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ImageValidationError(f"Could not read image: {exc}") from exc
    if not fmt:
        raise ImageValidationError("Image format could not be determined.")
    return fmt, width, height


def ensure_min_resolution(data: bytes, min_size: int) -> None:
    """Raise :class:`ImageValidationError` if either dimension is below ``min_size``.

    The message names the actual and required sizes so the client knows by how
    much an uploaded image falls short.
    """
    _fmt, width, height = validate_image(data)
    if width < min_size or height < min_size:
        raise ImageValidationError(
            f"Image is {width}x{height}; at least {min_size}x{min_size} is required for distribution."
        )


def upscale_image(data: bytes, target_size: int) -> bytes:
    """Resize ``data`` to ``target_size`` x ``target_size`` and return PNG bytes.

    Cover art is square (DALL-E emits 1024x1024); LANCZOS gives the best quality
    for the upscale. Output is always PNG so the stored distribution master is
    lossless regardless of the source format.
    """
    with Image.open(io.BytesIO(data)) as img:
        resized = img.convert("RGB").resize((target_size, target_size), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        resized.save(out, format="PNG")
    return out.getvalue()
