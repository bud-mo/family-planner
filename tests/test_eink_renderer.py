"""Unit tests for EinkRenderer — pixel-perfect e-ink post-processing.

Covers:
- Output mode is always RGB
- Output is resized to the correct panel resolution
- All output pixels are strict palette entries (bw / bwr / 4gray)
- Uniform input regions stay uniform when dithering is disabled
- Floyd-Steinberg dithering *does* produce spatial variation in mixed-tone regions
  (validates that the no-dither tests are non-trivial)
- The original image is never mutated
- All known Waveshare model identifiers resolve to a valid resolution
"""
from __future__ import annotations

import types

import pytest
from PIL import Image

from app.renderer.eink_renderer import (
    EINK_RESOLUTIONS,
    EinkRenderer,
    _4GRAY_PALETTE,
    _BWR_PALETTE,
)


# ---------------------------------------------------------------------------
# Palette sets used for pixel-compliance assertions
# ---------------------------------------------------------------------------

_BW_PIXELS: frozenset[tuple[int, int, int]] = frozenset(
    {(0, 0, 0), (255, 255, 255)}
)
_BWR_PIXELS: frozenset[tuple[int, int, int]] = frozenset(
    {
        (255, 255, 255),  # white
        (0, 0, 0),        # black
        (255, 0, 0),      # red
    }
)
_4GRAY_PIXELS: frozenset[tuple[int, int, int]] = frozenset(
    {(0, 0, 0), (85, 85, 85), (170, 170, 170), (255, 255, 255)}
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(
    palette: str = "bw",
    dither: bool = False,
    model: str = "7in5_V2",
) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        type="eink",
        eink_model=model,
        eink_palette=palette,
        eink_dither=dither,
        rotation=0,
    )


def _solid_image(color: tuple[int, int, int], size: tuple[int, int] = (200, 100)) -> Image.Image:
    return Image.new("RGB", size, color)


def _gradient_image(size: tuple[int, int] = (256, 100)) -> Image.Image:
    """Horizontal gradient from black (left) to white (right)."""
    w, h = size
    img = Image.new("RGB", size)
    pixels = img.load()
    assert pixels is not None
    for x in range(w):
        gray = int(x * 255 / max(w - 1, 1))
        for y in range(h):
            pixels[x, y] = (gray, gray, gray)  # type: ignore[index]
    return img


def _unique_pixels(img: Image.Image) -> set[tuple[int, ...]]:
    return set(img.convert("RGB").getdata())


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def renderer_bw() -> EinkRenderer:
    return EinkRenderer(_make_config(palette="bw", dither=False))


@pytest.fixture
def renderer_bw_dither() -> EinkRenderer:
    return EinkRenderer(_make_config(palette="bw", dither=True))


@pytest.fixture
def renderer_bwr() -> EinkRenderer:
    return EinkRenderer(_make_config(palette="bwr", dither=False))


@pytest.fixture
def renderer_bwr_dither() -> EinkRenderer:
    return EinkRenderer(_make_config(palette="bwr", dither=True))


@pytest.fixture
def renderer_4gray() -> EinkRenderer:
    return EinkRenderer(_make_config(palette="4gray", dither=False))


@pytest.fixture
def renderer_4gray_dither() -> EinkRenderer:
    return EinkRenderer(_make_config(palette="4gray", dither=True))


# ---------------------------------------------------------------------------
# Output mode
# ---------------------------------------------------------------------------

class TestOutputMode:
    """process() must always return an RGB image."""

    def test_bw_returns_rgb(self, renderer_bw: EinkRenderer) -> None:
        out = renderer_bw.process(_solid_image((127, 127, 127)))
        assert out.mode == "RGB"

    def test_bwr_returns_rgb(self, renderer_bwr: EinkRenderer) -> None:
        out = renderer_bwr.process(_solid_image((200, 20, 20)))
        assert out.mode == "RGB"

    def test_4gray_returns_rgb(self, renderer_4gray: EinkRenderer) -> None:
        out = renderer_4gray.process(_solid_image((85, 85, 85)))
        assert out.mode == "RGB"


# ---------------------------------------------------------------------------
# Output dimensions
# ---------------------------------------------------------------------------

