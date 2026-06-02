"""Shared text-measurement and rich/mixed-text drawing helpers.

These functions are display-agnostic except where they draw, in which case they
go through the :class:`~app.renderer.components.context.RenderContext` facade so
that ditherable token colours are recorded in the dither mask.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PIL import ImageDraw, ImageFont

from app.renderer.emoji_icons import split_text_emoji
from app.renderer.rich_text import RichLine, RichSpan, parse_html_description

if TYPE_CHECKING:
    from app.renderer.components.context import Fonts, RenderContext


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Convert a ``#rrggbb`` colour string to an (r, g, b) tuple."""
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def ellipsize(text: str, font: "ImageFont.FreeTypeFont", max_width: int) -> str:
    """Return the longest prefix of *text* that fits in *max_width* px, with '…'.

    Returns ``""`` if even the ellipsis alone exceeds *max_width*.
    """
    if font.getlength(text) <= max_width:
        return text
    ellipsis_w = font.getlength("…")
    if ellipsis_w > max_width:
        return ""
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if font.getlength(text[:mid]) + ellipsis_w <= max_width:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo] + "…" if lo > 0 else ""


# ---------------------------------------------------------------------------
# Mixed text + inline-icon rendering
# ---------------------------------------------------------------------------

def measure_mixed(
    draw: ImageDraw.ImageDraw,
    segments: list[tuple[str, str]],
    font: ImageFont.FreeTypeFont,
    icon_size: int,
) -> float:
    """Return the total pixel width of *segments* (text + icons)."""
    total = 0.0
    for seg_type, content in segments:
        if seg_type == "text":
            if content:
                bb = draw.textbbox((0, 0), content, font=font)
                total += bb[2] - bb[0]
        else:
            total += icon_size + 1  # icon width + 1 px inter-icon gap
    return total


def fit_mixed(
    draw: ImageDraw.ImageDraw,
    segments: list[tuple[str, str]],
    font: ImageFont.FreeTypeFont,
    icon_size: int,
    max_width: float,
) -> list[tuple[str, str]]:
    """Truncate *segments* so their total width fits within *max_width*.

    The last visible element is followed by '…' when content is cut.
    """
    if max_width <= 0:
        return []
    if measure_mixed(draw, segments, font, icon_size) <= max_width:
        return list(segments)

    ellipsis_w = draw.textbbox((0, 0), "…", font=font)[2]
    budget = max_width - ellipsis_w
    result: list[tuple[str, str]] = []
    cur_w = 0.0

    for seg_type, content in segments:
        if seg_type == "text":
            bb = draw.textbbox((0, 0), content, font=font) if content else (0, 0, 0, 0)
            seg_w = bb[2] - bb[0]
            if cur_w + seg_w <= budget:
                result.append(("text", content))
                cur_w += seg_w
            else:
                # Binary-search the longest substring that fits
                remaining = budget - cur_w
                if remaining > 0:
                    lo, hi = 0, len(content)
                    while lo < hi:
                        mid = (lo + hi + 1) // 2
                        b = draw.textbbox((0, 0), content[:mid], font=font)
                        if b[2] - b[0] <= remaining:
                            lo = mid
                        else:
                            hi = mid - 1
                    if lo > 0:
                        result.append(("text", content[:lo]))
                result.append(("text", "…"))
                return result
        else:  # "icon"
            seg_w = icon_size + 1
            if cur_w + seg_w <= budget:
                result.append((seg_type, content))
                cur_w += seg_w
            else:
                result.append(("text", "…"))
                return result

    result.append(("text", "…"))
    return result


