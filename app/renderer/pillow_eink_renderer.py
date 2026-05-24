"""Pillow-native renderer for Family Planner — Home view.

Single-screen layout: weather banner · mini-calendar · agenda · footer.

``PillowEinkRenderer`` renders a ``PIL.Image`` directly from ``NavigationState``
and a list of ``CalendarEvent`` objects, without involving a browser or network.
It is the sole renderer for both HDMI (pygame) and e-ink (Waveshare) displays.

Usage::

    renderer = PillowEinkRenderer(config)
    state = NavigationState()
    start, end = events_range_for_state(state)
    events = aggregator.get_events(start, end)
    img = renderer.render(state, events)      # PIL.Image RGB
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from PIL import Image, ImageColor, ImageDraw, ImageFont

from app.calendar.data_builders import _build_month_grid, _build_rolling_week_grid
from app.renderer.emoji_icons import load_icon, split_text_emoji
from app.renderer.state import NavigationState
from app.renderer.tokens import (
    BANNER_HEIGHT,
    CALENDAR_HEIGHT,
    COL_LEFT_RATIO,
    FONT_BODY_REGULAR,
    FONT_BODY_SEMIBOLD,
    FONT_DISPLAY_REGULAR,
    FONT_MONO_REGULAR,
    FONTS_DIR,
    FOOTER_HEIGHT,
    Rect,
    TEXT_BASE,
    TEXT_LG,
    TEXT_MD,
    TEXT_SM,
    TEXT_XL,
    TEXT_XS,
    WeatherData,
    get_palette,
)

if TYPE_CHECKING:
    from app.calendar.base import CalendarEvent
    from app.config import AppConfig
    from app.weather.provider import WeatherProvider

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Locale strings (private — not imported from other modules to avoid coupling)
# ---------------------------------------------------------------------------
# Locale strings
# ---------------------------------------------------------------------------

_MONTH_NAMES_IT: list[str] = [
    "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
    "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre",
]
_DAY_NAMES_IT: list[str] = ["LUN", "MAR", "MER", "GIO", "VEN", "SAB", "DOM"]
_DAY_NAMES_FULL_IT: list[str] = [
    "Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica",
]
_MONTH_NAMES_SHORT_IT: list[str] = [
    "GEN", "FEB", "MAR", "APR", "MAG", "GIU",
    "LUG", "AGO", "SET", "OTT", "NOV", "DIC",
]


class PillowEinkRenderer:
    """Renders the Home view as a ``PIL.Image``.

    Args:
        config: Full application config. ``config.display`` supplies canvas
                dimensions, layout, and display type; ``config.timezone``
                localises event times.

    Raises:
        FileNotFoundError: If any required TTF font file is missing from
            ``app/assets/fonts/``.
    """

    def __init__(
        self,
        config: "AppConfig",
        weather_provider: "WeatherProvider | None" = None,
    ) -> None:
        self._size: tuple[int, int] = (config.display.width, config.display.height)
        self._layout: str = config.display.layout
        self._display_type: str = config.display.type
        self._weather_provider = weather_provider

        tz_name: str = getattr(config, "timezone", "local")
        if tz_name and tz_name != "local":
            try:
                self._tz: ZoneInfo | None = ZoneInfo(tz_name)
            except (KeyError, ZoneInfoNotFoundError):
                logger.warning(
                    "PillowEinkRenderer: unknown timezone %r — using event-native tz",
                    tz_name,
                )
                self._tz = None
        else:
            self._tz = None

        self._font_display: ImageFont.FreeTypeFont = self._load_font(FONT_DISPLAY_REGULAR, TEXT_LG)
        self._font_body: ImageFont.FreeTypeFont = self._load_font(FONT_BODY_REGULAR, TEXT_BASE)
        self._font_date_num: ImageFont.FreeTypeFont = self._load_font(FONT_BODY_REGULAR, TEXT_MD)
        self._font_label: ImageFont.FreeTypeFont = self._load_font(FONT_BODY_SEMIBOLD, TEXT_XS)
        self._font_event: ImageFont.FreeTypeFont = self._load_font(FONT_BODY_REGULAR, TEXT_XS)
        self._font_mono: ImageFont.FreeTypeFont = self._load_font(FONT_MONO_REGULAR, TEXT_SM)
        self._font_temp: ImageFont.FreeTypeFont = self._load_font(FONT_BODY_SEMIBOLD, 40)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def render(
        self,
        state: NavigationState,
        events: list["CalendarEvent"],
    ) -> Image.Image:
        """Render the Home view for *state* and *events* as an RGB ``PIL.Image``."""
        W, H = self._size
        palette = get_palette()
        img = Image.new("RGB", (W, H), palette["BG"])
        draw = ImageDraw.Draw(img)

        weather = (
            self._weather_provider.get()
            if self._weather_provider is not None
            else WeatherData()
        )

        if self._layout == "portrait":
            weather_rect: Rect = (0, 0, W, BANNER_HEIGHT)
            calendar_rect: Rect = (0, BANNER_HEIGHT, W, CALENDAR_HEIGHT)
            agenda_rect: Rect = (
                0,
                BANNER_HEIGHT + CALENDAR_HEIGHT,
                W,
                H - BANNER_HEIGHT - CALENDAR_HEIGHT - FOOTER_HEIGHT,
            )
            footer_rect: Rect = (0, H - FOOTER_HEIGHT, W, FOOTER_HEIGHT)
        else:  # landscape
            col_left = int(W * COL_LEFT_RATIO)
            col_right = W - col_left
            weather_rect = (0, 0, col_left, BANNER_HEIGHT)
            calendar_rect = (0, BANNER_HEIGHT, col_left, H - BANNER_HEIGHT - FOOTER_HEIGHT)
            agenda_rect = (col_left, 0, col_right, H - FOOTER_HEIGHT)
            footer_rect = (0, H - FOOTER_HEIGHT, W, FOOTER_HEIGHT)

        self._draw_weather(draw, img, weather_rect, weather, palette)
        self._draw_mini_calendar(draw, calendar_rect, state, events, palette)
        self._draw_agenda(draw, img, agenda_rect, state, events, palette)
        self._draw_footer(draw, footer_rect, palette)
        return img

    # ------------------------------------------------------------------
    # Weather banner
    # ------------------------------------------------------------------

    def _draw_weather(
        self,
        draw: ImageDraw.ImageDraw,
        img: Image.Image,
        rect: Rect,
        weather: WeatherData,
        palette: dict[str, str],
    ) -> None:
        x0, y0, w, h = rect
        today = date.today()
        date_str = (
            f"{_DAY_NAMES_FULL_IT[today.weekday()]}, "
            f"{today.day} {_MONTH_NAMES_IT[today.month - 1]} {today.year}"
        )
        y_mid = y0 + h // 2
        draw.text(
            (x0 + 12, y_mid),
            date_str,
            font=self._font_display,
            fill=palette["INK"],
            anchor="lm",
        )

        right_x = x0 + w - 12

        if weather.temp_current is not None:
            # Horizontal layout (right-to-left):
            #   [icon 40px] | [temp 40px] | [↑max / ↓min stacked]
            has_maxmin = weather.temp_max is not None and weather.temp_min is not None

            # Step 1: measure max/min column width (rightmost block)
            maxmin_col_w = 0
            if has_maxmin:
                max_str = f"\u2191{weather.temp_max:.0f}°"
                min_str = f"\u2193{weather.temp_min:.0f}°"
                maxmin_col_w = max(
                    int(draw.textlength(max_str, font=self._font_label)),
                    int(draw.textlength(min_str, font=self._font_label)),
                )

            # Step 2: draw max/min stacked column, right-anchored at right_x
            if has_maxmin:
                # Centre the pair around banner midline — simulate justify-content: space-evenly.
                # half_lh ≈ half the visual line-height of font_label (TEXT_XS=11 + 5px leading → 16px → 8px half).
                _half_lh = (TEXT_XS + 5) // 2  # 8px for TEXT_XS=11
                y_max = y_mid - _half_lh
                y_min = y_mid + _half_lh
                draw.text(
                    (right_x, y_max),
                    max_str,
                    font=self._font_label,
                    fill=palette["INK_MUTED"],
                    anchor="rm",
                )
                draw.text(
                    (right_x, y_min),
                    min_str,
                    font=self._font_label,
                    fill=palette["INK_MUTED"],
                    anchor="rm",
                )

            # Step 3: draw current temperature, right-anchored left of max/min column
            temp_gap = 8 if has_maxmin else 0
            temp_right_x = right_x - maxmin_col_w - temp_gap
            temp_str = f"{weather.temp_current:.0f}°"
            draw.text(
                (temp_right_x, y_mid),
                temp_str,
                font=self._font_temp,
                fill=palette["INK"],
                anchor="rm",
            )
            temp_w = int(draw.textlength(temp_str, font=self._font_temp))

            # Step 4: draw condition icon (40px), left of temperature
            if weather.condition_icon is not None:
                icon_img = load_icon(weather.condition_icon, 40)
                if icon_img is not None:
                    r, g, b = self._hex_to_rgb(palette["INK"])
                    _, _, _, alpha = icon_img.split()
                    tinted = Image.new("RGBA", icon_img.size, (r, g, b, 255))
                    tinted.putalpha(alpha)
                    icon_x = temp_right_x - temp_w - 10 - 40
                    icon_y = y_mid - 20
                    img.paste(tinted, (icon_x, icon_y), mask=tinted)

        draw.line(
            [(x0, y0 + h - 1), (x0 + w, y0 + h - 1)],
            fill=palette["RULE_STRONG"],
            width=2,
        )

    # ------------------------------------------------------------------
    # Mini-calendar helpers
    # ------------------------------------------------------------------

    def _format_event_short(self, evt: "CalendarEvent") -> str:
        """Return a compact display string: 'HH:MM Title' for timed events, 'Title' for all-day."""
        if evt.all_day:
            return evt.title
        local_start = evt.start.astimezone(self._tz) if self._tz else evt.start
        return f"{local_start.strftime('%H:%M')} {evt.title}"

    def _truncate_event_line(
        self, text: str, font: "ImageFont.FreeTypeFont", max_width: int
    ) -> str:
        """Truncate *text* to fit *max_width* pixels, appending '…' if needed."""
        if font.getlength(text) <= max_width:
            return text
        ellipsis = "…"
        ellipsis_w = font.getlength(ellipsis)
        if ellipsis_w > max_width:
            return ""
        lo, hi = 0, len(text)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if font.getlength(text[:mid]) + ellipsis_w <= max_width:
                lo = mid
            else:
                hi = mid - 1
        return text[:lo] + ellipsis if lo > 0 else ""

    # ------------------------------------------------------------------
    # Mini-calendar
    # ------------------------------------------------------------------

    def _draw_mini_calendar(
        self,
        draw: ImageDraw.ImageDraw,
        rect: Rect,
        state: NavigationState,
        events: list["CalendarEvent"],
        palette: dict[str, str],
    ) -> None:
        x0, y0, w, h = rect
        today = date.today()
        weeks = _build_rolling_week_grid(state.anchor_date, events, today)
        # Always 5 rows
        N_ROWS = 5

        # No top month header — the in-grid month separator provides context.
        dow_header_h = 16
        separator_h = 16  # height reserved for each between-row month separator

        # DOW header
        dow_y = y0 + dow_header_h // 2
        cell_w = w / 7
        for i, name in enumerate(_DAY_NAMES_IT):
            cx = x0 + i * cell_w + cell_w / 2
            draw.text(
                (cx, dow_y),
                name,
                font=self._font_label,
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
        day_area_h = 18    # height reserved for the day number at the top of each cell
        event_line_h = 13  # TEXT_XS (11px) + 2px gap
        cell_pad_x = 3     # horizontal margin inside cell for event text
        max_event_lines = 4  # show up to 4 events; if more, show 3 + "+N"

        # Color border: only on screens wide enough to absorb the 4px overhead per cell
        show_border = self._size[0] >= 1024
        text_x_offset = cell_pad_x + 4 if show_border else cell_pad_x  # border(2) + gap(2)
        max_text_w = int(cell_w) - text_x_offset - cell_pad_x

        cum_y = grid_top
        for row_idx, week in enumerate(weeks):
            # Month separator: a full-width label row between weeks at month boundary
            if row_idx in sep_before_rows:
                sep_date = week[0]["date"]
                sep_label = (
                    f"{_MONTH_NAMES_IT[sep_date.month - 1].upper()} {sep_date.year}"
                )
                draw.text(
                    (x0 + w // 2, cum_y + separator_h // 2),
                    sep_label,
                    font=self._font_label,
                    fill=palette["INK"],
                    anchor="mm",
                )
                cum_y += separator_h

            row_top_y = cum_y

            for col_idx, cell in enumerate(week):
                cx0 = x0 + col_idx * cell_w
                cy0 = row_top_y
                cx_mid = cx0 + cell_w / 2

                # Day number: centered in the top area [cy0+1 .. cy0+day_area_h]
                day_num_cy = cy0 + 1 + day_area_h // 2

                if cell["is_today"]:
                    # Light-gray cell background for today; day number and events in black
                    draw.rectangle(
                        [cx0, cy0, cx0 + cell_w - 1, cy0 + cell_h - 1],
                        fill=palette["BG_ALT"],
                    )
                    ink = palette["INK"]
                    event_ink = palette["INK"]
                else:
                    ink = palette["INK"]
                    event_ink = palette["INK_MUTED"]

                draw.text(
                    (cx_mid, day_num_cy),
                    str(cell["day_number"]),
                    font=self._font_label,
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
                    if show_border:
                        border_x = int(cx0 + cell_pad_x)
                        try:
                            border_color: tuple | None = ImageColor.getrgb(evt.color) if evt.color else None
                        except (ValueError, AttributeError):
                            border_color = None
                        if border_color is not None:
                            draw.line(
                                [(border_x, line_top + 1), (border_x, line_top + event_line_h - 2)],
                                fill=border_color,
                                width=2,
                            )
                    text = self._truncate_event_line(
                        self._format_event_short(evt), self._font_event, max_text_w
                    )
                    if text:
                        draw.text(
                            (cx0 + text_x_offset, line_y),
                            text,
                            font=self._font_event,
                            fill=event_ink,
                            anchor="lm",
                        )

                if overflow_count > 0:
                    overflow_y = (
                        event_area_top + len(events_to_show) * event_line_h + event_line_h // 2
                    )
                    draw.text(
                        (cx0 + cell_pad_x, overflow_y),
                        f"+{overflow_count}",
                        font=self._font_event,
                        fill=palette["INK_FAINT"],
                        anchor="lm",
                    )

            cum_y += cell_h

        # Bottom separator (portrait only)
        if self._layout == "portrait":
            draw.line(
                [(x0, y0 + h - 1), (x0 + w, y0 + h - 1)],
                fill=palette["RULE_STRONG"],
                width=1,
            )

    # ------------------------------------------------------------------
    # Agenda
    # ------------------------------------------------------------------

    def _draw_agenda(
        self,
        draw: ImageDraw.ImageDraw,
        img: Image.Image,
        rect: Rect,
        state: NavigationState,
        events: list["CalendarEvent"],
        palette: dict[str, str],
    ) -> None:
        x0, y0, w, h = rect

        # Left column separator (landscape only)
        if self._layout == "landscape":
            draw.line([(x0, y0), (x0, y0 + h)], fill=palette["RULE_STRONG"], width=1)

        padding_x = 12
        date_col_w = 52
        event_row_h = 40
        event_row_loc_h = 54
        time_col_w = 56

        # Group events across the full 30-day window (matches events_range_for_state)
        _WINDOW_DAYS = 30
        window_start = state.anchor_date
        window_end = state.anchor_date + timedelta(days=_WINDOW_DAYS - 1)

        days_events: dict[date, list] = {}
        for d_offset in range(_WINDOW_DAYS):
            days_events[window_start + timedelta(days=d_offset)] = []

        for evt in events:
            local_start = evt.start.astimezone(self._tz) if self._tz else evt.start
            evt_date = local_start.date()
            if window_start <= evt_date <= window_end:
                days_events[evt_date].append(evt)

        for d in days_events:
            days_events[d].sort(key=lambda e: (not e.all_day, e.start))

        # Empty state
        has_events = any(len(v) > 0 for v in days_events.values())
        if not has_events:
            draw.text(
                (x0 + w // 2, y0 + h // 2),
                "Nessun appuntamento",
                font=self._font_label,
                fill=palette["INK_FAINT"],
                anchor="mm",
            )
            return

        # Build ordered list: (day, event) — skip days with no events
        items: list[tuple[date, object]] = []
        for d_offset in range(_WINDOW_DAYS):
            day = window_start + timedelta(days=d_offset)
            if not days_events[day]:
                continue
            for evt in days_events[day]:
                items.append((day, evt))

        # First pass: determine what fits and count overflow
        cur_y = y0
        max_y = y0 + h
        rendered: list[tuple[date, object]] = []
        remaining_count = 0
        in_overflow = False

        for day, evt in items:
            if in_overflow:
                remaining_count += 1
                continue
            row_h_item = event_row_loc_h if evt.location else event_row_h  # type: ignore[union-attr]
            # Reserve one event_row_h for the overflow indicator
            if cur_y + row_h_item > max_y - event_row_h:
                in_overflow = True
                remaining_count += 1
                continue
            rendered.append((day, evt))
            cur_y += row_h_item

        # Second pass: draw
        cur_y = y0
        prev_day: date | None = None
        is_first_rendered = True
        for day, evt in rendered:
            first_in_day = day != prev_day
            row_h_item = event_row_loc_h if evt.location else event_row_h  # type: ignore[union-attr]
            self._draw_event_row(
                draw, img, evt, x0, cur_y, w, row_h_item,  # type: ignore[arg-type]
                padding_x, time_col_w, date_col_w, palette,
                day_date=day if first_in_day else None,
                draw_top_separator=not is_first_rendered,
            )
            cur_y += row_h_item
            prev_day = day
            is_first_rendered = False

        # Overflow indicator
        if remaining_count > 0 and cur_y + event_row_h <= max_y:
            draw.text(
                (x0 + w // 2, cur_y + event_row_h // 2),
                f"… altri {remaining_count} appuntamenti",
                font=self._font_label,
                fill=palette["INK_MUTED"],
                anchor="mm",
            )

    def _draw_event_row(
        self,
        draw: ImageDraw.ImageDraw,
        img: Image.Image,
        evt: "CalendarEvent",
        x0: int,
        y0: int,
        w: int,
        row_h: int,
        padding_x: int,
        time_col_w: int,
        date_col_w: int,
        palette: dict[str, str],
        day_date: date | None = None,
        draw_top_separator: bool = True,
    ) -> None:
        first_in_day = day_date is not None

        # Horizontal separator:
        #   - first rendered row: none
        #   - day boundary: full-width (covers date column area)
        #   - same-day continuation: starts after the date column
        if draw_top_separator:
            sep_x_start = x0 + padding_x if first_in_day else x0 + padding_x + date_col_w
            draw.line([(sep_x_start, y0), (x0 + w, y0)], fill=palette["RULE"])

        # --- Date column ---
        if day_date is not None:
            # Vertically centre the two-line block (day number + abbreviation)
            date_content_h = TEXT_MD + 4 + TEXT_XS
            date_top = y0 + (row_h - date_content_h) // 2
            num_y = date_top + TEXT_MD // 2
            label_y = date_top + TEXT_MD + 4 + TEXT_XS // 2
            date_col_right = x0 + padding_x + date_col_w - 4
            draw.text(
                (date_col_right, num_y),
                str(day_date.day),
                font=self._font_date_num,
                fill=palette["INK"],
                anchor="rm",
            )
            draw.text(
                (date_col_right, label_y),
                f"{_MONTH_NAMES_SHORT_IT[day_date.month - 1]}, {_DAY_NAMES_IT[day_date.weekday()]}",
                font=self._font_label,
                fill=palette["INK_MUTED"],
                anchor="rm",
            )

        # --- Time column ---
        time_area_x = x0 + padding_x + date_col_w
        sep_x = time_area_x + time_col_w

        # Vertical position: centre, or upper third if location present
        if evt.location:
            time_y = y0 + row_h // 3
        else:
            time_y = y0 + row_h // 2

        half_lh = (TEXT_SM + 5) // 2

        if not evt.all_day:
            local_start = evt.start.astimezone(self._tz) if self._tz else evt.start
            local_end = evt.end.astimezone(self._tz) if self._tz else evt.end
            draw.text(
                (sep_x - 4, time_y - half_lh),
                local_start.strftime("%H:%M"),
                font=self._font_mono,
                fill=palette["INK_MUTED"],
                anchor="rm",
            )
            draw.text(
                (sep_x - 4, time_y + half_lh),
                local_end.strftime("%H:%M"),
                font=self._font_mono,
                fill=palette["INK_FAINT"],
                anchor="rm",
            )

        # Vertical separator between time column and content — coloured with calendar colour
        raw_color = getattr(evt, "color", "") or ""
        if raw_color.startswith("#") and len(raw_color) == 7:
            try:
                sep_rgb: tuple[int, int, int] = self._hex_to_rgb(raw_color)
            except ValueError:
                sep_rgb = self._hex_to_rgb(palette["RULE"])
        else:
            sep_rgb = self._hex_to_rgb(palette["RULE"])
        draw.line([(sep_x, y0 + 4), (sep_x, y0 + row_h - 4)], fill=sep_rgb, width=2)

        # --- Content ---
        title_x = sep_x + 8
        title_max_w = w - (title_x - x0) - 8
        icon_size_title = int(self._font_body.size * 0.75)
        title_segs = split_text_emoji(evt.title)
        title_segs = self._fit_mixed(draw, title_segs, self._font_body, icon_size_title, title_max_w)
        self._draw_mixed(draw, img, title_segs, title_x, time_y, self._font_body, palette["INK"], icon_size_title)

        if evt.location:
            loc_y = y0 + row_h * 2 // 3
            icon_size_loc = int(self._font_label.size * 0.75)
            loc_segs = split_text_emoji(evt.location)
            loc_segs = self._fit_mixed(draw, loc_segs, self._font_label, icon_size_loc, title_max_w)
            self._draw_mixed(draw, img, loc_segs, title_x, loc_y, self._font_label, palette["INK_MUTED"], icon_size_loc)


    # ------------------------------------------------------------------
    # Footer
    # ------------------------------------------------------------------

    def _draw_footer(
        self,
        draw: ImageDraw.ImageDraw,
        rect: Rect,
        palette: dict[str, str],
    ) -> None:
        x0, y0, w, h = rect

        # Top separator
        draw.line([(x0, y0), (x0 + w, y0)], fill=palette["RULE"])

        y_mid = y0 + h // 2

        # Status indicators (right-aligned)
        status_parts: list[tuple[str, ImageFont.FreeTypeFont]] = [
            (self._display_type, self._font_label),
            (self._layout, self._font_label),
        ]
        status_parts.append((datetime.now().strftime("%H:%M"), self._font_mono))

        right_x = x0 + w - 12
        for text, font in reversed(status_parts):
            bbox = draw.textbbox((0, 0), text, font=font)
            text_w = bbox[2] - bbox[0]
            draw.text(
                (right_x, y_mid),
                text,
                font=font,
                fill=palette["INK_MUTED"],
                anchor="rm",
            )
            right_x -= text_w + 12

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load_font(filename: str, size: int) -> ImageFont.FreeTypeFont:
        path = FONTS_DIR / filename
        if not path.exists():
            raise FileNotFoundError(
                f"PillowEinkRenderer: required font not found: {path}"
            )
        return ImageFont.truetype(str(path), size)

    @staticmethod
    def _fit_text(
        draw: ImageDraw.ImageDraw,
        text: str,
        font: ImageFont.FreeTypeFont,
        max_width: float,
    ) -> str:
        """Truncate *text* to fit *max_width* pixels, appending '…' if needed."""
        if max_width <= 0:
            return ""
        bbox = draw.textbbox((0, 0), text, font=font)
        if bbox[2] - bbox[0] <= max_width:
            return text
        lo, hi = 0, len(text)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            candidate = text[:mid] + "…"
            b = draw.textbbox((0, 0), candidate, font=font)
            if b[2] - b[0] <= max_width:
                lo = mid
            else:
                hi = mid - 1
        return text[:lo] + "…"

    # ------------------------------------------------------------------
    # Mixed text + inline-icon rendering helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
        """Convert a ``#rrggbb`` colour string to an (r, g, b) tuple."""
        h = hex_color.lstrip("#")
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

    @staticmethod
    def _measure_mixed(
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

    @staticmethod
    def _fit_mixed(
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
        if PillowEinkRenderer._measure_mixed(draw, segments, font, icon_size) <= max_width:
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

    def _draw_mixed(
        self,
        draw: ImageDraw.ImageDraw,
        img: Image.Image,
        segments: list[tuple[str, str]],
        x: int,
        y: int,
        font: ImageFont.FreeTypeFont,
        fill: str,
        icon_size: int,
    ) -> None:
        """Render *segments* left-to-right starting at (*x*, *y* middle-left).

        Text segments use ``draw.text`` with ``anchor="lm"``.
        Icon segments are composited onto *img* recoloured to *fill*.
        """
        cur_x = x
        r, g, b = self._hex_to_rgb(fill)

        for seg_type, content in segments:
            if seg_type == "text":
                if content:
                    draw.text((cur_x, y), content, font=font, fill=fill, anchor="lm")
                    bb = draw.textbbox((0, 0), content, font=font)
                    cur_x += bb[2] - bb[0]
            else:  # "icon"
                icon_img = load_icon(content, icon_size)
                if icon_img is not None:
                    # Recolour: solid fill masked by the icon's alpha channel
                    colored = Image.new("RGBA", icon_img.size, (r, g, b, 255))
                    _, _, _, alpha = icon_img.split()
                    colored.putalpha(alpha)
                    icon_top = y - icon_size // 2
                    img.paste(colored, (cur_x, icon_top), mask=colored)
                    cur_x += icon_size + 1
