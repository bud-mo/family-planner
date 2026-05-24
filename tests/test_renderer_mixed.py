"""Unit tests for the mixed text+icon rendering helpers in PillowEinkRenderer.

Covers:
- _measure_mixed   — width calculation for text and icon segments
- _fit_mixed       — truncation within a pixel budget
- _draw_mixed      — compositing onto a PIL Image (smoke + pixel checks)
"""
from __future__ import annotations

import types

import pytest
from PIL import Image, ImageDraw, ImageFont

from app.renderer.emoji_icons import split_text_emoji
from app.renderer.pillow_eink_renderer import PillowEinkRenderer
from app.renderer.tokens import FONT_BODY_REGULAR, FONTS_DIR, TEXT_BASE


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def renderer() -> PillowEinkRenderer:
    cfg = types.SimpleNamespace(
        display=types.SimpleNamespace(
            width=800, height=480, layout="portrait", type="hdmi"
        ),
        timezone="local",
    )
    return PillowEinkRenderer(cfg)


@pytest.fixture(scope="module")
def font() -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS_DIR / FONT_BODY_REGULAR), TEXT_BASE)


@pytest.fixture()
def canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    """Return a fresh white 400×60 RGBA image and its draw context."""
    img = Image.new("RGB", (400, 60), "#ffffff")
    draw = ImageDraw.Draw(img)
    return img, draw


def _icon_size() -> int:
    return int(TEXT_BASE * 0.75)  # ≈ 11 px


# ---------------------------------------------------------------------------
# _measure_mixed
# ---------------------------------------------------------------------------

class TestMeasureMixed:

    def test_empty_segments(self, canvas, font):
        _, draw = canvas
        assert PillowEinkRenderer._measure_mixed(draw, [], font, _icon_size()) == 0.0

    def test_text_only(self, canvas, font):
        _, draw = canvas
        text = "Hello"
        segs = [("text", text)]
        expected = draw.textbbox((0, 0), text, font=font)[2]
        result = PillowEinkRenderer._measure_mixed(draw, segs, font, _icon_size())
        assert result == pytest.approx(expected, abs=1)

    def test_icon_only(self, canvas, font):
        _, draw = canvas
        sz = _icon_size()
        segs = [("icon", "heart")]
        result = PillowEinkRenderer._measure_mixed(draw, segs, font, sz)
        assert result == sz + 1  # icon + 1 px gap

    def test_multiple_icons(self, canvas, font):
        _, draw = canvas
        sz = _icon_size()
        segs = [("icon", "heart"), ("icon", "star"), ("icon", "cake")]
        result = PillowEinkRenderer._measure_mixed(draw, segs, font, sz)
        assert result == (sz + 1) * 3

    def test_mixed_text_and_icon(self, canvas, font):
        _, draw = canvas
        sz = _icon_size()
        text = "Ciao "
        segs = [("text", text), ("icon", "heart")]
        text_w = draw.textbbox((0, 0), text, font=font)[2]
        expected = text_w + sz + 1
        result = PillowEinkRenderer._measure_mixed(draw, segs, font, sz)
        assert result == pytest.approx(expected, abs=1)

    def test_empty_text_segment_contributes_zero(self, canvas, font):
        _, draw = canvas
        segs = [("text", "")]
        assert PillowEinkRenderer._measure_mixed(draw, segs, font, _icon_size()) == 0.0


# ---------------------------------------------------------------------------
# _fit_mixed
# ---------------------------------------------------------------------------

class TestFitMixed:

    def test_fits_without_truncation(self, canvas, font):
        _, draw = canvas
        segs = [("text", "Hi")]
        result = PillowEinkRenderer._fit_mixed(draw, segs, font, _icon_size(), 500)
        assert result == [("text", "Hi")]

    def test_zero_max_width_returns_empty(self, canvas, font):
        _, draw = canvas
        segs = [("text", "Hello")]
        assert PillowEinkRenderer._fit_mixed(draw, segs, font, _icon_size(), 0) == []

    def test_long_text_truncated_with_ellipsis(self, canvas, font):
        _, draw = canvas
        segs = [("text", "Appuntamento molto lungo che non ci sta")]
        result = PillowEinkRenderer._fit_mixed(draw, segs, font, _icon_size(), 60)
        # Must end with an ellipsis text segment
        assert result[-1] == ("text", "…")
        # Total rendered width must fit within budget
        total_w = PillowEinkRenderer._measure_mixed(draw, result, font, _icon_size())
        assert total_w <= 60

    def test_icon_dropped_when_budget_exceeded(self, canvas, font):
        _, draw = canvas
        # Very narrow budget: forces icon to be dropped
        segs = [("text", "X"), ("icon", "heart")]
        result = PillowEinkRenderer._fit_mixed(draw, segs, font, _icon_size(), 30)
        # Result must fit
        total_w = PillowEinkRenderer._measure_mixed(draw, result, font, _icon_size())
        assert total_w <= 30

    def test_all_icons_fit(self, canvas, font):
        _, draw = canvas
        sz = _icon_size()
        segs = [("icon", "heart"), ("icon", "star")]
        result = PillowEinkRenderer._fit_mixed(draw, segs, font, sz, 500)
        assert result == segs

    def test_matrimonio_title_fits_in_wide_canvas(self, canvas, font):
        _, draw = canvas
        title = "Matrimonio nostro 😍🥰🤩❤️❤️❤️❤️❤️❤️"
        segs = split_text_emoji(title)
        result = PillowEinkRenderer._fit_mixed(draw, segs, font, _icon_size(), 400)
        total_w = PillowEinkRenderer._measure_mixed(draw, result, font, _icon_size())
        assert total_w <= 400

    def test_matrimonio_title_truncated_in_narrow_canvas(self, canvas, font):
        _, draw = canvas
        title = "Matrimonio nostro 😍🥰🤩❤️❤️❤️❤️❤️❤️"
        segs = split_text_emoji(title)
        result = PillowEinkRenderer._fit_mixed(draw, segs, font, _icon_size(), 100)
        total_w = PillowEinkRenderer._measure_mixed(draw, result, font, _icon_size())
        assert total_w <= 100
        # Result must end with ellipsis
        assert result[-1] == ("text", "…")

    def test_result_is_a_copy(self, canvas, font):
        _, draw = canvas
        segs = [("text", "Ciao")]
        result = PillowEinkRenderer._fit_mixed(draw, segs, font, _icon_size(), 500)
        result.append(("text", " extra"))
        # Original segs must be untouched
        assert segs == [("text", "Ciao")]


