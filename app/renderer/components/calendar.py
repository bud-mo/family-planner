"""Mini-calendar — rolling 5-week grid with per-cell event lines."""
from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from app.calendar.data_builders import _build_rolling_week_grid
from app.renderer.components.text import ellipsize
from app.renderer.locale_it import (
    DAY_NAMES_IT as _DAY_NAMES_IT,
    MONTH_NAMES_IT as _MONTH_NAMES_IT,
)
from app.renderer.state import NavigationState

if TYPE_CHECKING:
    from app.calendar.base import CalendarEvent
    from app.renderer.components.context import RenderContext

Rect = tuple[int, int, int, int]


def draw_mini_calendar(
    ctx: "RenderContext",
    rect: Rect,
    state: NavigationState,
    events: list["CalendarEvent"],
) -> None:
    x0, y0, w, h = rect
    palette = ctx.palette
    fonts = ctx.fonts
    today = date.today()
    weeks = _build_rolling_week_grid(state.anchor_date, events, today)
    N_ROWS = 5

    dow_header_h = 24
    separator_h = 40  # height reserved for each between-row month separator

    # DOW header
    dow_y = y0 + dow_header_h // 2
    cell_w = w / 7
    for i, name in enumerate(_DAY_NAMES_IT):
        cx = x0 + i * cell_w + cell_w / 2
        ctx.text(
            (cx, dow_y),
            name,
            font=fonts.label,
            fill=palette["INK_MUTED"],
            anchor="mm",
        )

    # Determine which rows are preceded by a month separator
    sep_before_rows: set[int] = {
        i
        for i in range(1, N_ROWS)
        if weeks[i][0]["date"].month != weeks[i - 1][0]["date"].month
    }
    total_sep_h = len(sep_before_rows) * separator_h

    grid_top = y0 + dow_header_h
    grid_h = h - dow_header_h
    cell_h = (grid_h - total_sep_h) / N_ROWS

    # Cell layout constants
    day_area_h = 24    # height reserved for the day number at the top of each cell
    event_line_h = 20  # TEXT_XS (18px) + 2px gap
    cell_pad_x = 3     # horizontal margin inside cell for event text
    dot_r = 3          # radius of the calendar-colour dot

    available_event_h = int(cell_h) - day_area_h - 1
    max_event_lines = max(1, available_event_h // event_line_h)

    text_x_offset = cell_pad_x + dot_r * 2 + 3  # dot_diam(6) + gap(3)
    max_text_w = int(cell_w) - text_x_offset - cell_pad_x

    cum_y = grid_top
    for row_idx, week in enumerate(weeks):
        # Month separator: a full-width label row between weeks at month boundary
        if row_idx in sep_before_rows:
            sep_date = week[0]["date"]
            sep_label = (
                f"{_MONTH_NAMES_IT[sep_date.month - 1].upper()} {sep_date.year}"
            )
            ctx.text(
                (x0 + w // 2, cum_y + separator_h // 2),
                sep_label,
                font=fonts.label,
                fill=palette["INK"],
                anchor="mm",
            )
            cum_y += separator_h

        row_top_y = cum_y

        for col_idx, cell in enumerate(week):
            cx0 = x0 + col_idx * cell_w
            cy0 = row_top_y
            cx_mid = cx0 + cell_w / 2

            day_num_cy = cy0 + 1 + day_area_h // 2

            if cell["is_today"]:
                # Filled highlight for today.  On grayscale panels this is the
                # design grey, reproduced via dithering; on multicolour panels
                # BG_ALT resolves to a solid panel colour (see resolve_palette),
                # so the fill is crisp and free of coloured dither noise.
                ctx.rectangle(
                    [cx0, cy0, cx0 + cell_w - 1, cy0 + cell_h - 1],
                    fill=palette["BG_ALT"],
                )
                ink = palette["INK"]
                event_ink = palette["INK"]
            else:
                ink = palette["INK"]
                event_ink = palette["INK"] if cell["date"] >= today else palette["INK_MUTED"]

            ctx.text(
                (cx_mid, day_num_cy),
                str(cell["day_number"]),
                font=fonts.label,
                fill=ink,
                anchor="mm",
            )

            cell_events = cell["events"]
            if not cell_events or max_event_lines == 0:
                continue

            cell_events = sorted(cell_events, key=lambda e: (not e.all_day, e.start))
            n_events = len(cell_events)

            if n_events <= max_event_lines:
                events_to_show = cell_events
                overflow_count = 0
            else:
                events_to_show = cell_events[: max_event_lines - 1]
                overflow_count = n_events - len(events_to_show)

            event_area_top = cy0 + day_area_h + 1

            for line_idx, evt in enumerate(events_to_show):
                line_top = int(event_area_top + line_idx * event_line_h)
                line_y = line_top + event_line_h // 2
                # Coloured dot — snapped to a visible panel colour on e-ink.
                dot_color = evt.color if evt.color else palette["INK_FAINT"]
                try:
                    dot_fill = ctx.snap_visible(dot_color)
                except (ValueError, AttributeError):
                    dot_fill = ctx.snap_visible(palette["INK_FAINT"])
                dot_cx = int(cx0 + cell_pad_x) + dot_r
                ctx.ellipse(
                    [(dot_cx - dot_r, line_y - dot_r), (dot_cx + dot_r, line_y + dot_r)],
                    fill=dot_fill,
                )
                text = ellipsize(evt.title, fonts.event, max_text_w)
                if text:
                    ctx.text(
                        (cx0 + text_x_offset, line_y),
                        text,
                        font=fonts.event,
                        fill=event_ink,
                        anchor="lm",
                    )

            if overflow_count > 0:
                overflow_y = (
                    event_area_top + len(events_to_show) * event_line_h + event_line_h // 2
                )
                overflow_fill = palette["INK"] if cell["date"] >= today else palette["INK_FAINT"]
                ctx.text(
                    (cx0 + text_x_offset, overflow_y),
                    f"+{overflow_count}",
                    font=fonts.event,
                    fill=overflow_fill,
                    anchor="lm",
                )

        cum_y += cell_h

    # Bottom separator (portrait only)
    if ctx.layout == "portrait":
        ctx.line(
            [(x0, y0 + h - 1), (x0 + w, y0 + h - 1)],
            fill=palette["RULE_STRONG"],
            width=1,
        )
