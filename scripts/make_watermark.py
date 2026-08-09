"""Render the free-tier video watermark bug (#401).

Run once, offline, to regenerate ``src/acemusic/assets/watermark.png``; the
rendered PNG is committed and the worker only composites it. Keeping the
generation here rather than in the request path means the API needs neither a
font file nor Pillow's text stack at render time, and the mark is byte-identical
on every deployment.

The bug is the app icon (the glyph from ``web/app/favicon.ico``) beside the word
"Cadenza" set in Nunito Sans Bold — the web app's typeface — both white with a
soft dark shadow so the mark stays legible over a bright or a dark frame.

    uv run python scripts/make_watermark.py

Needs network access the first time (it fetches the font from Google Fonts) and
is not part of the test suite or the build.
"""

from __future__ import annotations

import hashlib
import io
import sys
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFilter, ImageFont

REPO_ROOT = Path(__file__).resolve().parent.parent
FAVICON = REPO_ROOT / "web" / "app" / "favicon.ico"
OUTPUT = REPO_ROOT / "src" / "acemusic" / "assets" / "watermark.png"

# Nunito Sans Bold — the same family web/app/layout.tsx loads via next/font/google.
FONT_URL = (
    "https://fonts.gstatic.com/s/nunitosans/v19/"
    "pe1mMImSLYBIv1o4X1M8ce2xCx3yop4tQpF_MeTm0lfGWVpNn64CL7U8upHZIbMV51Q42ptCp5F5bxqqtQ1yiU4GMS5ntA.ttf"
)
FONT_CACHE = REPO_ROOT / ".cache" / "NunitoSans-Bold.ttf"
# Pinned so "the mark is byte-identical on every deployment" stays true even if
# Google re-cuts the face behind that URL: a silently different font would
# regenerate a silently different watermark.
FONT_SHA256 = "ec2336c2beb651fb7f9fb968ef4e5b69e91af624c240331a239d3aefd6e41ef0"

WORDMARK = "Cadenza"
# Rendered at 4x the 1080p display size so the worker's downscale stays crisp at 4k.
ICON_PX = 128
FONT_PX = 104
GAP_PX = 36
PAD_PX = 24
SHADOW_BLUR = 8
SHADOW_ALPHA = 150


def load_font() -> ImageFont.FreeTypeFont:
    """Nunito Sans Bold, downloaded once into the gitignored .cache/ and hash-checked."""
    if not FONT_CACHE.exists():
        FONT_CACHE.parent.mkdir(parents=True, exist_ok=True)
        FONT_CACHE.write_bytes(httpx.get(FONT_URL, timeout=30.0, follow_redirects=True).raise_for_status().content)
    digest = hashlib.sha256(FONT_CACHE.read_bytes()).hexdigest()
    if digest != FONT_SHA256:
        raise SystemExit(f"Font hash mismatch for {FONT_CACHE}\n  expected {FONT_SHA256}\n  got      {digest}")
    return ImageFont.truetype(str(FONT_CACHE), FONT_PX)


def load_icon() -> Image.Image:
    """The favicon's glyph as a white-on-transparent icon of ``ICON_PX`` square.

    The favicon is a white mark on a black plate. A watermark must not paint a
    black box over the video, so the plate is dropped: luminance becomes alpha,
    which keeps the glyph's antialiased edges instead of hard-keying them. The
    result is cropped to the glyph before scaling, so the mark is sized by the
    triangle itself rather than by the favicon's generous padding.
    """
    alpha = Image.open(FAVICON).convert("L")
    icon = Image.new("RGBA", alpha.size, (255, 255, 255, 0))
    icon.putalpha(alpha)
    return icon.crop(icon.getbbox()).resize((ICON_PX, ICON_PX), Image.LANCZOS)


def build() -> Image.Image:
    """Compose icon + wordmark on transparent, with a soft shadow underneath."""
    font = load_font()
    icon = load_icon()

    text_box = font.getbbox(WORDMARK)
    text_w, text_h = text_box[2] - text_box[0], text_box[3] - text_box[1]
    width = PAD_PX * 2 + ICON_PX + GAP_PX + text_w
    height = PAD_PX * 2 + max(ICON_PX, text_h)

    mark = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    mark.alpha_composite(icon, (PAD_PX, (height - ICON_PX) // 2))
    ImageDraw.Draw(mark).text(
        (PAD_PX + ICON_PX + GAP_PX - text_box[0], (height - text_h) // 2 - text_box[1]),
        WORDMARK,
        font=font,
        fill=(255, 255, 255, 255),
    )

    # Shadow: the mark's own alpha, blurred and darkened, composited behind it.
    shadow = Image.new("RGBA", mark.size, (0, 0, 0, 0))
    shadow.putalpha(mark.getchannel("A").point(lambda a: a * SHADOW_ALPHA // 255))
    shadow = shadow.filter(ImageFilter.GaussianBlur(SHADOW_BLUR))
    shadow.alpha_composite(mark)
    return shadow


def main() -> int:
    if not FAVICON.exists():
        print(f"missing app icon: {FAVICON}", file=sys.stderr)
        return 1
    mark = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO()
    mark.save(buffer, format="PNG", optimize=True)
    OUTPUT.write_bytes(buffer.getvalue())
    print(f"wrote {OUTPUT} ({mark.width}x{mark.height}, {OUTPUT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
