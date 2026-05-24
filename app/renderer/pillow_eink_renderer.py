"""Pillow-native e-ink renderer for Family Planner.

``PillowEinkRenderer`` renders a ``PIL.Image`` directly from ``NavigationState``
and a list of ``CalendarEvent`` objects, without involving a browser or network.

It is designed for ``display.type == "eink"`` and replaces ``PlaywrightRenderer``
in the e-ink display loop.  It does not import or start Chromium; all layout is
computed in Python and painted with Pillow ``ImageDraw``.

Does not inherit from ``Renderer`` — the public API accepts ``state`` and
``events`` as explicit parameters rather than owning them internally (unlike
``PlaywrightRenderer`` which manages its own headless browser state).

Usage::

    renderer = PillowEinkRenderer(config)
    state = state_manager.get()
    start, end = events_range_for_state(state)
    events = aggregator.get_events(start, end)
    img = renderer.render(state, events)      # PIL.Image RGB
    processed = eink_post_processor.process(img)
    display.push(processed)
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from PIL import Image, ImageDraw, ImageFont

from app.calendar.data_builders import (
    _GRID_END_HOUR,
    _GRID_HEIGHT_PX,
    _GRID_START_HOUR,
    _build_month_grid,
    _event_to_grid,
)
from app.renderer.state import NavigationState, View
from app.renderer.tokens import (
    FONT_BODY_REGULAR,
    FONT_BODY_SEMIBOLD,
    FONT_DISPLAY_REGULAR,
    FONT_MONO_REGULAR,
    FONTS_DIR,
    FOOTER_HEIGHT,
    HEADER_HEIGHT,
    TEXT_LG,
    TEXT_SM,
    TEXT_XS,
    get_palette,
)

if TYPE_CHECKING:
    from app.calendar.base import CalendarEvent
    from app.config import AppConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Locale strings (private — not imported from other modules to avoid coupling)
# ---------------------------------------------------------------------------

_MONTH_NAMES_IT: list[str] = [
    "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
    "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre",
]
_DAY_NAMES_IT: list[str] = ["LUN", "MAR", "MER", "GIO", "VEN", "SAB", "DOM"]
_DAY_NAMES_FULL_IT: list[str] = [
    "Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica",
]
_VIEW_LABELS_IT: dict[View, str] = {
    View.ANNUAL: "ANNUALE",
    View.MONTHLY: "MENSILE",
    View.WEEKLY: "SETTIMANALE",
    View.DAILY: "GIORNALIERO",
    View.DETAIL: "DETTAGLIO",
}

# ---------------------------------------------------------------------------
# Layout constants (px) — all values are absolute pixels for a fixed display
# ---------------------------------------------------------------------------

_DOW_HEADER_H: int = 20    # day-of-week header row height (monthly view)
_COL_HEADER_H: int = 28    # day column header height (weekly view)
_ALLDAY_H: int = 20        # all-day events strip height (weekly view)
_TIME_COL_W: int = 48      # hour-label column width (weekly view)
_MIN_EVENT_H: int = 12     # minimum timed-event block height (px)
_DOT_RADIUS: int = 3       # event dot radius in monthly cells (px)
_MAX_DOTS: int = 3         # max event dots per cell before showing "+"
_DAILY_ROW_H: int = 24     # event row height in daily view (px)
_TIME_COL_DAILY_W: int = 90  # time label column width in daily view (px)
_DOT_D: int = 8            # event dot diameter in daily view (px)


class PillowEinkRenderer:
    """Pillow-native renderer: ``NavigationState`` + events → ``PIL.Image``.

    Args:
        config: Full application config.  ``config.display`` supplies canvas
                dimensions; ``config.timezone`` localises event times.

    Raises:
        FileNotFoundError: If any required TTF font file is missing from
            ``app/assets/fonts/``.
    """

    def __init__(self, config: "AppConfig") -> None:
        self._size: tuple[int, int] = (config.display.width, config.display.height)

        # Timezone for localising event datetimes — None keeps event-native tz.
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

        # Fonts are loaded once at construction — raise immediately if any TTF is missing
        # rather than silently falling back to Pillow's default (unreadable on e-ink).
        self._font_title: ImageFont.FreeTypeFont = self._load_font(FONT_DISPLAY_REGULAR, TEXT_LG)
        self._font_body: ImageFont.FreeTypeFont = self._load_font(FONT_BODY_REGULAR, TEXT_SM)
        self._font_label: ImageFont.FreeTypeFont = self._load_font(FONT_BODY_SEMIBOLD, TEXT_XS)
        self._font_mono: ImageFont.FreeTypeFont = self._load_font(FONT_MONO_REGULAR, TEXT_XS)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def render(
        self,
        state: NavigationState,
        events: list["CalendarEvent"],
    ) -> Image.Image:
        """Render the calendar view described by *state* to a ``PIL.Image``.

        Args:
            state: Current navigation state (view, selected date, night mode).
            events: Events pre-fetched by the caller for the relevant time window.

        Returns:
            RGB ``PIL.Image`` at the configured display resolution.
        """
        palette = get_palette(state.night_mode)
        img = Image.new("RGB", self._size, palette["BG"])
        draw = ImageDraw.Draw(img)

        title = self._compute_title(state)
        self._draw_header(draw, title, palette)
        self._draw_footer(draw, state, palette)

        if state.view == View.MONTHLY:
            self._draw_monthly(draw, state, events, palette)
        elif state.view == View.WEEKLY:
            self._draw_weekly(draw, state, events, palette)
        elif state.view == View.DAILY:
            self._draw_daily(draw, state, events, palette)
        else:
            logger.warning(
                "PillowEinkRenderer: view %r not yet implemented — falling back to monthly",
                state.view,
            )
            self._draw_monthly(draw, state, events, palette)

        return img

    # ------------------------------------------------------------------
    # Title computation
    # ------------------------------------------------------------------

    def _compute_title(self, state: NavigationState) -> str:
        sel = state.selected_date
        if state.view == View.MONTHLY:
            return f"{_MONTH_NAMES_IT[sel.month - 1]} {sel.year}"
        if state.view == View.WEEKLY:
            week_start = sel - timedelta(days=sel.weekday())
            week_end = week_start + timedelta(days=6)
            week_num = week_start.isocalendar()[1]
            month_name = _MONTH_NAMES_IT[week_end.month - 1]
            return (
                f"Settimana {week_num} · "
                f"{week_start.day}–{week_end.day} {month_name} {week_end.year}"
            )
        if state.view == View.DAILY:
            dow = _DAY_NAMES_FULL_IT[sel.weekday()]
            month_name = _MONTH_NAMES_IT[sel.month - 1]
            return f"{dow} {sel.day} {month_name} {sel.year}"
        return ""

    # ------------------------------------------------------------------
    # Chrome: header and footer
    # ------------------------------------------------------------------

    def _draw_header(
        self,
        draw: ImageDraw.ImageDraw,
        title: str,
        palette: dict[str, str],
    ) -> None:
        w = self._size[0]
        y_mid = HEADER_HEIGHT // 2
        draw.text(
            (16, y_mid), title,
            font=self._font_title, fill=palette["INK"], anchor="lm",
        )
        draw.line(
            [(0, HEADER_HEIGHT - 1), (w, HEADER_HEIGHT - 1)],
            fill=palette["RULE_STRONG"],
        )

    def _draw_footer(
        self,
        draw: ImageDraw.ImageDraw,
        state: NavigationState,
        palette: dict[str, str],
    ) -> None:
        w, h = self._size
        footer_top = h - FOOTER_HEIGHT
        y_mid = footer_top + FOOTER_HEIGHT // 2

        draw.line([(0, footer_top), (w, footer_top)], fill=palette["RULE"])

        view_label = _VIEW_LABELS_IT.get(state.view, "")
        draw.text(
            (16, y_mid), view_label,
            font=self._font_label, fill=palette["INK_MUTED"], anchor="lm",
        )

        sel = state.selected_date
        date_str = f"{sel.day} {_MONTH_NAMES_IT[sel.month - 1]} {sel.year}"
        draw.text(
            (w - 16, y_mid), date_str,
            font=self._font_mono, fill=palette["INK_MUTED"], anchor="rm",
        )

    # ------------------------------------------------------------------
    # Monthly view (Fase 3)
    # ------------------------------------------------------------------

    def _draw_monthly(
        self,
        draw: ImageDraw.ImageDraw,
        state: NavigationState,
        events: list["CalendarEvent"],
        palette: dict[str, str],
    ) -> None:
        w, h = self._size
        today = date.today()
        year, month = state.selected_date.year, state.selected_date.month
        weeks = _build_month_grid(year, month, events, today)
        n_weeks = len(weeks)

        content_top = HEADER_HEIGHT
        content_h = h - HEADER_HEIGHT - FOOTER_HEIGHT
        grid_top = content_top + _DOW_HEADER_H
        grid_h = content_h - _DOW_HEADER_H
        cell_w = w / 7
        cell_h = grid_h / n_weeks

        # --- Day-of-week header row ---
        for i, name in enumerate(_DAY_NAMES_IT):
            x = i * cell_w + cell_w / 2
            y = content_top + _DOW_HEADER_H // 2
            draw.text(
                (x, y), name,
                font=self._font_label, fill=palette["INK_MUTED"], anchor="mm",
            )

        # --- Grid cells ---
        for row_idx, week in enumerate(weeks):
            for col_idx, cell in enumerate(week):
                cx0 = col_idx * cell_w
                cy0 = grid_top + row_idx * cell_h

                # Today highlight: small square behind the day number.
                if cell["is_today"]:
                    sq = 18
                    draw.rectangle(
                        [cx0 + 3, cy0 + 2, cx0 + 3 + sq, cy0 + 2 + sq],
                        fill=palette["BG_ALT"],
                    )

                # Day number.
                ink = palette["INK"] if cell["is_current_month"] else palette["INK_FAINT"]
                draw.text(
                    (cx0 + 5, cy0 + 4),
                    str(cell["day_number"]),
                    font=self._font_body,
                    fill=ink,
                    anchor="lt",
                )

                # Event dots: up to _MAX_DOTS coloured circles, then "+" if more.
                cell_events: list = cell["events"]
                n_ev = len(cell_events)
                if n_ev > 0:
                    dot_y = cy0 + 22
                    x_start = cx0 + 5
                    shown = min(n_ev, _MAX_DOTS)
                    for k in range(shown):
                        cx = x_start + k * (_DOT_RADIUS * 2 + 3) + _DOT_RADIUS
                        draw.ellipse(
                            [
                                cx - _DOT_RADIUS, dot_y - _DOT_RADIUS,
                                cx + _DOT_RADIUS, dot_y + _DOT_RADIUS,
                            ],
                            fill=cell_events[k].color,
                        )
                    if n_ev > _MAX_DOTS:
                        px = x_start + shown * (_DOT_RADIUS * 2 + 3)
                        draw.text(
                            (px, dot_y), "+",
                            font=self._font_mono, fill=palette["INK_MUTED"], anchor="lm",
                        )

        # --- Grid lines ---
        # Outer border in strong rule colour.
        draw.rectangle(
            [0, grid_top, w - 1, grid_top + round(grid_h) - 1],
            outline=palette["RULE_STRONG"],
        )
        # Vertical column separators.
        for col in range(1, 7):
            x = round(col * cell_w)
            draw.line([(x, grid_top), (x, grid_top + round(grid_h))], fill=palette["RULE"])
        # Horizontal row separators.
        for row in range(1, n_weeks):
            y = round(grid_top + row * cell_h)
            draw.line([(0, y), (w, y)], fill=palette["RULE"])

    # ------------------------------------------------------------------
    # Weekly view (Fase 4)
    # ------------------------------------------------------------------

    def _draw_weekly(
        self,
        draw: ImageDraw.ImageDraw,
        state: NavigationState,
        events: list["CalendarEvent"],
        palette: dict[str, str],
    ) -> None:
        w, h = self._size
        today = date.today()
        sel = state.selected_date
        week_start = sel - timedelta(days=sel.weekday())

        day_col_w = (w - _TIME_COL_W) / 7
        content_top = HEADER_HEIGHT
        content_h = h - HEADER_HEIGHT - FOOTER_HEIGHT
        allday_row_top = content_top + _COL_HEADER_H
        grid_top = allday_row_top + _ALLDAY_H
        grid_h = content_h - _COL_HEADER_H - _ALLDAY_H

        # Scaling factor: _event_to_grid works in _GRID_HEIGHT_PX=700 space;
        # we map proportionally to the actual grid_h available on this display.
        scale = grid_h / _GRID_HEIGHT_PX
        n_hours = _GRID_END_HOUR - _GRID_START_HOUR  # 14

        all_day_events = [e for e in events if e.all_day]
        timed_events = [e for e in events if not e.all_day]

        # --- Day column headers ---
        for i in range(7):
            day = week_start + timedelta(days=i)
            x0 = _TIME_COL_W + i * day_col_w
            x1 = x0 + day_col_w
            is_today = day == today

            if is_today:
                draw.rectangle(
                    [x0, content_top, x1 - 1, allday_row_top - 1],
                    fill=palette["BG_ALT"],
                )

            label = f"{_DAY_NAMES_IT[i]} {day.day}"
            draw.text(
                (x0 + day_col_w / 2, content_top + _COL_HEADER_H // 2),
                label,
                font=self._font_label,
                fill=palette["INK"],
                anchor="mm",
            )

        # --- All-day events strip ---
        for evt in all_day_events:
            day_idx = (evt.start.date() - week_start).days
            if 0 <= day_idx <= 6:
                x0 = _TIME_COL_W + round(day_idx * day_col_w) + 1
                x1 = _TIME_COL_W + round((day_idx + 1) * day_col_w) - 2
                y0 = allday_row_top + 2
                y1 = grid_top - 2
                draw.rectangle([x0, y0, x1, y1], fill=evt.color)
                strip_w = x1 - x0
                if strip_w > 32:
                    txt_color = self._text_color_for_bg(evt.color)
                    label = self._fit_text(draw, evt.title, self._font_mono, strip_w - 6)
                    draw.text(
                        (x0 + 3, (y0 + y1) // 2), label,
                        font=self._font_mono, fill=txt_color, anchor="lm",
                    )

        # Separator between all-day strip and main grid.
        draw.line([(0, grid_top), (w, grid_top)], fill=palette["RULE_STRONG"])

        # --- Hour lines and labels ---
        hour_h = grid_h / n_hours
        for i in range(n_hours + 1):
            hr = _GRID_START_HOUR + i
            y = round(grid_top + i * hour_h)
            draw.line([(_TIME_COL_W, y), (w, y)], fill=palette["RULE"])
            draw.text(
                (_TIME_COL_W - 4, y),
                f"{hr:02d}:00",
                font=self._font_mono,
                fill=palette["INK_FAINT"],
                anchor="rm",
            )

        # --- Vertical column separators ---
        # i=0: right edge of time column; i=1..6: between day cols; i=7: right edge.
        for i in range(8):
            x = round(_TIME_COL_W + i * day_col_w)
            draw.line([(x, content_top), (x, grid_top + round(grid_h))], fill=palette["RULE"])

        # --- Timed event rectangles ---
        for evt in timed_events:
            grid_info = _event_to_grid(evt, week_start, self._tz)
            if grid_info is None:
                continue

            top_px = round(grid_info["top"] * scale)
            height_px = max(_MIN_EVENT_H, round(grid_info["height"] * scale))
            day_idx = grid_info["day_index"]

            x0 = _TIME_COL_W + round(day_idx * day_col_w) + 1
            x1 = _TIME_COL_W + round((day_idx + 1) * day_col_w) - 2
            y0 = grid_top + top_px
            y1 = min(y0 + height_px, grid_top + round(grid_h))  # clip to grid

            draw.rectangle([x0, y0, x1, y1], fill=evt.color)

            txt_color = self._text_color_for_bg(evt.color)
            available_w = x1 - x0 - 6

            if height_px >= 20 and available_w > 0:
                title = self._fit_text(draw, grid_info["title"], self._font_body, available_w)
                draw.text(
                    (x0 + 3, y0 + 2), title,
                    font=self._font_body, fill=txt_color, anchor="lt",
                )
            if height_px >= 30 and available_w > 0:
                draw.text(
                    (x0 + 3, y1 - 2), grid_info["start_str"],
                    font=self._font_mono, fill=txt_color, anchor="lb",
                )

    # ------------------------------------------------------------------
    # Daily view (Fase 5)
    # ------------------------------------------------------------------

    def _draw_daily(
        self,
        draw: ImageDraw.ImageDraw,
        state: NavigationState,
        events: list["CalendarEvent"],
        palette: dict[str, str],
    ) -> None:
        w, h = self._size
        target_date = state.selected_date
        content_top = HEADER_HEIGHT
        content_h = h - HEADER_HEIGHT - FOOTER_HEIGHT

        # --- Filter and sort events for the selected day ---
        day_events: list["CalendarEvent"] = []
        for evt in events:
            local_date = (
                evt.start.astimezone(self._tz).date()
                if self._tz
                else evt.start.date()
            )
            if local_date == target_date:
                day_events.append(evt)
        # All-day events first, then timed events ordered by start time.
        day_events.sort(key=lambda e: (not e.all_day, e.start))

        # --- Empty state ---
        if not day_events:
            draw.text(
                (w // 2, content_top + content_h // 2),
                "Nessun evento",
                font=self._font_body,
                fill=palette["INK_FAINT"],
                anchor="mm",
            )
            return

        # --- Calculate visible rows ---
        max_rows = content_h // _DAILY_ROW_H
        if len(day_events) > max_rows:
            visible = day_events[: max_rows - 1]
            n_hidden = len(day_events) - len(visible)
        else:
            visible = day_events
            n_hidden = 0

        dot_r = _DOT_D // 2
        time_x = 16 + _DOT_D + 8           # left edge of time column
        title_x = time_x + _TIME_COL_DAILY_W + 8  # left edge of title
        title_max_w = w - title_x - 16    # remaining width minus right margin

        for row_idx, evt in enumerate(visible):
            y0 = content_top + row_idx * _DAILY_ROW_H
            y_mid = y0 + _DAILY_ROW_H // 2

            # Row separator (not on first row)
            if row_idx > 0:
                draw.line([(0, y0), (w, y0)], fill=palette["RULE"])

            # Colour dot
            dot_x = 16 + dot_r
            draw.ellipse(
                [dot_x - dot_r, y_mid - dot_r, dot_x + dot_r, y_mid + dot_r],
                fill=evt.color,
            )

            # Time label
            if evt.all_day:
                time_str = "tutto il giorno"
            else:
                if self._tz:
                    local_start = evt.start.astimezone(self._tz)
                    local_end = evt.end.astimezone(self._tz)
                else:
                    local_start = evt.start
                    local_end = evt.end
                time_str = (
                    f"{local_start.strftime('%H:%M')}\u2013{local_end.strftime('%H:%M')}"
                )
            draw.text(
                (time_x, y_mid),
                time_str,
                font=self._font_mono,
                fill=palette["INK_MUTED"],
                anchor="lm",
            )

            # Title (truncated to available width)
            title = self._fit_text(draw, evt.title, self._font_body, title_max_w)
            draw.text(
                (title_x, y_mid),
                title,
                font=self._font_body,
                fill=palette["INK"],
                anchor="lm",
            )

        # --- Overflow indicator ---
        if n_hidden > 0:
            overflow_y0 = content_top + len(visible) * _DAILY_ROW_H
            overflow_y_mid = overflow_y0 + _DAILY_ROW_H // 2
            draw.line([(0, overflow_y0), (w, overflow_y0)], fill=palette["RULE"])
            draw.text(
                (w // 2, overflow_y_mid),
                f"+ {n_hidden} altri",
                font=self._font_label,
                fill=palette["INK_MUTED"],
                anchor="mm",
            )

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
    def _text_color_for_bg(hex_color: str) -> str:
        """Return white or dark ink for a given background hex colour.

        Uses the ITU-R BT.601 luma formula for perceived luminance.
        """
        try:
            c = hex_color.lstrip("#")
            r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
            luminance = 0.299 * r + 0.587 * g + 0.114 * b
            return "#FFFFFF" if luminance < 140 else "#111111"
        except (ValueError, IndexError):
            return "#111111"

    @staticmethod
    def _fit_text(
        draw: ImageDraw.ImageDraw,
        text: str,
        font: ImageFont.FreeTypeFont,
        max_width: float,
    ) -> str:
        """Truncate *text* to fit *max_width* pixels, appending '…' if needed.

        Uses binary search for O(log n) truncation.
        """
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
