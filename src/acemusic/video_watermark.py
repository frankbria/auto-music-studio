"""Free-tier video watermarking (#401).

US-26.2 sells the free tier as "720p watermarked video". The resolution half is
an authorization check in the router; this is the other half — a corner bug (the
app icon plus the wordmark "Cadenza") composited onto the rendered MP4 *after*
the provider returns it, so it does not depend on a provider feature and applies
identically to original renders and to edits.

The mark is a committed PNG (:mod:`scripts.make_watermark` regenerates it), so
nothing here needs a font or a text renderer. ffmpeg scales it relative to the
frame height and overlays it in the bottom-right corner, which keeps the bug the
same apparent size at 720p, 1080p and 4k.

Every failure raises :class:`WatermarkError`. That is deliberate: the caller
fails the job on it, because a watermarking step that quietly falls through to
the unmarked bytes would hand the free tier the Pro deliverable.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

WATERMARK_PATH = Path(__file__).parent / "assets" / "watermark.png"

#: Bug height as a fraction of the frame height, and its inset from both edges.
#: Sized by *height* so a 16:9, 9:16 and 1:1 render all get the same apparent mark.
_MARK_HEIGHT_RATIO = 0.06
_MARGIN_RATIO = 0.025

#: A visible mark must survive re-encoding, so the video stream is re-encoded
#: (the audio is copied through untouched — the mark is a picture, not a sound).
_VIDEO_CODEC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]

# Generous: a 4k, minutes-long render is re-encoded here. Still bounded, so a
# wedged ffmpeg fails the job instead of pinning a worker thread forever.
_TIMEOUT_S = 1800
_PROBE_TIMEOUT_S = 60


class WatermarkError(Exception):
    """Raised when the watermark could not be applied to a video."""


def _run(command: list[str], *, timeout: int, what: str) -> subprocess.CompletedProcess[bytes]:
    """Run one ffmpeg-family command, turning every failure into a WatermarkError."""
    try:
        result = subprocess.run(command, capture_output=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise WatermarkError(f"{command[0]!r} is not installed or not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise WatermarkError(f"{what} timed out after {timeout}s") from exc
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip().splitlines()
        raise WatermarkError(f"{what} failed: {detail[-1] if detail else 'no output'}")
    return result


def _frame_size(source: Path, ffprobe: str) -> tuple[int, int]:
    """The video stream's ``(width, height)`` in pixels.

    Probed rather than derived from an ffmpeg filter expression: the geometry is
    then plain integer arithmetic here, testable and identical across ffmpeg
    versions (``scale2ref``'s reference-size variables are not).
    """
    result = _run(
        [
            ffprobe, "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(source),
        ],  # fmt: skip
        timeout=_PROBE_TIMEOUT_S,
        what="Probing the video",
    )
    try:
        width, height = (int(part) for part in result.stdout.decode().strip().splitlines()[0].split("x"))
    except (IndexError, ValueError) as exc:
        raise WatermarkError("Could not read the video's dimensions") from exc
    if width <= 0 or height <= 0:
        raise WatermarkError(f"Video reports a nonsensical size ({width}x{height})")
    return width, height


def _geometry(width: int, height: int) -> tuple[int, int, int, int]:
    """``(mark_w, mark_h, x, y)`` for the bug in the bottom-right corner.

    Sized and inset by *height*, so a 16:9, 9:16 and 1:1 render at the same
    resolution all get the same apparent mark, and 720p/1080p/4k all get the
    same fraction of the frame.
    """
    from PIL import Image

    with Image.open(WATERMARK_PATH) as mark:
        native_w, native_h = mark.size
    mark_h = max(1, round(height * _MARK_HEIGHT_RATIO))
    mark_w = max(1, round(mark_h * native_w / native_h))
    margin = round(height * _MARGIN_RATIO)
    return mark_w, mark_h, max(0, width - mark_w - margin), max(0, height - mark_h - margin)


def apply_watermark(video: bytes, *, ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe") -> bytes:
    """Return ``video`` with the Cadenza bug composited into its bottom-right corner.

    Blocking (subprocess + disk); call it from a worker thread. Raises
    :class:`WatermarkError` if ffmpeg is absent, fails, times out, or produces
    nothing — never returns the input unmarked.
    """
    if not WATERMARK_PATH.is_file():
        raise WatermarkError(f"Watermark asset is missing: {WATERMARK_PATH}")

    with tempfile.TemporaryDirectory(prefix="watermark-") as tmp:
        source, marked = Path(tmp) / "in.mp4", Path(tmp) / "out.mp4"
        source.write_bytes(video)
        mark_w, mark_h, x, y = _geometry(*_frame_size(source, ffprobe))
        _run(
            [
                ffmpeg, "-y", "-loglevel", "error", "-nostdin",
                "-i", str(source), "-i", str(WATERMARK_PATH),
                "-filter_complex", f"[1:v]scale={mark_w}:{mark_h}[mark];[0:v][mark]overlay={x}:{y}",
                *_VIDEO_CODEC, "-c:a", "copy", "-movflags", "+faststart",
                str(marked),
            ],  # fmt: skip
            timeout=_TIMEOUT_S,
            what="Watermarking",
        )
        data = marked.read_bytes() if marked.is_file() else b""
        if not data:
            raise WatermarkError("Watermarking produced an empty video")
        return data
