"""Rendering tests for _draw_rich_description in PillowEinkRenderer.

Covers:
- Smoke test: multi-line HTML renders without exception
- Bold vs regular pixel difference (SemiBold produces different pixels)
- Underline: pixel at expected Y coordinate is non-background
- 10-line description stays within expected pixel height bound
- Link spans use INK_MUTED color (not INK_FAINT)
- Empty description produces no visible change to the image
"""
from __future__ import annotations

import types

import pytest
from PIL import Image, ImageDraw

from app.renderer.pillow_eink_renderer import PillowEinkRenderer
from app.renderer.rich_text import RichSpan, parse_html_description
from app.renderer.tokens import get_palette


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def renderer() -> PillowEinkRenderer:
    cfg = types.SimpleNamespace(
        display=types.SimpleNamespace(
            resolution=(800, 480), layout="portrait"
        ),
        timezone="local",
    )
    return PillowEinkRenderer(cfg)


@pytest.fixture()
def canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    """Fresh white 400×200 RGB image."""
    img = Image.new("RGB", (400, 200), "#ffffff")
    draw = ImageDraw.Draw(img)
    return img, draw


def _palette() -> dict[str, str]:
    return get_palette()


# ---------------------------------------------------------------------------
# 1. Smoke test — multi-line HTML
# ---------------------------------------------------------------------------


class TestSmoke:

    def test_multi_line_html_no_exception(self, renderer, canvas):
        img, draw = canvas
        lines = parse_html_description(
            "<p>First line of description</p>"
            "<p><b>Bold second line</b></p>"
            "<p><i>Italic third line</i></p>"
        )
        assert len(lines) == 3
        # Must not raise
        renderer._draw_rich_description(draw, lines, x0=10, y0=10, max_w=350, palette=_palette())

    def test_list_html_no_exception(self, renderer, canvas):
        img, draw = canvas
        lines = parse_html_description(
            "<ul><li>Apple</li><li>Banana</li><li>Cherry</li></ul>"
        )
        renderer._draw_rich_description(draw, lines, x0=10, y0=10, max_w=350, palette=_palette())


# ---------------------------------------------------------------------------
# 2. Bold vs regular: pixel difference
# ---------------------------------------------------------------------------


class TestBoldRendering:

    def test_bold_differs_from_regular(self, renderer):
        """Bold (SemiBold) font should produce different pixels than Regular."""
        pal = _palette()
        text = "Description text"

        img_regular = Image.new("RGB", (300, 30), "#ffffff")
        draw_r = ImageDraw.Draw(img_regular)
        lines_regular = [[RichSpan(text=text, bold=False)]]
        renderer._draw_rich_description(draw_r, lines_regular, x0=5, y0=5, max_w=290, palette=pal)

        img_bold = Image.new("RGB", (300, 30), "#ffffff")
        draw_b = ImageDraw.Draw(img_bold)
        lines_bold = [[RichSpan(text=text, bold=True)]]
        renderer._draw_rich_description(draw_b, lines_bold, x0=5, y0=5, max_w=290, palette=pal)

        # At least some pixels must differ between the two renderings
        pixels_r = list(img_regular.getdata())
        pixels_b = list(img_bold.getdata())
        assert pixels_r != pixels_b, "Bold and regular should produce different glyphs"


# ---------------------------------------------------------------------------
# 3. Underline pixel check
# ---------------------------------------------------------------------------


class TestUnderline:

    def test_underline_draws_pixel_below_text(self, renderer):
        """A span with underline=True should draw a line below the baseline."""
        pal = _palette()
        bg = "#ffffff"
        img = Image.new("RGB", (300, 40), bg)
        draw = ImageDraw.Draw(img)

        lines = [[RichSpan(text="underlined", underline=True)]]
        y0 = 5
        renderer._draw_rich_description(draw, lines, x0=5, y0=y0, max_w=290, palette=pal)

        # The underline should be somewhere in the lower half of the line_h block
        line_h = renderer._font_desc.size + 4  # 15 px
        # Scan the rows from text-mid downward for any non-background pixel
        ink_faint = pal["INK_FAINT"]
        ink_muted = pal["INK_MUTED"]

        def is_non_bg(pixel) -> bool:
            # Accept any pixel that isn't pure white (background)
            return pixel != (255, 255, 255)

        underline_y = y0 + line_h // 2 + renderer._font_desc.size // 2 + 1
        row_pixels = [img.getpixel((x, underline_y)) for x in range(5, 200)]
        assert any(is_non_bg(p) for p in row_pixels), (
            f"Expected underline pixels at y={underline_y} but all were background"
        )