# ---------------------------------------------------------------------------
# _draw_mixed
# ---------------------------------------------------------------------------

INK = "#1a1a1a"
BG  = "#ffffff"


def _has_non_white_pixels(img: Image.Image, region: tuple[int, int, int, int]) -> bool:
    """Return True if *region* (left, top, right, bottom) contains any non-white pixel."""
    cropped = img.crop(region)
    pixels = list(cropped.getdata())
    return any(p != (255, 255, 255) for p in pixels)


class TestDrawMixed:

    def test_smoke_no_exception(self, renderer, canvas, font):
        img, draw = canvas
        segs = [("text", "Ciao")]
        renderer._draw_mixed(draw, img, segs, 4, 30, font, INK, _icon_size())

    def test_text_segment_draws_pixels(self, renderer, canvas, font):
        img, draw = canvas
        segs = [("text", "Hi")]
        renderer._draw_mixed(draw, img, segs, 4, 30, font, INK, _icon_size())
        # Check the region where text should appear
        assert _has_non_white_pixels(img, (4, 15, 60, 45))

    def test_icon_segment_draws_pixels(self, renderer, canvas, font):
        # Uses "heart" — skip if not pre-baked
        from app.renderer.emoji_icons import load_icon
        if load_icon("heart", _icon_size()) is None:
            pytest.skip("heart.png not available")

        img, draw = canvas
        sz = _icon_size()
        segs = [("icon", "heart")]
        renderer._draw_mixed(draw, img, segs, 4, 30, font, INK, sz)
        # The icon should have produced non-white pixels
        assert _has_non_white_pixels(img, (4, 30 - sz, 4 + sz + 4, 30 + sz))

    def test_missing_icon_silently_skipped(self, renderer, canvas, font):
        """An icon with no pre-baked PNG must not raise and must not advance x."""
        img, draw = canvas
        segs = [("icon", "__no_such_icon__"), ("text", "OK")]
        # Should not raise
        renderer._draw_mixed(draw, img, segs, 4, 30, font, INK, _icon_size())
        # "OK" text must still be drawn (non-white pixels after x=4)
        assert _has_non_white_pixels(img, (4, 15, 80, 45))

    def test_icon_rendered_on_dark_background(self, renderer, font):
        from app.renderer.emoji_icons import load_icon
        if load_icon("heart", _icon_size()) is None:
            pytest.skip("heart.png not available")

        light_ink = "#f5f5f0"
        dark_bg   = "#1a1a1a"
        img  = Image.new("RGB", (60, 40), dark_bg)
        draw = ImageDraw.Draw(img)
        sz   = _icon_size()

        segs = [("icon", "heart")]
        renderer._draw_mixed(draw, img, segs, 4, 20, font, light_ink, sz)

        # At least one pixel in the icon region must differ from the dark background
        assert _has_non_white_pixels(img, (4, 20 - sz, 4 + sz + 2, 20 + sz))

    def test_empty_segments_no_change(self, renderer, canvas, font):
        img, draw = canvas
        original = img.copy()
        renderer._draw_mixed(draw, img, [], 4, 30, font, INK, _icon_size())
        assert list(img.getdata()) == list(original.getdata())

    # ------------------------------------------------------------------
    # End-to-end pipeline: split → fit → draw
    # ------------------------------------------------------------------

    def test_matrimonio_full_pipeline(self, renderer, canvas, font):
        img, draw = canvas
        title = "Matrimonio nostro 😍🥰🤩❤️❤️❤️❤️❤️❤️"
        sz    = _icon_size()

        segs = split_text_emoji(title)
        segs = renderer._fit_mixed(draw, segs, font, sz, 390)
        renderer._draw_mixed(draw, img, segs, 4, 30, font, INK, sz)

        # Something must have been drawn
        assert _has_non_white_pixels(img, (4, 10, 380, 50))

    def test_hex_to_rgb_conversion(self):
        assert PillowEinkRenderer._hex_to_rgb("#1a1a1a") == (26, 26, 26)
        assert PillowEinkRenderer._hex_to_rgb("#ffffff") == (255, 255, 255)
        assert PillowEinkRenderer._hex_to_rgb("#f5f5f0") == (245, 245, 240)
        assert PillowEinkRenderer._hex_to_rgb("ff0000") == (255, 0, 0)  # no leading #
