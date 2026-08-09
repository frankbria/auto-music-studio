"""Tests for the free-tier video watermark (#401).

Two layers. The first runs anywhere: the error contract — a missing or failing
ffmpeg, or input that is not a video, must raise :class:`WatermarkError` rather
than hand back unmarked bytes, because the caller turns that into a failed job.
The second actually composites (``requires_ffmpeg``) and inspects the resulting
pixels; CI has no ffmpeg, so it skips there and runs locally and in the demo.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from acemusic.video_watermark import WATERMARK_PATH, WatermarkError, _mark_size, apply_watermark

requires_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")

# A flat mid-grey clip: any pixel that changes after compositing changed because
# of the mark, not because of the source's own detail.
_SOURCE_COLOUR = "gray"


def _make_video(tmp_path: Path, *, width: int = 1280, height: int = 720) -> bytes:
    """Encode a 1s silent test clip of the given size and return its bytes."""
    out = tmp_path / f"src-{width}x{height}.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c={_SOURCE_COLOUR}:s={width}x{height}:r=15:d=1",
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            str(out),
        ],
        check=True,
    )  # fmt: skip
    return out.read_bytes()


def _frame(tmp_path: Path, video: bytes, name: str):
    """Decode the clip's first frame to a PIL image."""
    from PIL import Image

    src, png = tmp_path / f"{name}.mp4", tmp_path / f"{name}.png"
    src.write_bytes(video)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-frames:v", "1", str(png)],
        check=True,
    )
    return Image.open(png).convert("RGB")


class TestAsset:
    def test_watermark_asset_is_committed(self) -> None:
        assert WATERMARK_PATH.is_file() and WATERMARK_PATH.stat().st_size > 0

    def test_watermark_asset_has_transparency(self) -> None:
        """A mark with no alpha would paint an opaque plate over the video."""
        from PIL import Image

        mark = Image.open(WATERMARK_PATH)
        assert mark.mode == "RGBA"
        assert mark.getchannel("A").getextrema()[0] == 0


class TestMarkSize:
    """Pure arithmetic — runs in CI, where there is no ffmpeg."""

    def test_mark_fits_inside_the_frame(self) -> None:
        mark_w, mark_h = _mark_size(720)
        assert 0 < mark_w < 1280 and 0 < mark_h < 720

    def test_same_fraction_of_the_frame_at_every_resolution(self) -> None:
        ratios = [_mark_size(h)[1] / h for h in (720, 1080, 2160)]
        assert max(ratios) - min(ratios) < 0.005

    def test_aspect_ratio_preserved(self) -> None:
        from PIL import Image

        with Image.open(WATERMARK_PATH) as mark:
            native = mark.width / mark.height
        mark_w, mark_h = _mark_size(1080)
        assert abs(mark_w / mark_h - native) < 0.02

    def test_sized_by_height_not_width(self) -> None:
        """A 9:16 render gets the same bug as a 16:9 one of the same height."""
        assert _mark_size(1920) == _mark_size(1920)
        assert _mark_size(2160)[1] > _mark_size(1080)[1]

    def test_tiny_frame_still_produces_a_visible_mark(self) -> None:
        mark_w, mark_h = _mark_size(4)
        assert mark_w >= 1 and mark_h >= 1


class TestFailureIsLoud:
    """#401: watermarking must never silently produce an unmarked video."""

    def test_missing_ffprobe_raises(self, tmp_path) -> None:
        with pytest.raises(WatermarkError, match="not installed"):
            apply_watermark(b"not-really-a-video", ffprobe=str(tmp_path / "no-such-ffprobe"))

    @requires_ffmpeg
    def test_missing_ffmpeg_raises(self, tmp_path) -> None:
        with pytest.raises(WatermarkError, match="not installed"):
            apply_watermark(_make_video(tmp_path), ffmpeg=str(tmp_path / "no-such-ffmpeg"))

    @requires_ffmpeg
    def test_undecodable_input_raises(self) -> None:
        with pytest.raises(WatermarkError, match="failed"):
            apply_watermark(b"not-really-a-video")

    @requires_ffmpeg
    def test_empty_input_raises(self) -> None:
        with pytest.raises(WatermarkError):
            apply_watermark(b"")

    @requires_ffmpeg
    def test_audio_only_input_raises(self, tmp_path) -> None:
        """A file with no video stream has no frame to mark — fail, don't pass it through."""
        audio = tmp_path / "audio.m4a"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
             "-i", "anullsrc=r=44100:cl=stereo", "-t", "1", "-c:a", "aac", str(audio)],
            check=True,
        )  # fmt: skip
        with pytest.raises(WatermarkError, match="dimensions"):
            apply_watermark(audio.read_bytes())


@requires_ffmpeg
class TestComposite:
    def test_output_is_a_playable_video(self, tmp_path) -> None:
        marked = apply_watermark(_make_video(tmp_path))
        assert marked and marked != _make_video(tmp_path)
        assert _frame(tmp_path, marked, "marked").size == (1280, 720)

    def test_mark_lands_in_the_corner(self, tmp_path) -> None:
        """The bug is in the bottom-right; the rest of the frame is untouched."""
        source = _make_video(tmp_path)
        before = _frame(tmp_path, source, "before")
        after = _frame(tmp_path, apply_watermark(source), "after")

        width, height = before.size
        corner = (int(width * 0.6), int(height * 0.8), width, height)
        assert after.crop(corner) != before.crop(corner), "no mark in the bottom-right corner"
        # Top-left quadrant: the video itself must survive unmarked.
        elsewhere = (0, 0, width // 2, height // 2)
        assert after.crop(elsewhere).getextrema() == before.crop(elsewhere).getextrema()

    def test_portrait_render_is_marked_on_screen(self, tmp_path) -> None:
        """9:16 is a supported aspect ratio; the bug must not fall off its edge."""
        source = _make_video(tmp_path, width=720, height=1280)
        before = _frame(tmp_path, source, "portrait-before")
        after = _frame(tmp_path, apply_watermark(source), "portrait-after")

        from PIL import ImageChops

        changed = ImageChops.difference(before, after).getbbox()
        assert changed is not None, "no mark anywhere in the frame"
        left, top, right, bottom = changed
        assert right <= 720 and bottom <= 1280
        assert left > 720 // 2 and top > 1280 // 2  # bottom-right corner

    def test_mark_scales_with_the_frame(self, tmp_path) -> None:
        """A 4k render gets a proportionally sized bug, not a 720p-sized speck."""
        marks = {}
        for width, height, name in ((1280, 720, "hd"), (3840, 2160, "uhd")):
            source = _make_video(tmp_path, width=width, height=height)
            before = _frame(tmp_path, source, f"{name}-before")
            after = _frame(tmp_path, apply_watermark(source), f"{name}-after")
            from PIL import ImageChops

            marks[name] = ImageChops.difference(before, after).getbbox()

        hd, uhd = marks["hd"], marks["uhd"]
        # Same relative height (within a pixel-rounding tolerance), 3x the pixels.
        hd_ratio = (hd[3] - hd[1]) / 720
        uhd_ratio = (uhd[3] - uhd[1]) / 2160
        assert abs(hd_ratio - uhd_ratio) < 0.01