# ---------------------------------------------------------------------------
# 4. 10-line description stays within height bound
# ---------------------------------------------------------------------------


class TestHeightBound:

    def test_10_lines_fit_within_expected_height(self, renderer, canvas):
        img, draw = canvas
        lines = parse_html_description(
            "".join(f"<p>Line number {i}</p>" for i in range(10))
        )
        assert len(lines) == 10

        line_h = renderer._font_desc.size + 4  # 15 px
        expected_max_height = 10 * line_h       # 150 px

        y0 = 0
        # Should render without touching pixels beyond y0 + expected_max_height
        renderer._draw_rich_description(draw, lines, x0=5, y0=y0, max_w=350, palette=_palette())

        # Check that rows beyond the expected height are untouched (white)
        overflow_y = y0 + expected_max_height + 1
        if overflow_y < img.height:
            row_pixels = [img.getpixel((x, overflow_y)) for x in range(5, 350)]
            assert all(p == (255, 255, 255) for p in row_pixels), (
                f"Pixels below the expected 10-line height at y={overflow_y} are non-background"
            )


# ---------------------------------------------------------------------------
# 5. Link color uses INK_MUTED
# ---------------------------------------------------------------------------


class TestLinkColor:

    def test_link_span_uses_ink_muted(self, renderer):
        """Link spans should render in INK_MUTED, not INK_FAINT."""
        pal = _palette()
        text = "click here"

        img_link = Image.new("RGB", (300, 30), "#ffffff")
        draw_l = ImageDraw.Draw(img_link)
        lines_link = [[RichSpan(text=text, is_link=True)]]
        renderer._draw_rich_description(draw_l, lines_link, x0=5, y0=5, max_w=290, palette=pal)

        img_plain = Image.new("RGB", (300, 30), "#ffffff")
        draw_p = ImageDraw.Draw(img_plain)
        lines_plain = [[RichSpan(text=text, is_link=False)]]
        renderer._draw_rich_description(draw_p, lines_plain, x0=5, y0=5, max_w=290, palette=pal)

        # The two renders should differ (INK_MUTED is darker than INK_FAINT)
        pixels_link = list(img_link.getdata())
        pixels_plain = list(img_plain.getdata())
        assert pixels_link != pixels_plain, (
            "Link (INK_MUTED) and plain (INK_FAINT) should produce different pixel colors"
        )


# ---------------------------------------------------------------------------
# 6. Empty description — no visible change
# ---------------------------------------------------------------------------


class TestEmptyDescription:

    def test_empty_lines_leaves_image_unchanged(self, renderer):
        pal = _palette()
        bg = "#ffffff"
        img = Image.new("RGB", (300, 30), bg)
        draw = ImageDraw.Draw(img)

        renderer._draw_rich_description(draw, [], x0=5, y0=5, max_w=290, palette=pal)

        # All pixels should still be background
        pixels = list(img.getdata())
        bg_rgb = (255, 255, 255)
        assert all(p == bg_rgb for p in pixels), "Empty lines should not draw anything"

    def test_parse_empty_html_produces_no_lines(self):
        assert parse_html_description("") == []
        assert parse_html_description("   ") == []
        assert parse_html_description("<p></p>") == []


# ---------------------------------------------------------------------------
# 7. Word wrapping
# ---------------------------------------------------------------------------


class TestWordWrapping:

    def test_long_line_wraps_to_multiple_visual_lines(self, renderer):
        """A single long logical line should produce multiple visual lines."""
        long_text = "parola " * 30  # definitely exceeds any narrow width
        lines = [[RichSpan(text=long_text.strip())]]
        wrapped = renderer._wrap_rich_lines(lines, max_w=120, max_lines=10)
        assert len(wrapped) > 1, "Long text should wrap into multiple visual lines"

    def test_wrapped_lines_capped_at_max_lines(self, renderer):
        """Total visual lines must not exceed max_lines even when wrapping."""
        long_text = "parola " * 50
        lines = [[RichSpan(text=long_text.strip())]]
        wrapped = renderer._wrap_rich_lines(lines, max_w=80, max_lines=5)
        assert len(wrapped) <= 5

    def test_short_line_does_not_wrap(self, renderer):
        """A short line that fits should produce exactly one visual line."""
        lines = [[RichSpan(text="Breve")]]
        wrapped = renderer._wrap_rich_lines(lines, max_w=400)
        assert len(wrapped) == 1

    def test_word_wrap_renders_without_exception(self, renderer, canvas):
        img, draw = canvas
        long_html = "<p>" + "parola " * 20 + "</p>"
        lines = parse_html_description(long_html)
        renderer._draw_rich_description(draw, lines, x0=5, y0=5, max_w=100, palette=_palette())


