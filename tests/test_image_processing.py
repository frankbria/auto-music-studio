"""Tests for the cover-art image helpers (US-13.1, issue #132).

``validate_image`` / ``ensure_min_resolution`` / ``upscale_image`` back the
artwork upload validation (format, resolution, corruption) and the 1024->3000
distribution upscale. No external services, so these run in CI.
"""

import io

import pytest
from PIL import Image

from acemusic.image_processing import (
    ImageValidationError,
    ensure_min_resolution,
    upscale_image,
    validate_image,
)


def _img_bytes(fmt: str, size: tuple[int, int] = (3000, 3000), color: str = "navy") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format=fmt)
    return buf.getvalue()


class TestValidateImage:
    @pytest.mark.parametrize("fmt,expected", [("PNG", "png"), ("JPEG", "jpeg")])
    def test_returns_format_and_dimensions(self, fmt: str, expected: str) -> None:
        data = _img_bytes(fmt, size=(800, 600))
        result_fmt, width, height = validate_image(data)
        assert result_fmt == expected
        assert (width, height) == (800, 600)

    def test_corrupt_bytes_raise(self) -> None:
        with pytest.raises(ImageValidationError):
            validate_image(b"not an image at all")

    def test_truncated_image_raises(self) -> None:
        data = _img_bytes("PNG")[:100]  # header only, body chopped
        with pytest.raises(ImageValidationError):
            validate_image(data)


class TestEnsureMinResolution:
    def test_passes_when_meets_minimum(self) -> None:
        ensure_min_resolution(_img_bytes("PNG", size=(3000, 3000)), 3000)  # no raise

    def test_rejects_below_minimum_with_descriptive_error(self) -> None:
        data = _img_bytes("PNG", size=(1024, 1024))
        with pytest.raises(ImageValidationError) as exc:
            ensure_min_resolution(data, 3000)
        message = str(exc.value)
        assert "1024" in message and "3000" in message

    def test_rejects_when_only_one_dimension_too_small(self) -> None:
        data = _img_bytes("PNG", size=(3000, 2000))
        with pytest.raises(ImageValidationError):
            ensure_min_resolution(data, 3000)


class TestUpscaleImage:
    def test_upscales_to_target_square(self) -> None:
        data = _img_bytes("PNG", size=(1024, 1024))
        out = upscale_image(data, 3000)
        fmt, width, height = validate_image(out)
        assert fmt == "png"
        assert (width, height) == (3000, 3000)

    def test_output_is_valid_png_for_jpeg_input(self) -> None:
        out = upscale_image(_img_bytes("JPEG", size=(1024, 1024)), 3000)
        assert validate_image(out)[0] == "png"
