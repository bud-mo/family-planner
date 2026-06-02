"""Panel-palette resolution for the e-ink renderer.

Maps the design-token "day palette" (full RGB, see :mod:`app.renderer.tokens`)
onto the limited colour set of a specific e-ink panel, and decides which tokens
are reproduced *crisply* (snapped to an exact panel colour, so they survive
nearest-colour quantisation with sharp edges) versus *via dithering* (kept as
their original grey so :class:`~app.renderer.eink_renderer.EinkRenderer` can
dither them — preserving visual hierarchy on 1-bit panels).

This module is the single source of truth for the physical panel colours.
"""
from __future__ import annotations

from PIL import ImageColor

from app.renderer.tokens import get_palette

# ---------------------------------------------------------------------------
# Physical panel colours (R, G, B) per palette identifier
# ---------------------------------------------------------------------------

PANEL_COLORS: dict[str, list[tuple[int, int, int]]] = {
    "bw":       [(0, 0, 0), (255, 255, 255)],
    "bwr":      [(0, 0, 0), (255, 255, 255), (255, 0, 0)],
    "4gray":    [(0, 0, 0), (85, 85, 85), (170, 170, 170), (255, 255, 255)],
    "spectra6": [
        (0, 0, 0),       # black
        (255, 255, 255), # white
        (255, 0, 0),     # red
        (0, 255, 0),     # green
        (0, 0, 255),     # blue
        (255, 255, 0),   # yellow
    ],
}

# Semantic tokens whose grey is reproduced through dithering (not snapped to a
# panel colour) so that secondary text/rules keep a distinct tone on grayscale
# panels. Primary tokens (INK, ACCENT, RULE_STRONG, BG) are snapped instead.
#
# Dithering grey only looks good on grayscale palettes (bw / 4gray): there it
# yields a clean grey stipple.  On *multicolour* palettes (bwr / spectra6) the
# error-diffusion approximates grey with coloured pixels — a noisy rainbow — so
# secondary tokens are snapped to a crisp legible colour instead (see below).
DITHERABLE_TOKENS: frozenset[str] = frozenset(
    {"INK_MUTED", "INK_FAINT", "RULE", "HOLIDAY", "BG_ALT"}
)

# Palettes that render grey pleasantly through dithering.
GRAYSCALE_PALETTES: frozenset[str] = frozenset({"bw", "4gray"})

# Secondary tokens forced to solid black on multicolour panels so they stay
# legible (a naive nearest-snap would turn the lightest greys white/invisible).
_MULTICOLOUR_BLACK_TOKENS: tuple[str, ...] = ("INK_MUTED", "INK_FAINT", "HOLIDAY", "RULE")

# On multicolour panels only the today-cell highlight (BG_ALT) is reproduced via
# dithering — its grey has no panel equivalent and a coloured stipple is the
# wanted look there; all other secondary tokens are snapped to crisp black.
_MULTICOLOUR_DITHERABLE: frozenset[str] = frozenset({"BG_ALT"})


def is_grayscale_palette(eink_palette: str) -> bool:
    """True if *eink_palette* reproduces grey acceptably via dithering."""
    return eink_palette in GRAYSCALE_PALETTES


def ditherable_tokens(eink_palette: str) -> frozenset[str]:
    """Token names reproduced via dithering for *eink_palette*."""
    if is_grayscale_palette(eink_palette):
        return DITHERABLE_TOKENS
    return _MULTICOLOUR_DITHERABLE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_rgb(color: tuple[int, int, int] | str) -> tuple[int, int, int]:
    if isinstance(color, str):
        return ImageColor.getrgb(color)
    return color


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def snap_to_palette(
    color: tuple[int, int, int] | str, eink_palette: str
) -> tuple[int, int, int]:
    """Return the panel colour nearest to *color* (squared Euclidean RGB distance)."""
    r, g, b = _to_rgb(color)
    colors = PANEL_COLORS.get(eink_palette, PANEL_COLORS["bw"])
    return min(
        colors,
        key=lambda c: (c[0] - r) ** 2 + (c[1] - g) ** 2 + (c[2] - b) ** 2,
    )


def resolve_palette(display_type: str, eink_palette: str) -> dict[str, str]:
    """Return the semantic palette for the target display.

    For ``hdmi`` the full day palette is returned unchanged.  For e-ink, tokens
    that are *ditherable* for the palette (see :func:`ditherable_tokens`) keep
    their original grey (reproduced via dithering); the rest are snapped to an
    exact panel colour.  On multicolour panels the secondary text/rules are
    additionally forced to solid black so they stay crisp and legible instead of
    becoming coloured noise — only the today highlight stays dithered.
    """
    base = get_palette()
    if display_type != "eink":
        return dict(base)

    grayscale = is_grayscale_palette(eink_palette)
    dith = ditherable_tokens(eink_palette)
    resolved: dict[str, str] = {}
    for name, hexcol in base.items():
        if name in dith:
            resolved[name] = hexcol  # keep grey — reproduced via dithering
        else:
            resolved[name] = _hex(snap_to_palette(hexcol, eink_palette))

    if not grayscale:
        # Keep secondary text/rules legible (the lightest greys would otherwise
        # snap to white).  BG_ALT is intentionally excluded — it stays dithered.
        for name in _MULTICOLOUR_BLACK_TOKENS:
            resolved[name] = "#000000"
    return resolved


def ditherable_color_values(eink_palette: str) -> frozenset[str]:
    """Day-palette hex values the renderer marks for dithering.

    These are the *original* (un-snapped) hex strings of the palette's ditherable
    tokens; the drawing facade recognises them by value to flag the corresponding
    pixels in the dither mask.
    """
    base = get_palette()
    return frozenset(base[name] for name in ditherable_tokens(eink_palette))


def flat_palette(eink_palette: str) -> list[int]:
    """Flat ``[r, g, b, r, g, b, ...]`` list for ``Image.putpalette`` / ``quantize``."""
    colors = PANEL_COLORS.get(eink_palette, PANEL_COLORS["bw"])
    return [channel for rgb in colors for channel in rgb]