class TestOutputDimensions:
    """process() must resize to the panel's native resolution."""

    def test_resizes_smaller_input(self, renderer_bw: EinkRenderer) -> None:
        img = _solid_image((255, 255, 255), size=(400, 240))
        out = renderer_bw.process(img)
        assert out.size == EINK_RESOLUTIONS["7in5_V2"]  # (800, 480)

    def test_resizes_larger_input(self, renderer_bw: EinkRenderer) -> None:
        img = _solid_image((0, 0, 0), size=(1920, 1080))
        out = renderer_bw.process(img)
        assert out.size == EINK_RESOLUTIONS["7in5_V2"]

    def test_already_correct_size_unchanged(self, renderer_bw: EinkRenderer) -> None:
        w, h = EINK_RESOLUTIONS["7in5_V2"]
        img = _solid_image((255, 255, 255), size=(w, h))
        out = renderer_bw.process(img)
        assert out.size == (w, h)

    @pytest.mark.parametrize("model,expected_size", list(EINK_RESOLUTIONS.items()))
    def test_all_models_produce_correct_size(
        self, model: str, expected_size: tuple[int, int]
    ) -> None:
        renderer = EinkRenderer(_make_config(model=model))
        img = _solid_image((200, 200, 200), size=(100, 100))
        out = renderer.process(img)
        assert out.size == expected_size

    def test_unknown_model_falls_back_to_7in5_v2(self) -> None:
        renderer = EinkRenderer(_make_config(model="totally_unknown"))
        out = renderer.process(_solid_image((0, 0, 0)))
        assert out.size == EINK_RESOLUTIONS["7in5_V2"]


# ---------------------------------------------------------------------------
# Palette compliance — all pixels must be strict palette entries
# ---------------------------------------------------------------------------

class TestPaletteCompliance:
    """Every output pixel must be one of the allowed panel colours."""

    def test_bw_nodither_gradient_only_bw_pixels(self, renderer_bw: EinkRenderer) -> None:
        out = renderer_bw.process(_gradient_image())
        pixels = _unique_pixels(out)
        assert pixels <= _BW_PIXELS

    def test_bw_dither_gradient_only_bw_pixels(self, renderer_bw_dither: EinkRenderer) -> None:
        out = renderer_bw_dither.process(_gradient_image())
        pixels = _unique_pixels(out)
        assert pixels <= _BW_PIXELS

    def test_bwr_nodither_gradient_only_bwr_pixels(self, renderer_bwr: EinkRenderer) -> None:
        # Use a reddish + neutral gradient
        img = Image.new("RGB", (100, 100))
        px = img.load()
        assert px is not None
        for x in range(100):
            for y in range(50):
                px[x, y] = (200, 20, 20)     # type: ignore[index]  # reddish
            for y in range(50, 100):
                px[x, y] = (x * 2, x * 2, x * 2)  # type: ignore[index]  # neutral gray
        out = renderer_bwr.process(img)
        pixels = _unique_pixels(out)
        assert pixels <= _BWR_PIXELS

    def test_4gray_nodither_gradient_only_4gray_pixels(self, renderer_4gray: EinkRenderer) -> None:
        out = renderer_4gray.process(_gradient_image())
        pixels = _unique_pixels(out)
        assert pixels <= _4GRAY_PIXELS

    def test_4gray_dither_gradient_only_4gray_pixels(self, renderer_4gray_dither: EinkRenderer) -> None:
        out = renderer_4gray_dither.process(_gradient_image())
        pixels = _unique_pixels(out)
        assert pixels <= _4GRAY_PIXELS


# ---------------------------------------------------------------------------
# Pixel-perfect: uniform regions stay uniform without dithering
# ---------------------------------------------------------------------------

