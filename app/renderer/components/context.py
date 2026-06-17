"""Shared drawing context for the Home-view components.

``RenderContext`` bundles the target image, its ``ImageDraw`` handle, the
resolved panel palette, the font set, and a parallel **dither mask**.  Its
drawing facade (``text``/``line``/``rectangle``/``ellipse``) automatically marks
the mask wherever a *ditherable* token colour is used, so the post-processor can
dither secondary greys while leaving primary text and fills crisp.

Decorative colours (event dots, weather icons) are snapped to an exact panel
colour via :meth:`RenderContext.snap` and therefore stay crisp (never masked).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from PIL import Image, ImageColor, ImageDraw, ImageFont

from app.renderer.emoji_icons import load_icon
from app.renderer.palette import (
    ditherable_color_values,
    is_grayscale_palette,
    snap_to_palette,
)
from app.renderer.tokens import (
    FONT_BODY_ITALIC,
    FONT_BODY_REGULAR,
    FONT_BODY_SEMIBOLD,
    FONT_DISPLAY_REGULAR,
    FONT_MONO_REGULAR,
    FONTS_DIR,
    TEXT_BASE,
    TEXT_LG,
    TEXT_MD,
    TEXT_SM,
    TEXT_XS,
)
from app.renderer.locale_it import DAY_NAMES_IT as _DAY_NAMES_IT

if TYPE_CHECKING:
    from zoneinfo import ZoneInfo

Color = "tuple[int, int, int] | str"


# ---------------------------------------------------------------------------
# Fonts
# ---------------------------------------------------------------------------

@dataclass
class Fonts:
    """The full set of fonts used across the Home view, loaded once."""

    display: ImageFont.FreeTypeFont
    body: ImageFont.FreeTypeFont
    date_num: ImageFont.FreeTypeFont
    label: ImageFont.FreeTypeFont
    event: ImageFont.FreeTypeFont
    mono: ImageFont.FreeTypeFont
    mono_xs: ImageFont.FreeTypeFont
    temp: ImageFont.FreeTypeFont
    hourly_temp: ImageFont.FreeTypeFont
    desc: ImageFont.FreeTypeFont
    desc_bold: ImageFont.FreeTypeFont
    desc_italic: ImageFont.FreeTypeFont
    icon_size_desc: int
    date_abbrev_slot_w: int


def _load_font(filename: str, size: int) -> ImageFont.FreeTypeFont:
    path = FONTS_DIR / filename
    if not path.exists():
        raise FileNotFoundError(
            f"PillowEinkRenderer: required font not found: {path}"
        )
    return ImageFont.truetype(str(path), size)


def build_fonts() -> Fonts:
    """Load every font used by the renderer (raises if any TTF is missing)."""
    label = _load_font(FONT_BODY_SEMIBOLD, TEXT_XS)
    # Widest Italian weekday abbreviation, so the day number sits at a fixed x.
    date_abbrev_slot_w = max(int(label.getlength(a)) for a in _DAY_NAMES_IT) + 2
    return Fonts(
        display=_load_font(FONT_DISPLAY_REGULAR, TEXT_LG),
        body=_load_font(FONT_BODY_REGULAR, TEXT_BASE),
        date_num=_load_font(FONT_BODY_REGULAR, TEXT_MD),
        label=label,
        event=_load_font(FONT_BODY_REGULAR, TEXT_XS),
        mono=_load_font(FONT_MONO_REGULAR, TEXT_SM),
        mono_xs=_load_font(FONT_MONO_REGULAR, TEXT_XS),
        temp=_load_font(FONT_BODY_SEMIBOLD, 40),
        hourly_temp=_load_font(FONT_BODY_SEMIBOLD, TEXT_SM),
        desc=_load_font(FONT_BODY_REGULAR, TEXT_XS),
        desc_bold=_load_font(FONT_BODY_SEMIBOLD, TEXT_XS),
        desc_italic=_load_font(FONT_BODY_ITALIC, TEXT_XS),
        icon_size_desc=max(8, int(TEXT_XS * 0.75)),
        date_abbrev_slot_w=date_abbrev_slot_w,
    )


# ---------------------------------------------------------------------------
# Render context + drawing facade
# ---------------------------------------------------------------------------

class RenderContext:
    """Holds the image, palette, fonts and dither mask for one render pass."""

    def __init__(
        self,
        img: Image.Image,
        palette: dict[str, str],
        fonts: Fonts,
        *,
        layout: str,
        display_type: str,
        eink_palette: str,
        tz: "ZoneInfo | None",
    ) -> None:
        self.img = img
        self.draw = ImageDraw.Draw(img)
        self.size: tuple[int, int] = img.size
        self.palette = palette
        self.fonts = fonts
        self.layout = layout
        self.display_type = display_type
        self.eink_palette = eink_palette
        self.is_eink = display_type == "eink"
        # Grayscale panels reproduce grey via dithering; multicolour panels snap
        # secondary UI to crisp colours (see app.renderer.palette).
        self.is_grayscale = is_grayscale_palette(eink_palette)
        self.tz = tz
        # Parallel mask: white (255) marks pixels the post-processor may dither.
        self.mask = Image.new("L", img.size, 0)
        self.mask_draw = ImageDraw.Draw(self.mask)
        self._ditherable_values = ditherable_color_values(eink_palette)

    # ------------------------------------------------------------------
    # Colour helpers
    # ------------------------------------------------------------------

    def snap(self, color: Color) -> tuple[int, int, int]:
        """Return *color* as an (r, g, b) tuple, snapped to the panel on e-ink."""
        if self.is_eink:
            return snap_to_palette(color, self.eink_palette)
        if isinstance(color, str):
            return ImageColor.getrgb(color)
        return color

    def snap_visible(self, color: Color) -> tuple[int, int, int]:
        """Like :meth:`snap`, but never returns the (white) background colour.

        Used for small decorative marks (event dots): a colour that snaps to
        white would be invisible on the white background, so fall back to black.
        """
        rgb = self.snap(color)
        if self.is_eink and rgb == (255, 255, 255):
            return (0, 0, 0)
        return rgb

    def _is_ditherable(self, fill: Color | None) -> bool:
        return (
            self.is_eink
            and isinstance(fill, str)
            and fill in self._ditherable_values
        )

    # ------------------------------------------------------------------
    # Drawing facade — marks the dither mask for ditherable token colours
    # ------------------------------------------------------------------

    def text(
        self,
        xy: tuple[float, float],
        text: str,
        *,
        font: ImageFont.FreeTypeFont,
        fill: Color,
        anchor: str | None = None,
    ) -> None:
        self.draw.text(xy, text, font=font, fill=fill, anchor=anchor)
        if text and self._is_ditherable(fill):
            bbox = self.draw.textbbox(xy, text, font=font, anchor=anchor)
            self.mask_draw.rectangle(bbox, fill=255)

    def line(self, xy, *, fill: Color, width: int = 1) -> None:
        self.draw.line(xy, fill=fill, width=width)
        if self._is_ditherable(fill):
            self.mask_draw.line(xy, fill=255, width=width)

    def rectangle(
        self, xy, *, fill: Color | None = None, outline: Color | None = None, width: int = 1
    ) -> None:
        self.draw.rectangle(xy, fill=fill, outline=outline, width=width)
        if self._is_ditherable(fill) or self._is_ditherable(outline):
            self.mask_draw.rectangle(xy, fill=255)

    def ellipse(
        self,
        xy,
        *,
        fill: Color | None = None,
        outline: Color | None = None,
        dither: bool = False,
    ) -> None:
        """Draw an ellipse, optionally reproducing *fill* via dithering.

        When ``dither=True`` the ellipse region is marked in the dither mask so
        the post-processor reproduces *fill* with Floyd-Steinberg dithering
        instead of snapping it to the nearest panel colour. The caller is
        responsible for passing the true (un-snapped) colour.
        """
        self.draw.ellipse(xy, fill=fill, outline=outline)
        if dither or self._is_ditherable(fill) or self._is_ditherable(outline):
            self.mask_draw.ellipse(xy, fill=255)

    def mark_dither(self, box: tuple[int, int, int, int]) -> None:
        """Explicitly mark a rectangular region for dithering (e.g. artwork)."""
        self.mask_draw.rectangle(box, fill=255)

    def unmark_dither(self, box: tuple[int, int, int, int]) -> None:
        """Clear a rectangular region from the dither mask (keep it crisp)."""
        self.mask_draw.rectangle(box, fill=0)

    def draw_icon(
        self,
        name: str,
        size: int,
        xy: tuple[int, int],
        color: Color,
        *,
        dither: bool = False,
    ) -> bool:
        """Composite a recoloured icon at top-left *xy*; returns ``True`` if drawn.

        When ``dither=False`` (default) the colour is snapped to the nearest panel
        colour so the icon stays crisp.  When ``dither=True`` the original colour
        is kept and the icon bounding box is marked in the dither mask so the
        post-processor reproduces it via Floyd-Steinberg dithering.
        """
        icon_img = load_icon(name, size)
        if icon_img is None:
            return False
        if dither:
            r, g, b = ImageColor.getrgb(color) if isinstance(color, str) else color
            iw, ih = icon_img.size
            self.mask_draw.rectangle(
                [xy[0], xy[1], xy[0] + iw - 1, xy[1] + ih - 1], fill=255
            )
        else:
            r, g, b = self.snap_visible(color)
        _, _, _, alpha = icon_img.split()
        tinted = Image.new("RGBA", icon_img.size, (r, g, b, 255))
        tinted.putalpha(alpha)
        self.img.paste(tinted, xy, mask=tinted)
        return True

    def attach_mask(self) -> None:
        """Attach the accumulated dither mask to the image's ``info`` dict."""
        self.img.info["dither_mask"] = self.mask
