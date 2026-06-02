"""Footer — top rule and right-aligned "last updated" timestamp."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.renderer.components.context import RenderContext

Rect = tuple[int, int, int, int]


def draw_footer(
    ctx: "RenderContext",
    rect: Rect,
    updated_at: datetime | None = None,
) -> None:
    x0, y0, w, h = rect
    palette = ctx.palette
    fonts = ctx.fonts

    # Top separator
    ctx.line([(x0, y0), (x0 + w, y0)], fill=palette["RULE"])

    # *updated_at* riflette l'ultima variazione dei dati, non il mero repaint;
    # se assente (anteprima web / HDMI) si usa l'ora corrente.
    ts = updated_at or datetime.now()
    status_text = f"Ultimo aggiornamento: {ts.strftime('%H:%M')}"
    _bbox = ctx.draw.textbbox((0, 0), status_text, font=fonts.label)
    _text_h = _bbox[3] - _bbox[1]
    ctx.text(
        (x0 + w - 12, y0 + h - 4 - _text_h),
        status_text,
        font=fonts.label,
        fill=palette["INK_MUTED"],
        anchor="rb",
    )