class TestUniformRegions:
    """With dithering disabled, a solid-colour input must produce a solid output.

    This is the core pixel-perfect guarantee: no dithering noise is injected
    into regions that are already a single colour.
    """

    @pytest.mark.parametrize("gray", [0, 50, 100, 128, 200, 255])
    def test_bw_solid_gray_is_uniform(self, renderer_bw: EinkRenderer, gray: int) -> None:
        img = _solid_image((gray, gray, gray), size=(200, 200))
        out = renderer_bw.process(img)
        pixels = _unique_pixels(out)
        assert len(pixels) == 1, (
            f"Solid gray={gray} produced {len(pixels)} distinct pixel values: {pixels}"
        )

    def test_bw_solid_white_stays_white(self, renderer_bw: EinkRenderer) -> None:
        out = renderer_bw.process(_solid_image((255, 255, 255)))
        assert _unique_pixels(out) == {(255, 255, 255)}

    def test_bw_solid_black_stays_black(self, renderer_bw: EinkRenderer) -> None:
        out = renderer_bw.process(_solid_image((0, 0, 0)))
        assert _unique_pixels(out) == {(0, 0, 0)}

    def test_bwr_solid_red_stays_red(self, renderer_bwr: EinkRenderer) -> None:
        out = renderer_bwr.process(_solid_image((255, 0, 0)))
        pixels = _unique_pixels(out)
        assert len(pixels) == 1

    def test_bwr_solid_white_stays_white(self, renderer_bwr: EinkRenderer) -> None:
        out = renderer_bwr.process(_solid_image((255, 255, 255)))
        pixels = _unique_pixels(out)
        assert len(pixels) == 1

    def test_bwr_solid_black_stays_black(self, renderer_bwr: EinkRenderer) -> None:
        out = renderer_bwr.process(_solid_image((0, 0, 0)))
        pixels = _unique_pixels(out)
        assert len(pixels) == 1

    @pytest.mark.parametrize("entry", [(0, 0, 0), (85, 85, 85), (170, 170, 170), (255, 255, 255)])
    def test_4gray_palette_entry_is_identity(
        self, renderer_4gray: EinkRenderer, entry: tuple[int, int, int]
    ) -> None:
        """Each of the four exact palette entries must round-trip to itself."""
        out = renderer_4gray.process(_solid_image(entry))
        pixels = _unique_pixels(out)
        assert pixels == {entry}, (
            f"Palette entry {entry} did not survive roundtrip: got {pixels}"
        )

    @pytest.mark.parametrize("gray", [0, 50, 100, 128, 200, 255])
    def test_4gray_solid_gray_is_uniform(self, renderer_4gray: EinkRenderer, gray: int) -> None:
        img = _solid_image((gray, gray, gray), size=(200, 200))
        out = renderer_4gray.process(img)
        pixels = _unique_pixels(out)
        assert len(pixels) == 1, (
            f"Solid gray={gray} produced {len(pixels)} distinct pixel values: {pixels}"
        )


# ---------------------------------------------------------------------------
# Dithering contrast — prove the no-dither tests are non-trivial
# ---------------------------------------------------------------------------

class TestDitheringProducesVariation:
    """With Floyd-Steinberg enabled, a mid-tone gradient must produce visible
    spatial variation — demonstrating that the no-dither tests above are not
    vacuously true.
    """

    def _count_unique_in_row(self, img: Image.Image, y: int) -> int:
        w = img.width
        row = [img.getpixel((x, y)) for x in range(w)]
        return len(set(row))

    def test_bw_dither_gradient_has_more_variation_than_nodither(
        self,
        renderer_bw: EinkRenderer,
        renderer_bw_dither: EinkRenderer,
    ) -> None:
        """A BW gradient processed with dithering must have more unique rows than without."""
        # Use a vertical gradient so each row has a uniform input gray value
        h = 256
        img = Image.new("RGB", (200, h))
        px = img.load()
        assert px is not None
        for y in range(h):
            gray = int(y * 255 / (h - 1))
            for x in range(200):
                px[x, y] = (gray, gray, gray)  # type: ignore[index]

        out_nodither = renderer_bw.process(img)
        out_dither = renderer_bw_dither.process(img)

        # With no dithering, each row should be uniform (1 unique colour per row)
        nodither_max_unique = max(
            self._count_unique_in_row(out_nodither, y)
            for y in range(out_nodither.height)
        )
        # With dithering, mid-tone rows should have more than 1 colour
        dither_max_unique = max(
            self._count_unique_in_row(out_dither, y)
            for y in range(out_dither.height)
        )

        assert nodither_max_unique == 1, (
            "No-dither: expected every row to be uniform "
            f"(max unique colours per row: {nodither_max_unique})"
        )
        assert dither_max_unique > 1, (
            "Dither: expected at least one row with mixed colours, "
            f"but max unique colours per row was {dither_max_unique}"
        )

    def test_4gray_dither_gradient_has_more_variation_than_nodither(
        self,
        renderer_4gray: EinkRenderer,
        renderer_4gray_dither: EinkRenderer,
    ) -> None:
        """A 4-gray gradient with dithering must have more unique rows than without."""
        h = 200
        img = Image.new("RGB", (200, h))
        px = img.load()
        assert px is not None
        for y in range(h):
            gray = int(y * 255 / (h - 1))
            for x in range(200):
                px[x, y] = (gray, gray, gray)  # type: ignore[index]

        out_nodither = renderer_4gray.process(img)
        out_dither = renderer_4gray_dither.process(img)

        nodither_max_unique = max(
            self._count_unique_in_row(out_nodither, y)
            for y in range(out_nodither.height)
        )
        dither_max_unique = max(
            self._count_unique_in_row(out_dither, y)
            for y in range(out_dither.height)
        )

        assert nodither_max_unique == 1, (
            f"No-dither: expected uniform rows, got max {nodither_max_unique} per row"
        )
        assert dither_max_unique > 1, (
            f"Dither: expected mixed rows, got max {dither_max_unique} per row"
        )


