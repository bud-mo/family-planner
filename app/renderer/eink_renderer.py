"""E-ink post-processor for Family Planner.

``EinkRenderer`` is *not* a ``Renderer`` subclass — it is a post-processing
step that receives an already-composed ``PIL.Image`` from ``ImageRenderer``
and converts it to a format suitable for a specific Waveshare e-ink panel.

It is safe to import on macOS/Linux without Waveshare hardware libraries.
"""
from __future__ import annotations

import logging

from PIL import Image

from app.config import DisplayConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Known Waveshare panel resolutions  (model → (width, height) in pixels)
# ---------------------------------------------------------------------------

EINK_RESOLUTIONS: dict[str, tuple[int, int]] = {
    "7in5_V2": (800, 480),
    "7in5": (640, 384),
    "4in2": (400, 300),
    "4in2_V2": (400, 300),
    "2in13": (250, 122),
    "2in13_V2": (250, 122),
    "2in13_V3": (250, 122),
    "1in54": (200, 200),
    "1in54_V2": (200, 200),
    "5in83": (600, 448),
    "5in83_V2": (648, 480),
    "3in7": (280, 480),
    "2in7": (176, 264),
    # Pimoroni Inky Impression (Spectra 6)
    "inky_impression_4":  (600, 400),
    "inky_impression_7":  (800, 480),
    "inky_impression_13": (1600, 1200),
}

# 3-colour BWR palette entries (R, G, B)
_BWR_PALETTE: list[int] = [
    255, 255, 255,  # white
    0,   0,   0,   # black
    255, 0,   0,   # red
]

# 4-grey palette entries (R, G, B)  — black, dark-grey, light-grey, white
_4GRAY_PALETTE: list[int] = [
    0,   0,   0,
    85,  85,  85,
    170, 170, 170,
    255, 255, 255,
]

# 6-colour Pimoroni Spectra 6 palette entries (R, G, B)
# Colours: black, white, red, green, blue, yellow
_SPECTRA6_PALETTE: list[int] = [
    0,   0,   0,    # black
    255, 255, 255,  # white
    255, 0,   0,    # red
    0,   255, 0,    # green
    0,   0,   255,  # blue
    255, 255, 0,    # yellow
]


def _build_palette_image(entries: list[int]) -> Image.Image:
    """Build a palette-mode image pre-loaded with *entries*."""
    n_colours = len(entries) // 3
    palette_img = Image.new("P", (1, 1))
    # Pad remaining palette entries to 256 colours
    padded = entries + [0] * (768 - len(entries))
    palette_img.putpalette(padded)
    return palette_img


class EinkRenderer:
    """Post-processor that converts an RGB PIL.Image for an e-ink panel."""

    def __init__(self, config: DisplayConfig) -> None:
        self._config = config
        model = config.eink_model
        if model not in EINK_RESOLUTIONS:
            logger.warning(
                "EinkRenderer: unknown eink_model %r — falling back to 7in5_V2 (800×480)",
                model,
            )
            model = "7in5_V2"
        self._size: tuple[int, int] = EINK_RESOLUTIONS[model]
        self._palette: str = config.eink_palette
        self._dither: bool = config.eink_dither
        self._rotation: int = config.rotation

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def process(self, image: Image.Image) -> Image.Image:
        """Convert *image* to a panel-ready ``PIL.Image``.

        Steps:
        1. Resize to the panel's native resolution (LANCZOS).
        2. Quantise to the configured palette (``bw`` / ``bwr`` / ``4gray`` / ``spectra6``).
        3. Apply Floyd-Steinberg dithering if ``eink_dither`` is enabled.

        Returns a new ``PIL.Image`` in ``"RGB"`` mode for ``bw`` / ``bwr`` / ``4gray``
        palettes, or in palette mode (``"P"``) for ``spectra6`` (Pimoroni Inky Impression).
        The ``"P"`` image can be passed directly to ``inky.set_image()``.
        """
        dither_mode = Image.Dither.FLOYDSTEINBERG if self._dither else Image.Dither.NONE

        # 1. Resize — for 90°/270° the input canvas is transposed relative to
        #    the panel's native resolution, so swap the resize target dimensions.
        W, H = self._size
        resize_target = (H, W) if self._rotation in (90, 270) else (W, H)
        resized = image.resize(resize_target, Image.Resampling.LANCZOS)

        # 2 + 3. Quantise
        if self._palette == "bw":
            result = self._quantise_bw(resized, dither_mode)
        elif self._palette == "bwr":
            result = self._quantise_bwr(resized, dither_mode)
        elif self._palette == "4gray":
            result = self._quantise_4gray(resized, dither_mode)
        elif self._palette == "spectra6":
            result = self._quantise_spectra6(resized, dither_mode)
        else:
            logger.warning(
                "EinkRenderer: unknown palette %r — using bw", self._palette
            )
            result = self._quantise_bw(resized, dither_mode)

        # 4. Rotate — PIL.Image.rotate uses counter-clockwise convention;
        #    negate the angle for a clockwise physical rotation correction.
        if self._rotation:
            result = result.rotate(-self._rotation, expand=True)

        return result

    # ------------------------------------------------------------------
    # Private quantisation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _quantise_bw(
        image: Image.Image, dither: Image.Dither
    ) -> Image.Image:
        """Two-level black-and-white quantisation."""
        grey = image.convert("L")
        bw = grey.convert("1", dither=dither)
        return bw.convert("RGB")

    @staticmethod
    def _quantise_bwr(
        image: Image.Image, dither: Image.Dither
    ) -> Image.Image:
        """Three-colour black/white/red quantisation."""
        palette_img = _build_palette_image(_BWR_PALETTE)
        quantised = image.convert("RGB").quantize(
            colors=3,
            palette=palette_img,
            dither=dither,
        )
        return quantised.convert("RGB")

    @staticmethod
    def _quantise_4gray(
        image: Image.Image, dither: Image.Dither
    ) -> Image.Image:
        """Four-level grey quantisation."""
        palette_img = _build_palette_image(_4GRAY_PALETTE)
        quantised = image.convert("RGB").quantize(
            colors=4,
            palette=palette_img,
            dither=dither,
        )
        return quantised.convert("RGB")

    @staticmethod
    def _quantise_spectra6(
        image: Image.Image, dither: Image.Dither
    ) -> Image.Image:
        """Six-colour Pimoroni Spectra 6 quantisation (black, white, red, green, blue, yellow).

        Returns a palette-mode (``"P"``) image ready for ``inky.set_image()``.
        The Inky library maps each palette RGB value to the nearest hardware colour.
        """
        palette_img = _build_palette_image(_SPECTRA6_PALETTE)
        return image.convert("RGB").quantize(
            colors=6,
            palette=palette_img,
            dither=dither,
        )