def draw_mixed(
    ctx: "RenderContext",
    segments: list[tuple[str, str]],
    x: int,
    y: int,
    font: ImageFont.FreeTypeFont,
    fill: str,
    icon_size: int,
) -> None:
    """Render *segments* left-to-right starting at (*x*, *y* middle-left).

    Text segments use ``anchor="lm"``; icon segments are composited onto the
    image recoloured to *fill*.
    """
    cur_x = x
    for seg_type, content in segments:
        if seg_type == "text":
            if content:
                ctx.text((cur_x, y), content, font=font, fill=fill, anchor="lm")
                bb = ctx.draw.textbbox((0, 0), content, font=font)
                cur_x += bb[2] - bb[0]
        else:  # "icon"
            if ctx.draw_icon(content, icon_size, (cur_x, y - icon_size // 2), fill):
                cur_x += icon_size + 1


# ---------------------------------------------------------------------------
# Rich text (HTML descriptions)
# ---------------------------------------------------------------------------

def span_font(span: RichSpan, fonts: "Fonts") -> ImageFont.FreeTypeFont:
    """Return the correct description font for *span*'s inline style."""
    if span.bold:
        return fonts.desc_bold
    if span.italic:
        return fonts.desc_italic
    return fonts.desc


def measure_span_text(
    text: str, font: ImageFont.FreeTypeFont, icon_size_desc: int
) -> float:
    """Measure pixel width of *text*, treating emoji as inline icons."""
    total = 0.0
    for seg_type, content in split_text_emoji(text):
        if seg_type == "text":
            total += font.getlength(content)
        else:  # icon
            total += icon_size_desc + 1
    return total


def wrap_rich_lines(
    lines: list[RichLine],
    max_w: int,
    fonts: "Fonts",
    max_lines: int = 10,
) -> list[RichLine]:
    """Wrap logical RichLines into visual lines that fit within *max_w* px.

    Words are split at space boundaries.  A single word wider than max_w is
    placed alone on its line and truncated with '…'.  Output is capped at
    *max_lines*.
    """
    wrapped: list[RichLine] = []

    for line in lines:
        if len(wrapped) >= max_lines:
            break

        # Tokenise: split each span's text at spaces into atomic tokens
        tokens: list[tuple[str, bool, bool, bool, bool]] = []
        for span in line:
            if not span.text:
                continue
            parts = span.text.split(" ")
            for i, part in enumerate(parts):
                if i > 0:
                    tokens.append((" ", span.bold, span.italic, span.underline, span.is_link))
                if part:
                    tokens.append((part, span.bold, span.italic, span.underline, span.is_link))

        current: list[RichSpan] = []
        current_w = 0.0

        def _flush() -> None:
            nonlocal current, current_w
            # Strip trailing space from the last span
            if current:
                last = current[-1]
                stripped = last.text.rstrip(" ")
                if stripped != last.text:
                    current[-1] = RichSpan(text=stripped, bold=last.bold, italic=last.italic,
                                           underline=last.underline, is_link=last.is_link)
            if any(s.text for s in current):
                wrapped.append(current)
            current = []
            current_w = 0.0

        for text, bold, italic, underline, is_link in tokens:
            if len(wrapped) >= max_lines:
                break
            font = fonts.desc_bold if bold else (
                fonts.desc_italic if italic else fonts.desc
            )
            tw = measure_span_text(text, font, fonts.icon_size_desc)

            # Skip leading space at the start of a new visual line
            if text == " " and current_w == 0.0:
                continue

            if current_w + tw <= max_w or current_w == 0.0:
                new_span = RichSpan(text=text, bold=bold, italic=italic,
                                    underline=underline, is_link=is_link)
                # Merge with previous span if same style
                if (current
                        and current[-1].bold == bold
                        and current[-1].italic == italic
                        and current[-1].underline == underline
                        and current[-1].is_link == is_link):
                    current[-1] = RichSpan(
                        text=current[-1].text + text,
                        bold=bold, italic=italic,
                        underline=underline, is_link=is_link,
                    )
                else:
                    current.append(new_span)
                current_w += tw
            else:
                _flush()
                if len(wrapped) >= max_lines:
                    break
                if text == " ":
                    pass  # dropped — leading space on new line
                else:
                    # Truncate if even a single word exceeds max_w
                    if tw > max_w:
                        text = ellipsize(text, font, max_w)
                        tw = font.getlength(text)
                    current = [RichSpan(text=text, bold=bold, italic=italic,
                                        underline=underline, is_link=is_link)]
                    current_w = tw

        if len(wrapped) < max_lines:
            _flush()

    return wrapped


def draw_rich_description(
    ctx: "RenderContext",
    lines: list[RichLine],
    x0: int,
    y0: int,
    max_w: int,
    max_lines: int = 10,
) -> None:
    """Render *lines* as rich text starting at (*x0*, *y0* top-left).

    Each line occupies ``desc.size + 4`` px vertically.  Spans use Bold / Italic /
    Regular fonts as indicated; underlines and links are decorated with a 1 px
    rule below the text.  Emoji sequences are rendered as inline icon images.
    Secondary colours (INK_MUTED / INK_FAINT) are recorded in the dither mask.
    """
    visual_lines = wrap_rich_lines(lines, max_w, ctx.fonts, max_lines=max_lines)
    line_h = ctx.fonts.desc.size + 4
    icon_size = ctx.fonts.icon_size_desc

    for line_idx, line in enumerate(visual_lines):
        cy = y0 + line_idx * line_h + line_h // 2
        cx = float(x0)
        for span in line:
            if not span.text:
                continue
            font = span_font(span, ctx.fonts)
            color = ctx.palette["INK_MUTED"] if span.is_link else ctx.palette["INK_FAINT"]
            for seg_type, content in split_text_emoji(span.text):
                if seg_type == "text":
                    if not content:
                        continue
                    seg_w = font.getlength(content)
                    ctx.text((int(cx), cy), content, font=font, fill=color, anchor="lm")
                    if span.underline or span.is_link:
                        uy = cy + font.size // 2 + 1
                        ctx.line(
                            [(int(cx), uy), (int(cx + seg_w), uy)], fill=color, width=1
                        )
                    cx += seg_w
                else:  # "icon"
                    ctx.draw_icon(content, icon_size, (int(cx), cy - icon_size // 2), color)
                    cx += icon_size + 1


# Re-exported for callers that build descriptions then measure/draw them.
__all__ = [
    "hex_to_rgb",
    "ellipsize",
    "measure_mixed",
    "fit_mixed",
    "draw_mixed",
    "span_font",
    "measure_span_text",
    "wrap_rich_lines",
    "draw_rich_description",
    "parse_html_description",
]
