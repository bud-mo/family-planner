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
from app.renderer.palette import flat_palette

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

# Flat palette entries (R, G, B …) — sourced from app.renderer.palette, the
# single source of truth for physical panel colours.
_BWR_PALETTE: list[int] = flat_palette("bwr")
_4GRAY_PALETTE: list[int] = flat_palette("4gray")
_SPECTRA6_PALETTE: list[int] = flat_palette("spectra6")


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
        2. Quantise to the configured palette (``bw`` / ``bwr`` / ``4gray`` / ``spectra6``)
           **without** dithering — flat, crisp text and UI.
        3. Apply Floyd-Steinberg dithering **selectively**: only the regions
           marked in ``image.info["dither_mask"]`` (photographic content and
           secondary grey text/rules) are taken from a dithered copy and
           composited over the crisp version.  This keeps glyph edges and flat
           fills sharp while still reproducing greys/photos through dithering.

        Backward compatibility: when no ``dither_mask`` is attached and
        ``eink_dither`` is enabled, the whole image is dithered (legacy
        behaviour).  When ``eink_dither`` is disabled, no dithering ever occurs.

        Returns a new ``PIL.Image`` in ``"RGB"`` mode for ``bw`` / ``bwr`` / ``4gray``
        palettes, or in palette mode (``"P"``) for ``spectra6`` (Pimoroni Inky Impression).
        The ``"P"`` image can be passed directly to ``inky.set_image()``.
        """
        # Read the dither mask *before* any transform (resize discards .info).
        mask = image.info.get("dither_mask")

        # 1. Resize — for 90°/270° the input canvas is transposed relative to
        #    the panel's native resolution, so swap the resize target dimensions.
        W, H = self._size
        resize_target = (H, W) if self._rotation in (90, 270) else (W, H)
        resized = image.resize(resize_target, Image.Resampling.LANCZOS)

        # 2. Crisp (no-dither) quantisation — always produced.
        flat = self._quantise(resized, Image.Dither.NONE)

        # 3. Dither selectively.
        if self._dither and mask is not None:
            # Marked regions only: composite a dithered copy over the crisp one.
            mask_resized = mask.convert("L").resize(
                resize_target, Image.Resampling.NEAREST
            )
            if mask_resized.getbbox() is not None:  # at least one marked pixel
                dithered = self._quantise(resized, Image.Dither.FLOYDSTEINBERG)
                result = flat.copy()
                # paste() with a binary "L" mask is a clean pixel-wise select,
                # valid for both "RGB" and "P" (spectra6) modes.
                result.paste(dithered, (0, 0), mask_resized)
            else:
                result = flat
        elif self._dither:
            # No mask supplied — dither the whole image (legacy behaviour).
            result = self._quantise(resized, Image.Dither.FLOYDSTEINBERG)
        else:
            result = flat

        # 4. Rotate — PIL.Image.rotate uses counter-clockwise convention;
        #    negate the angle for a clockwise physical rotation correction.
        if self._rotation:
            result = result.rotate(-self._rotation, expand=True)

        return result

    def _quantise(self, image: Image.Image, dither: Image.Dither) -> Image.Image:
        """Dispatch to the configured palette quantiser."""
        if self._palette == "bw":
            return self._quantise_bw(image, dither)
        if self._palette == "bwr":
            return self._quantise_bwr(image, dither)
        if self._palette == "4gray":
            return self._quantise_4gray(image, dither)
        if self._palette == "spectra6":
            return self._quantise_spectra6(image, dither)
        logger.warning("EinkRenderer: unknown palette %r — using bw", self._palette)
        return self._quantise_bw(image, dither)

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
