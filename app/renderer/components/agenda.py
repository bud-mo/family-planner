"""Agenda — a 30-day vertical list of events grouped by day."""
from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING

from PIL import ImageColor

from app.renderer.components.text import (
    draw_mixed,
    draw_rich_description,
    fit_mixed,
    parse_html_description,
    wrap_rich_lines,
)
from app.calendar.data_builders import event_local_dates
from app.renderer.emoji_icons import split_text_emoji
from app.renderer.locale_it import DAY_NAMES_IT as _DAY_NAMES_IT
from app.renderer.state import NavigationState
from app.renderer.tokens import TEXT_XS

if TYPE_CHECKING:
    from app.calendar.base import CalendarEvent
    from app.renderer.components.context import RenderContext

Rect = tuple[int, int, int, int]


def format_event_short(ctx: "RenderContext", evt: "CalendarEvent") -> str:
    """Return a compact display string: 'HH:MM Title' for timed events, 'Title' for all-day."""
    if evt.all_day:
        return evt.title
    local_start = evt.start.astimezone(ctx.tz) if ctx.tz else evt.start
    return f"{local_start.strftime('%H:%M')} {evt.title}"


def draw_agenda(
    ctx: "RenderContext",
    rect: Rect,
    state: NavigationState,
    events: list["CalendarEvent"],
) -> None:
    x0, y0, w, h = rect
    palette = ctx.palette
    fonts = ctx.fonts

    # Left column separator (landscape only)
    if ctx.layout == "landscape":
        ctx.line([(x0, y0), (x0, y0 + h)], fill=palette["RULE_STRONG"], width=1)

    padding_x = 12
    date_col_w = 84
    event_row_h = 60
    time_col_w = 200

    _WINDOW_DAYS = 30
    window_start = state.anchor_date
    window_end = state.anchor_date + timedelta(days=_WINDOW_DAYS - 1)

    days_events: dict[date, list] = {}
    for d_offset in range(_WINDOW_DAYS):
        days_events[window_start + timedelta(days=d_offset)] = []

    for evt in events:
        # Multi-day events are listed under every day they span.
        for evt_date in event_local_dates(evt, None if evt.all_day else ctx.tz):
            if window_start <= evt_date <= window_end:
                days_events[evt_date].append(evt)

    for d in days_events:
        days_events[d].sort(key=lambda e: (not e.all_day, e.start))

    # Empty state
    has_events = any(len(v) > 0 for v in days_events.values())
    if not has_events:
        ctx.text(
            (x0 + w // 2, y0 + h // 2),
            "Nessun appuntamento",
            font=fonts.label,
            fill=palette["INK_FAINT"],
            anchor="mm",
        )
        return

    # Build ordered list: (day, event, multiday_index, multiday_total) — skip
    # days with no events.  ``show_details`` below suppresses the repeated
    # location/description on the continuation days of a multi-day event.
    items: list[tuple[date, object, int, int]] = []
    for d_offset in range(_WINDOW_DAYS):
        day = window_start + timedelta(days=d_offset)
        if not days_events[day]:
            continue
        for evt in days_events[day]:
            span = event_local_dates(evt, None if evt.all_day else ctx.tz)
            total = len(span) if len(span) > 1 else 0
            index = span.index(day) + 1 if total else 0
            items.append((day, evt, index, total))

    def _show_details(index: int, total: int) -> bool:
        return not (total > 1 and index > 1)

    _desc_max_w = w - (padding_x + date_col_w + time_col_w + 8 + 8)

    def _row_height(evt: object, max_desc_lines: int = 10, show_details: bool = True) -> int:
        has_loc = bool(getattr(evt, "location", None)) and show_details
        desc_raw: str = (getattr(evt, "description", None) or "") if show_details else ""
        if desc_raw and max_desc_lines > 0:
            rich_lines = parse_html_description(desc_raw, max_lines=max_desc_lines)
            wrapped = wrap_rich_lines(rich_lines, _desc_max_w, fonts, max_lines=max_desc_lines)
            if wrapped:
                return 60 + (20 if has_loc else 0) + len(wrapped) * (TEXT_XS + 4) + 8
        return 60 + (28 if has_loc else 0)

    # First pass: determine what fits and count overflow
    cur_y = y0
    max_y = y0 + h
    rendered: list[tuple[date, object, int, int, int]] = []
    remaining_count = 0
    in_overflow = False

    for day, evt, index, total in items:
        if in_overflow:
            remaining_count += 1
            continue

        show_details = _show_details(index, total)
        full_h = _row_height(evt, 10, show_details)
        available = max_y - cur_y - event_row_h

        if full_h <= available:
            rendered.append((day, evt, 10, index, total))
            cur_y += full_h
        else:
            base_h = _row_height(evt, 0, show_details)  # height with no description
            if base_h > available:
                in_overflow = True
                remaining_count += 1
                continue

            has_desc = show_details and bool(getattr(evt, "description", None))
            if has_desc:
                max_lines_fit = max(0, (available - base_h - 8) // (TEXT_XS + 4))
                max_lines_fit = min(10, max_lines_fit)
            else:
                max_lines_fit = 0

            effective_h = _row_height(evt, max_lines_fit, show_details)
            rendered.append((day, evt, max_lines_fit, index, total))
            cur_y += effective_h

    # Second pass: draw
    cur_y = y0
    prev_day: date | None = None
    is_first_rendered = True
    for day, evt, max_desc_lines, index, total in rendered:
        first_in_day = day != prev_day
        show_details = _show_details(index, total)
        row_h_item = _row_height(evt, max_desc_lines, show_details)
        _draw_event_row(
            ctx, evt, x0, cur_y, w, row_h_item,
            padding_x, time_col_w, date_col_w,
            day_date=day if first_in_day else None,
            draw_top_separator=not is_first_rendered,
            max_desc_lines=max_desc_lines if show_details else 0,
            multiday_index=index,
            multiday_total=total,
            show_details=show_details,
        )
        cur_y += row_h_item
        prev_day = day
        is_first_rendered = False

    # Overflow indicator
    if remaining_count > 0 and cur_y + event_row_h <= max_y:
        ctx.text(
            (x0 + w // 2, cur_y + event_row_h // 2),
            f"… altri {remaining_count} appuntamenti",
            font=fonts.label,
            fill=palette["INK_MUTED"],
            anchor="mm",
        )


def _draw_event_row(
    ctx: "RenderContext",
    evt: "CalendarEvent",
    x0: int,
    y0: int,
    w: int,
    row_h: int,
    padding_x: int,
    time_col_w: int,
    date_col_w: int,
    day_date: date | None = None,
    draw_top_separator: bool = True,
    max_desc_lines: int = 10,
    multiday_index: int = 0,
    multiday_total: int = 0,
    show_details: bool = True,
) -> None:
    palette = ctx.palette
    fonts = ctx.fonts
    first_in_day = day_date is not None

    # Horizontal separator
    if draw_top_separator and first_in_day:
        ctx.line([(x0 + padding_x, y0), (x0 + w, y0)], fill=palette["RULE_STRONG"], width=1)

    # --- Date column ---
    if day_date is not None:
        date_col_right = x0 + padding_x + date_col_w - 4
        day_abbrev = _DAY_NAMES_IT[day_date.weekday()]
        ctx.text(
            (date_col_right, y0 + 30),
            day_abbrev,
            font=fonts.label,
            fill=palette["INK_MUTED"],
            anchor="rm",
        )
        ctx.text(
            (date_col_right - fonts.date_abbrev_slot_w - 5, y0 + 30),
            str(day_date.day),
            font=fonts.date_num,
            fill=palette["INK"],
            anchor="rm",
        )

    # --- Time column ---
    time_area_x = x0 + padding_x + date_col_w
    sep_x = time_area_x + time_col_w
    time_y = y0 + 30

    # Coloured dot — always reproduced via dithering so the true calendar
    # colour survives on e-ink instead of being snapped to a panel colour.
    raw_color = getattr(evt, "color", "") or ""
    dot_color = raw_color if (raw_color.startswith("#") and len(raw_color) == 7) else palette["RULE"]
    try:
        dot_rgb = ImageColor.getrgb(dot_color)
    except ValueError:
        dot_rgb = ImageColor.getrgb(palette["RULE"])
    dot_r = 7
    time_col_pad = 8
    dot_cx = time_area_x + time_col_pad + dot_r
    ctx.ellipse(
        [(dot_cx - dot_r, time_y - dot_r), (dot_cx + dot_r, time_y + dot_r)],
        fill=dot_rgb,
        dither=True,
    )

    # Time text — single line to the right of the dot.  Multi-day events show a
    # "Giorno X/N" counter (all-day) or directional arrows (timed) so each
    # occurrence reads as part of a span rather than a separate event.
    time_text_x = time_area_x + time_col_pad + dot_r * 2 + 6
    multiday = multiday_total > 1
    if evt.all_day:
        time_str = f"Giorno {multiday_index}/{multiday_total}" if multiday else "Tutto il giorno"
    else:
        local_start = evt.start.astimezone(ctx.tz) if ctx.tz else evt.start
        local_end = evt.end.astimezone(ctx.tz) if ctx.tz else evt.end
        if not multiday:
            time_str = f"{local_start.strftime('%H:%M')} - {local_end.strftime('%H:%M')}"
        elif multiday_index == 1:
            time_str = f"{local_start.strftime('%H:%M')} →"
        elif multiday_index == multiday_total:
            time_str = f"→ {local_end.strftime('%H:%M')}"
        else:
            time_str = "↔ tutto il giorno"
    ctx.text(
        (time_text_x, time_y),
        time_str,
        font=fonts.mono_xs,
        fill=palette["INK"],
        anchor="lm",
    )

    # --- Content ---
    title_x = sep_x + 8
    title_max_w = w - (title_x - x0) - 8
    icon_size_title = int(fonts.body.size * 0.75)
    title_segs = split_text_emoji(evt.title)
    title_segs = fit_mixed(ctx.draw, title_segs, fonts.body, icon_size_title, title_max_w)
    draw_mixed(ctx, title_segs, title_x, time_y, fonts.body, palette["INK"], icon_size_title)

    icon_size_sub = int(fonts.label.size * 0.75)
    show_loc = bool(evt.location) and show_details
    show_desc = bool(evt.description) and show_details
    loc_y: int | None = (y0 + 70) if show_loc else None
    desc_block_y: int | None = None
    if show_desc and max_desc_lines > 0:
        desc_block_y = y0 + 60 + (20 if show_loc else 0)

    if show_loc and loc_y is not None:
        loc_text = evt.location.replace("\r\n", " · ").replace("\n", " · ")
        loc_segs = split_text_emoji(loc_text)
        loc_segs = fit_mixed(ctx.draw, loc_segs, fonts.label, icon_size_sub, title_max_w)
        draw_mixed(ctx, loc_segs, title_x, loc_y, fonts.label, palette["INK_MUTED"], icon_size_sub)

    if show_desc and desc_block_y is not None:
        rich_lines = parse_html_description(evt.description, max_lines=max_desc_lines)
        if rich_lines:
            draw_rich_description(
                ctx, rich_lines, title_x, desc_block_y, title_max_w,
                max_lines=max_desc_lines,
            )