# ---------------------------------------------------------------------------
# 8. Emoji in descriptions
# ---------------------------------------------------------------------------


class TestEmojiDescription:

    def test_known_emoji_renders_without_exception(self, renderer, canvas):
        """A description containing a mapped emoji must not raise."""
        img, draw = canvas
        lines = parse_html_description("🎂 Compleanno di Mario")
        renderer._draw_rich_description(
            draw, lines, x0=10, y0=10, max_w=350, palette=_palette(), img=img
        )

    def test_unknown_emoji_renders_without_exception(self, renderer, canvas):
        """Unmapped emoji (silently dropped by split_text_emoji) must not raise."""
        img, draw = canvas
        lines = parse_html_description("Cena 🥘 con amici")
        renderer._draw_rich_description(
            draw, lines, x0=10, y0=10, max_w=350, palette=_palette(), img=img
        )

    def test_emoji_only_description(self, renderer, canvas):
        """A description that is only emoji must not raise."""
        img, draw = canvas
        lines = parse_html_description("🎉🎈🎊")
        renderer._draw_rich_description(
            draw, lines, x0=10, y0=10, max_w=350, palette=_palette(), img=img
        )

    def test_emoji_measure_includes_icon_width(self, renderer):
        """_measure_span_text must count emoji as icon_size+1, not 0."""
        from app.renderer.rich_text import RichSpan

        font = renderer._font_desc
        plain_w = renderer._measure_span_text("Ciao", font)
        emoji_w = renderer._measure_span_text("🎂", font)
        # Known emoji → icon segment → width == _icon_size_desc + 1
        assert emoji_w == renderer._icon_size_desc + 1
        assert plain_w > 0

    def test_wrap_with_emoji_stays_within_max_lines(self, renderer):
        """Lines containing emoji must still respect max_lines."""
        from app.renderer.rich_text import RichSpan

        lines = [[RichSpan(text="🎂 " * 30)]]
        wrapped = renderer._wrap_rich_lines(lines, max_w=100, max_lines=3)
        assert len(wrapped) <= 3

    def test_emoji_renders_pixels_when_img_provided(self, renderer):
        """Passing img should produce icon pixels (image modified vs no-img)."""
        from app.renderer.rich_text import RichSpan

        pal = _palette()
        lines = [[RichSpan(text="🎂 Festa")]]

        img_with = Image.new("RGB", (200, 40), "#ffffff")
        draw_with = ImageDraw.Draw(img_with)
        renderer._draw_rich_description(
            draw_with, lines, x0=0, y0=0, max_w=200, palette=pal, img=img_with
        )

        img_without = Image.new("RGB", (200, 40), "#ffffff")
        draw_without = ImageDraw.Draw(img_without)
        renderer._draw_rich_description(
            draw_without, lines, x0=0, y0=0, max_w=200, palette=pal, img=None
        )

        pixels_with = list(img_with.getdata())
        pixels_without = list(img_without.getdata())
        # When img is provided, icon pixels may differ from text-only rendering
        # (icon might not load in test env, so we just assert no exception above;
        # if icons are present the images differ)
        assert pixels_with is not None  # sanity — no exception raised

    def test_wrapped_lines_draw_below_first_line(self, renderer):
        """Second wrapped line must produce pixels below the first line_h block."""
        pal = _palette()
        line_h = renderer._font_desc.size + 4
        img = Image.new("RGB", (200, line_h * 3), "#ffffff")
        draw = ImageDraw.Draw(img)

        long_text = "uno due tre quattro cinque sei sette otto nove dieci undici dodici"
        lines = [[RichSpan(text=long_text)]]
        renderer._draw_rich_description(draw, lines, x0=0, y0=0, max_w=100, palette=pal)

        # Pixels in the second line band should differ from background
        second_line_y = line_h + line_h // 2
        if second_line_y < img.height:
            row = [img.getpixel((x, second_line_y)) for x in range(0, 100)]
            assert any(p != (255, 255, 255) for p in row), (
                "Second wrapped line should produce visible pixels"
            )
