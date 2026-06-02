"""Tests for selective (mask-driven) dithering in EinkRenderer + palette resolution.

Covers:
- A dither mask restricts Floyd-Steinberg to the marked region only; unmarked
  regions stay flat (uniform) even when ``eink_dither`` is enabled.
- With ``eink_dither`` disabled, a mask has no effect (everything stays flat).
- ``resolve_palette`` snaps crisp tokens to panel colours but keeps ditherable
  tokens as their original grey.
- ``snap_to_palette`` returns the nearest physical panel colour.
"""
from __future__ import annotations

import types

from PIL import Image

from app.renderer.eink_renderer import EINK_RESOLUTIONS, EinkRenderer
from app.renderer.palette import (
    DITHERABLE_TOKENS,
    ditherable_color_values,
    resolve_palette,
    snap_to_palette,
)
from app.renderer.tokens import get_palette


def _config(palette: str = "bw", dither: bool = True) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        type="eink",
        eink_model="7in5_V2",
        eink_palette=palette,
        eink_dither=dither,
        rotation=0,
    )


def _panel_sized_gray(value: int = 127) -> Image.Image:
    return Image.new("RGB", EINK_RESOLUTIONS["7in5_V2"], (value, value, value))


def _half_mask() -> Image.Image:
    """White (dither) on the left half, black (crisp) on the right half."""
    w, h = EINK_RESOLUTIONS["7in5_V2"]
    mask = Image.new("L", (w, h), 0)
    for x in range(w // 2):
        for y in range(h):
            mask.putpixel((x, y), 255)
    return mask


def _unique(img: Image.Image, box: tuple[int, int, int, int]) -> set:
    return set(img.convert("RGB").crop(box).getdata())


# ---------------------------------------------------------------------------
# Selective dithering
# ---------------------------------------------------------------------------

class TestSelectiveDither:
    def test_only_marked_region_is_dithered(self) -> None:
        renderer = EinkRenderer(_config(palette="bw", dither=True))
        img = _panel_sized_gray(127)
        img.info["dither_mask"] = _half_mask()

        out = renderer.process(img)
        w, h = out.size

        left = _unique(out, (0, 0, w // 2, h))       # marked → dithered
        right = _unique(out, (w // 2, 0, w, h))       # unmarked → flat

        assert len(left) > 1, "marked region should be dithered (mixed pixels)"
        assert len(right) == 1, "unmarked region should stay flat (uniform)"

    def test_disabled_dither_ignores_mask(self) -> None:
        renderer = EinkRenderer(_config(palette="bw", dither=False))
        img = _panel_sized_gray(127)
        img.info["dither_mask"] = _half_mask()

        out = renderer.process(img)
        assert len(_unique(out, (0, 0, *out.size))) == 1, (
            "with dithering disabled the whole image must stay flat"
        )

    def test_empty_mask_stays_flat(self) -> None:
        renderer = EinkRenderer(_config(palette="bw", dither=True))
        img = _panel_sized_gray(127)
        img.info["dither_mask"] = Image.new("L", img.size, 0)  # nothing marked

        out = renderer.process(img)
        assert len(_unique(out, (0, 0, *out.size))) == 1


# ---------------------------------------------------------------------------
# Palette resolution
# ---------------------------------------------------------------------------

class TestPaletteResolution:
    def test_hdmi_returns_day_palette_unchanged(self) -> None:
        assert resolve_palette("hdmi", "bw") == get_palette()

    def test_eink_snaps_crisp_tokens(self) -> None:
        resolved = resolve_palette("eink", "bw")
        assert resolved["BG"] == "#FFFFFF"
        assert resolved["INK"] == "#000000"
        assert resolved["RULE_STRONG"] == "#000000"

    def test_eink_keeps_ditherable_tokens_grey(self) -> None:
        base = get_palette()
        resolved = resolve_palette("eink", "bw")
        for token in DITHERABLE_TOKENS:
            assert resolved[token] == base[token], (
                f"ditherable token {token} must keep its original grey"
            )

    def test_multicolour_forces_secondary_text_black(self) -> None:
        resolved = resolve_palette("eink", "spectra6")
        for token in ("INK_MUTED", "INK_FAINT", "HOLIDAY", "RULE"):
            assert resolved[token] == "#000000", (
                f"{token} must be crisp black on multicolour panels"
            )

    def test_today_highlight_stays_dithered_grey(self) -> None:
        # The today highlight (BG_ALT) keeps its grey on every e-ink palette,
        # so it is reproduced via dithering (coloured stipple on multicolour).
        for pal in ("bw", "4gray", "bwr", "spectra6"):
            assert resolve_palette("eink", pal)["BG_ALT"] == get_palette()["BG_ALT"]

    def test_multicolour_dithers_only_the_highlight(self) -> None:
        base = get_palette()
        # Multicolour panels dither only BG_ALT among UI tokens.
        assert ditherable_color_values("spectra6") == frozenset({base["BG_ALT"]})
        assert ditherable_color_values("bwr") == frozenset({base["BG_ALT"]})
        # Grayscale panels still dither all their secondary tokens.
        assert len(ditherable_color_values("bw")) > 1
        assert len(ditherable_color_values("4gray")) > 1

    def test_snap_to_palette_nearest(self) -> None:
        assert snap_to_palette("#111111", "bw") == (0, 0, 0)
        assert snap_to_palette("#EEEEEE", "bw") == (255, 255, 255)
        assert snap_to_palette((255, 10, 10), "bwr") == (255, 0, 0)
        assert snap_to_palette("#666666", "4gray") in {(85, 85, 85), (0, 0, 0)}


# ---------------------------------------------------------------------------
# Renderer integration — the Home view attaches a mask
# ---------------------------------------------------------------------------

class TestRendererAttachesMask:
    def _renderer(self):
        from app.renderer.pillow_eink_renderer import PillowEinkRenderer

        cfg = types.SimpleNamespace(
            display=types.SimpleNamespace(
                width=480, height=800, layout="portrait", type="eink",
                eink_palette="bw",
            ),
            timezone="local",
            artwork=types.SimpleNamespace(query="landscape"),
        )
        return PillowEinkRenderer(cfg)

    def test_render_attaches_L_mask(self) -> None:
        from app.renderer.state import NavigationState

        renderer = self._renderer()
        img = renderer.render(NavigationState(), [])
        mask = img.info.get("dither_mask")
        assert mask is not None
        assert mask.mode == "L"
        assert mask.size == img.size
        # The DOW header / muted labels are drawn in a ditherable grey, so at
        # least some pixels must be marked for dithering.
        assert mask.getbbox() is not None