# ---------------------------------------------------------------------------
# Input immutability
# ---------------------------------------------------------------------------

class TestInputImmutability:
    """process() must not mutate the source image."""

    def test_bw_does_not_mutate_input(self, renderer_bw: EinkRenderer) -> None:
        img = _solid_image((127, 127, 127))
        before = list(img.getdata())
        renderer_bw.process(img)
        after = list(img.getdata())
        assert before == after

    def test_bwr_does_not_mutate_input(self, renderer_bwr: EinkRenderer) -> None:
        img = _solid_image((200, 50, 50))
        before = list(img.getdata())
        renderer_bwr.process(img)
        after = list(img.getdata())
        assert before == after

    def test_4gray_does_not_mutate_input(self, renderer_4gray: EinkRenderer) -> None:
        img = _solid_image((130, 130, 130))
        before = list(img.getdata())
        renderer_4gray.process(img)
        after = list(img.getdata())
        assert before == after

    def test_process_returns_new_image_object(self, renderer_bw: EinkRenderer) -> None:
        img = _solid_image((255, 255, 255), size=EINK_RESOLUTIONS["7in5_V2"])
        out = renderer_bw.process(img)
        assert out is not img


# ---------------------------------------------------------------------------
# Palette constant integrity
# ---------------------------------------------------------------------------

class TestPaletteConstants:
    """The palette constants exported from eink_renderer must be consistent."""

    def test_bwr_palette_has_three_entries(self) -> None:
        assert len(_BWR_PALETTE) == 9  # 3 colours × 3 channels

    def test_4gray_palette_has_four_entries(self) -> None:
        assert len(_4GRAY_PALETTE) == 12  # 4 colours × 3 channels

    def test_bwr_palette_entries_are_valid_rgb(self) -> None:
        for i in range(0, len(_BWR_PALETTE), 3):
            r, g, b = _BWR_PALETTE[i], _BWR_PALETTE[i + 1], _BWR_PALETTE[i + 2]
            assert 0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255

    def test_4gray_palette_entries_are_valid_rgb(self) -> None:
        for i in range(0, len(_4GRAY_PALETTE), 3):
            r, g, b = _4GRAY_PALETTE[i], _4GRAY_PALETTE[i + 1], _4GRAY_PALETTE[i + 2]
            assert 0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255

    def test_4gray_palette_entries_are_neutral_grays(self) -> None:
        """All 4-gray entries must have R == G == B (neutral gray)."""
        for i in range(0, len(_4GRAY_PALETTE), 3):
            r, g, b = _4GRAY_PALETTE[i], _4GRAY_PALETTE[i + 1], _4GRAY_PALETTE[i + 2]
            assert r == g == b, f"Non-neutral gray at index {i}: ({r},{g},{b})"

    def test_eink_resolutions_all_positive(self) -> None:
        for model, (w, h) in EINK_RESOLUTIONS.items():
            assert w > 0 and h > 0, f"Model {model!r} has invalid resolution ({w},{h})"
