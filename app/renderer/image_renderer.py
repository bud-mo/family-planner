"""Primary image renderer for Family Planner.

``ImageRenderer`` produces a full-frame ``PIL.Image`` (RGB) for any of the
five calendar views.  It is the single rendering pipeline shared by both the
HDMI display (pygame) and the e-ink display (post-processed by EinkRenderer).

Thread safety: ``render()`` and ``update_state()`` may be called from
different threads (pygame loop vs FastAPI).  An internal ``threading.Lock``
serialises state access around each ``render()`` call.
"""
from __future__ import annotations

import calendar
import logging
import threading
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageDraw, ImageFont

from app.calendar.aggregator import CalendarAggregator
from app.calendar.base import CalendarEvent
from app.config import DisplayConfig
from app.renderer.base import Renderer
from app.renderer.state import NavigationState, View
from app.renderer import tokens
from app.renderer.tokens import (
    FONTS_DIR,
    FOOTER_HEIGHT,
    HEADER_HEIGHT,
    ICONS_DIR,
    TEXT_BASE,
    TEXT_LG,
    TEXT_MD,
    TEXT_SM,
    TEXT_XL,
    TEXT_XS,
    get_palette,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Weekly view time window (08:00–22:00)
# ---------------------------------------------------------------------------

WEEKLY_START_HOUR: int = 8
WEEKLY_END_HOUR: int = 22
WEEKLY_HOURS: int = WEEKLY_END_HOUR - WEEKLY_START_HOUR  # 14

# Width of the time-label column in the weekly/daily views (px)
WEEKLY_TIME_COL_W: int = 52
DAILY_TIME_COL_W: int = 56

# Height of the all-day strip in the weekly view (px)
ALLDAY_STRIP_H: int = 24

# Minimum free-slot duration to label with "Libero" in the daily view (min)
FREE_SLOT_MIN_MINUTES: int = 60

# Italian locale helpers
_MONTHS_IT = [
    "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
    "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre",
]
_MONTHS_SHORT_IT = [
    "GEN", "FEB", "MAR", "APR", "MAG", "GIU",
    "LUG", "AGO", "SET", "OTT", "NOV", "DIC",
]
_DAYS_SHORT_IT = ["LUN", "MAR", "MER", "GIO", "VEN", "SAB", "DOM"]


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    """Convert a #RRGGBB hex string to an (R, G, B) integer tuple."""
    color = color.lstrip("#")
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)


def _week_number(d: date) -> int:
    """ISO week number for *d*."""
    return d.isocalendar()[1]


def _monday_of_week(d: date) -> date:
    """Return the Monday of the ISO week that contains *d*."""
    return d - timedelta(days=d.weekday())


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(value, hi))


class ImageRenderer(Renderer):
    """Render any of the five calendar views as a ``PIL.Image``."""

    def __init__(
        self,
        aggregator: CalendarAggregator,
        config: DisplayConfig,
        state: NavigationState | None = None,
    ) -> None:
        self._aggregator = aggregator
        self._config = config
        self._state = state or NavigationState()
        self._lock = threading.Lock()
        # Populated by _draw_footer() on every render; maps action name
        # ("up", "down", "enter", "escape") to (x1, y1, x2, y2) in image-space px.
        self._footer_rects: dict[str, tuple[int, int, int, int]] = {}

        self._fonts = self._load_fonts()
        self._icons = self._load_icons()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def update_state(self, new_state: NavigationState) -> None:
        """Thread-safe state update called from the display input handler."""
        with self._lock:
            self._state = new_state

    def get_footer_rects(self) -> dict[str, tuple[int, int, int, int]]:
        """Return a snapshot of footer button hit-rects from the last render.

        Keys are action names ("up", "down", "enter", "escape").
        Values are (x1, y1, x2, y2) in image-space pixels.
        Disabled buttons (e.g. "escape" on ANNUAL view) are absent from the dict.
        """
        return dict(self._footer_rects)

    def render(self) -> Image.Image:
        """Produce a full-frame RGB ``PIL.Image`` for the current state."""
        with self._lock:
            state = self._state

        palette = get_palette(state.night_mode)
        img = Image.new("RGB", (self._config.width, self._config.height),
                        _hex_to_rgb(palette["BG"]))
        draw = ImageDraw.Draw(img)

        # Fetch events for the relevant time window
        events = self._fetch_events(state)

        self._draw_header(draw, img, state, palette)
        self._draw_footer(draw, img, state, palette)
        self._draw_content(draw, img, state, palette, events)

        return img

    # ------------------------------------------------------------------
    # Asset loading
    # ------------------------------------------------------------------

    def _load_fonts(self) -> dict[str, dict[int, ImageFont.FreeTypeFont]]:
        """Load TTF fonts in all required sizes; fall back to Pillow built-in."""
        specs = {
            "display_regular": tokens.FONT_DISPLAY_REGULAR,
            "display_bold": tokens.FONT_DISPLAY_BOLD,
            "body_regular": tokens.FONT_BODY_REGULAR,
            "body_semibold": tokens.FONT_BODY_SEMIBOLD,
            "mono_regular": tokens.FONT_MONO_REGULAR,
        }
        sizes = [TEXT_XS, TEXT_SM, TEXT_BASE, TEXT_MD, TEXT_LG, TEXT_XL]
        result: dict[str, dict[int, ImageFont.FreeTypeFont]] = {}

        for key, filename in specs.items():
            path = FONTS_DIR / filename
            result[key] = {}
            for size in sizes:
                try:
                    result[key][size] = ImageFont.truetype(str(path), size)
                except (OSError, IOError):
                    if size == TEXT_XS:
                        logger.warning(
                            "Font file not found: %s — using Pillow built-in fallback",
                            path,
                        )
                    result[key][size] = ImageFont.load_default()

        return result

    def _load_icons(self) -> dict[str, Image.Image]:
        """Load available PNG icons; skip missing ones with a single warning."""
        icons: dict[str, Image.Image] = {}
        warned: set[str] = set()
        for png_path in ICONS_DIR.glob("*.png"):
            try:
                icons[png_path.stem] = Image.open(png_path).convert("RGBA")
            except (OSError, IOError) as exc:
                if png_path.stem not in warned:
                    logger.warning("Could not load icon %s: %s", png_path.name, exc)
                    warned.add(png_path.stem)
        return icons

    # ------------------------------------------------------------------
    # Event fetching
    # ------------------------------------------------------------------

    def _fetch_events(self, state: NavigationState) -> list[CalendarEvent]:
        """Return events for the time window visible in *state*'s view."""
        today = state.selected_date
        if state.view == View.ANNUAL:
            start_dt = datetime(today.year, 1, 1, tzinfo=timezone.utc)
            end_dt = datetime(today.year, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
        elif state.view == View.MONTHLY:
            first = today.replace(day=1)
            if first.month == 12:
                last = first.replace(year=first.year + 1, month=1) - timedelta(days=1)
            else:
                last = first.replace(month=first.month + 1) - timedelta(days=1)
            start_dt = datetime(first.year, first.month, 1, tzinfo=timezone.utc)
            end_dt = datetime(last.year, last.month, last.day, 23, 59, 59, tzinfo=timezone.utc)
        elif state.view == View.WEEKLY:
            monday = _monday_of_week(today)
            sunday = monday + timedelta(days=6)
            start_dt = datetime(monday.year, monday.month, monday.day, tzinfo=timezone.utc)
            end_dt = datetime(sunday.year, sunday.month, sunday.day, 23, 59, 59, tzinfo=timezone.utc)
        else:
            # DAILY and DETAIL: just today
            start_dt = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
            end_dt = datetime(today.year, today.month, today.day, 23, 59, 59, tzinfo=timezone.utc)

        try:
            return self._aggregator.get_events(start_dt, end_dt)
        except Exception as exc:
            logger.error("Failed to fetch events: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------

    def _draw_header(
        self,
        draw: ImageDraw.ImageDraw,
        img: Image.Image,
        state: NavigationState,
        palette: dict[str, str],
    ) -> None:
        w = self._config.width
        bg = _hex_to_rgb(palette["BG"])
        ink = _hex_to_rgb(palette["INK"])
        rule_strong = _hex_to_rgb(palette["RULE_STRONG"])

        # Background strip
        draw.rectangle([0, 0, w - 1, HEADER_HEIGHT - 1], fill=bg)

        # View title
        title = self._header_title(state)
        font_title = self._font("body_semibold", TEXT_LG)
        draw.text((16, HEADER_HEIGHT // 2), title, font=font_title,
                  fill=ink, anchor="lm")

        # Right-side indicators: display type + current time
        now_str = datetime.now().strftime("%H:%M")
        display_type = self._config.type
        right_text = f"{display_type}  {now_str}"
        if state.night_mode and self._config.type == "hdmi":
            right_text = f"☾  {right_text}"
        font_small = self._font("mono_regular", TEXT_XS)
        draw.text((w - 16, HEADER_HEIGHT // 2), right_text,
                  font=font_small, fill=_hex_to_rgb(palette["INK_MUTED"]),
                  anchor="rm")

        # Bottom border
        draw.line([(0, HEADER_HEIGHT - 1), (w - 1, HEADER_HEIGHT - 1)],
                  fill=rule_strong, width=2)

    def _header_title(self, state: NavigationState) -> str:
        d = state.selected_date
        if state.view == View.ANNUAL:
            return str(d.year)
        if state.view == View.MONTHLY:
            return f"{_MONTHS_IT[d.month - 1].upper()}  {d.year}"
        if state.view == View.WEEKLY:
            monday = _monday_of_week(d)
            sunday = monday + timedelta(days=6)
            wn = _week_number(d)
            return (
                f"Settimana {wn}  ·  "
                f"{monday.day}–{sunday.day} {_MONTHS_IT[monday.month - 1]} {monday.year}"
            )
        if state.view == View.DAILY:
            return (
                f"{_DAYS_SHORT_IT[d.weekday()]},  "
                f"{d.day} {_MONTHS_IT[d.month - 1]} {d.year}"
            )
        return "Dettaglio Appuntamento"

    # ------------------------------------------------------------------
    # Footer
    # ------------------------------------------------------------------

    def _draw_footer(
        self,
        draw: ImageDraw.ImageDraw,
        img: Image.Image,
        state: NavigationState,
        palette: dict[str, str],
    ) -> None:
        w = self._config.width
        h = self._config.height
        bg = _hex_to_rgb(palette["BG"])
        ink = _hex_to_rgb(palette["INK"])
        ink_faint = _hex_to_rgb(palette["INK_FAINT"])
        rule = _hex_to_rgb(palette["RULE"])

        y_top = h - FOOTER_HEIGHT
        draw.rectangle([0, y_top, w - 1, h - 1], fill=bg)
        draw.line([(0, y_top), (w - 1, y_top)], fill=rule, width=1)

        # Maps button index → action name (same order as buttons list below)
        _BUTTON_ACTIONS = ["up", "down", "enter", "escape"]

        buttons = [
            ("↑", "Su"),
            ("↓", "Giù"),
            ("↵", "Invio"),
            ("←", "Esci"),
        ]
        # "Esci" is disabled on the Annual view
        disabled_indices = {3} if state.view == View.ANNUAL else set()

        pad_x = tokens.FOOTER_BUTTON_PADDING_X
        font = self._font("body_regular", TEXT_XS)
        x = pad_x
        # Reset hit-rects for this render pass
        self._footer_rects = {}
        for i, (sym, label) in enumerate(buttons):
            color = ink_faint if i in disabled_indices else ink
            text = f"{sym}  {label}"
            bbox = draw.textbbox((0, 0), text, font=font)
            text_w = bbox[2] - bbox[0]
            draw.text((x, y_top + FOOTER_HEIGHT // 2), text,
                      font=font, fill=color, anchor="lm")
            # Record clickable rect (full footer height) only for enabled buttons
            if i not in disabled_indices:
                x1 = x - pad_x
                x2 = x + text_w + pad_x
                self._footer_rects[_BUTTON_ACTIONS[i]] = (x1, y_top, x2, h)
            x += text_w + pad_x * 2
            # Separator
            if i < len(buttons) - 1:
                draw.line([(x - pad_x, y_top + 8), (x - pad_x, h - 8)],
                          fill=rule, width=1)

    # ------------------------------------------------------------------
    # Content dispatcher
    # ------------------------------------------------------------------

    def _draw_content(
        self,
        draw: ImageDraw.ImageDraw,
        img: Image.Image,
        state: NavigationState,
        palette: dict[str, str],
        events: list[CalendarEvent],
    ) -> None:
        if state.view == View.ANNUAL:
            self._draw_annual(draw, img, state, palette, events)
        elif state.view == View.MONTHLY:
            self._draw_monthly(draw, img, state, palette, events)
        elif state.view == View.WEEKLY:
            self._draw_weekly(draw, img, state, palette, events)
        elif state.view == View.DAILY:
            self._draw_daily(draw, img, state, palette, events)
        elif state.view == View.DETAIL:
            self._draw_detail(draw, img, state, palette, events)

    # ------------------------------------------------------------------
    # Annual view
    # ------------------------------------------------------------------

    def _draw_annual(
        self,
        draw: ImageDraw.ImageDraw,
        img: Image.Image,
        state: NavigationState,
        palette: dict[str, str],
        events: list[CalendarEvent],
    ) -> None:
        w = self._config.width
        h = self._config.height
        content_y = HEADER_HEIGHT + 4
        content_h = h - FOOTER_HEIGHT - content_y
        content_w = w

        cols = 4
        rows = 3
        cell_w = content_w // cols
        cell_h = content_h // rows

        today = date.today()
        year = state.selected_date.year
        selected_month = state.selected_date.month

        # Collect dates with events for dot markers
        event_dates: set[date] = {e.start.date() for e in events}

        font_month = self._font("body_semibold", TEXT_SM)
        font_day = self._font("mono_regular", TEXT_XS)

        for month_idx in range(12):
            month_num = month_idx + 1
            col = month_idx % cols
            row = month_idx // cols
            cell_x = col * cell_w
            cell_y = content_y + row * cell_h

            # Month heading
            month_label = _MONTHS_SHORT_IT[month_idx]
            draw.text(
                (cell_x + 8, cell_y + 4),
                month_label,
                font=font_month,
                fill=_hex_to_rgb(palette["INK"]),
            )

            # Selected month outline
            if month_num == selected_month:
                draw.rectangle(
                    [cell_x + 1, cell_y + 1, cell_x + cell_w - 2, cell_y + cell_h - 2],
                    outline=_hex_to_rgb(palette["RULE_STRONG"]),
                    width=2,
                )

            # Day grid
            heading_h = TEXT_SM + 8
            day_area_y = cell_y + heading_h
            # Day names row (L M M G V S D)
            day_labels = "L M M G V S D".split()
            day_cell_w = (cell_w - 16) // 7
            for di, dl in enumerate(day_labels):
                draw.text(
                    (cell_x + 8 + di * day_cell_w + day_cell_w // 2, day_area_y),
                    dl,
                    font=font_day,
                    fill=_hex_to_rgb(palette["INK_MUTED"]),
                    anchor="mt",
                )

            row_y = day_area_y + TEXT_XS + 4
            cal = calendar.monthcalendar(year, month_num)
            for week in cal:
                for wd, day_num in enumerate(week):
                    if day_num == 0:
                        continue
                    dx = cell_x + 8 + wd * day_cell_w + day_cell_w // 2
                    dy = row_y
                    day_date = date(year, month_num, day_num)
                    is_today = (day_date == today)

                    if is_today:
                        # 16×16 filled square
                        sq = 8  # half side
                        draw.rectangle(
                            [dx - sq, dy, dx + sq, dy + 16],
                            fill=_hex_to_rgb(palette["ACCENT"]),
                        )
                        draw.text(
                            (dx, dy + 8),
                            str(day_num),
                            font=font_day,
                            fill=_hex_to_rgb(palette["BG"]),
                            anchor="mm",
                        )
                    else:
                        draw.text(
                            (dx, dy + 8),
                            str(day_num),
                            font=font_day,
                            fill=_hex_to_rgb(palette["INK"]),
                            anchor="mm",
                        )

                row_y += TEXT_XS + 4

    # ------------------------------------------------------------------
    # Monthly view
    # ------------------------------------------------------------------

    def _draw_monthly(
        self,
        draw: ImageDraw.ImageDraw,
        img: Image.Image,
        state: NavigationState,
        palette: dict[str, str],
        events: list[CalendarEvent],
    ) -> None:
        w = self._config.width
        h = self._config.height
        content_y = HEADER_HEIGHT + 1
        content_h = h - FOOTER_HEIGHT - content_y

        today = date.today()
        sel_date = state.selected_date
        year, month = sel_date.year, sel_date.month
        selected_week_monday = _monday_of_week(sel_date)

        event_dates: set[date] = {e.start.date() for e in events}

        font_heading = self._font("body_semibold", TEXT_SM)
        font_day = self._font("body_regular", TEXT_MD)
        font_small = self._font("mono_regular", TEXT_XS)

        col_w = w // 7
        # Day-of-week headers
        header_row_h = TEXT_SM + 12
        for di, label in enumerate(_DAYS_SHORT_IT):
            x_center = di * col_w + col_w // 2
            draw.text(
                (x_center, content_y + header_row_h // 2),
                label,
                font=font_heading,
                fill=_hex_to_rgb(palette["INK_MUTED"]),
                anchor="mm",
            )
        # Divider under day labels
        rule_y = content_y + header_row_h
        draw.line([(0, rule_y), (w - 1, rule_y)],
                  fill=_hex_to_rgb(palette["RULE"]), width=1)

        cal = calendar.monthcalendar(year, month)
        rows = len(cal)
        row_h = (content_h - header_row_h - 1) // rows

        for row_idx, week in enumerate(cal):
            row_y = rule_y + 1 + row_idx * row_h
            week_monday = None

            # Find the Monday of this week from the first non-zero day
            for di, day_num in enumerate(week):
                if day_num != 0:
                    d_in_week = date(year, month, day_num) - timedelta(days=di)
                    week_monday = d_in_week
                    break

            is_selected_week = week_monday is not None and week_monday == selected_week_monday

            # Selected week background + borders
            if is_selected_week:
                draw.rectangle(
                    [0, row_y, w - 1, row_y + row_h - 1],
                    fill=_hex_to_rgb(palette["BG_ALT"]),
                )
                draw.line([(0, row_y), (w - 1, row_y)],
                          fill=_hex_to_rgb(palette["RULE_STRONG"]), width=2)
                draw.line([(0, row_y + row_h - 1), (w - 1, row_y + row_h - 1)],
                          fill=_hex_to_rgb(palette["RULE_STRONG"]), width=2)
            else:
                draw.line([(0, row_y + row_h - 1), (w - 1, row_y + row_h - 1)],
                          fill=_hex_to_rgb(palette["RULE"]), width=1)

            for col_idx, day_num in enumerate(week):
                x_center = col_idx * col_w + col_w // 2
                y_center = row_y + row_h // 2

                if day_num == 0:
                    continue

                # Check if this day belongs to current month
                try:
                    day_date = date(year, month, day_num)
                    in_month = True
                except ValueError:
                    in_month = False

                is_today = (day_date == today) if in_month else False
                has_events = day_date in event_dates if in_month else False

                text_color = _hex_to_rgb(palette["INK"] if in_month else palette["INK_FAINT"])

                if is_today:
                    sq = 14
                    draw.rectangle(
                        [x_center - sq, y_center - sq, x_center + sq, y_center + sq],
                        fill=_hex_to_rgb(palette["ACCENT"]),
                    )
                    draw.text(
                        (x_center, y_center),
                        str(day_num),
                        font=self._font("body_semibold", TEXT_MD),
                        fill=_hex_to_rgb(palette["BG"]),
                        anchor="mm",
                    )
                else:
                    draw.text(
                        (x_center, y_center),
                        str(day_num),
                        font=self._font("body_regular", TEXT_MD),
                        fill=text_color,
                        anchor="mm",
                    )

                # Event indicator dash
                if has_events and in_month:
                    draw.text(
                        (x_center, y_center + TEXT_MD // 2 + 4),
                        "—",
                        font=font_small,
                        fill=_hex_to_rgb(palette["INK_MUTED"]),
                        anchor="mt",
                    )

    # ------------------------------------------------------------------
    # Weekly view
    # ------------------------------------------------------------------

    def _draw_weekly(
        self,
        draw: ImageDraw.ImageDraw,
        img: Image.Image,
        state: NavigationState,
        palette: dict[str, str],
        events: list[CalendarEvent],
    ) -> None:
        w = self._config.width
        h = self._config.height
        today = date.today()
        monday = _monday_of_week(state.selected_date)

        content_y = HEADER_HEIGHT + 1
        content_h = h - FOOTER_HEIGHT - content_y

        time_col_x = WEEKLY_TIME_COL_W
        grid_x = time_col_x
        grid_w = w - time_col_x
        day_col_w = grid_w // 7

        allday_y = content_y
        allday_bottom = allday_y + ALLDAY_STRIP_H
        grid_y = allday_bottom + 1
        grid_h = content_h - ALLDAY_STRIP_H - 1
        slot_h = grid_h / WEEKLY_HOURS  # pixels per hour

        font_hour = self._font("mono_regular", TEXT_XS)
        font_day_hdr = self._font("body_semibold", TEXT_SM)
        font_event = self._font("body_semibold", TEXT_SM)
        font_event_time = self._font("mono_regular", TEXT_XS)

        # Background
        draw.rectangle([0, content_y, w - 1, h - FOOTER_HEIGHT - 1],
                       fill=_hex_to_rgb(palette["BG"]))

        # All-day strip separator
        draw.line([(0, allday_bottom), (w - 1, allday_bottom)],
                  fill=_hex_to_rgb(palette["RULE_STRONG"]), width=1)

        # Day column headers
        for di in range(7):
            day_date = monday + timedelta(days=di)
            col_x = grid_x + di * day_col_w
            is_today = (day_date == today)
            is_selected = (day_date == state.selected_date)

            label = f"{_DAYS_SHORT_IT[di]} {day_date.day}"
            if is_today:
                draw.rectangle(
                    [col_x, allday_y, col_x + day_col_w - 1, allday_bottom - 1],
                    fill=_hex_to_rgb(palette["ACCENT"]),
                )
                draw.text(
                    (col_x + day_col_w // 2, allday_y + ALLDAY_STRIP_H // 2),
                    label,
                    font=font_day_hdr,
                    fill=_hex_to_rgb(palette["BG"]),
                    anchor="mm",
                )
            else:
                draw.text(
                    (col_x + day_col_w // 2, allday_y + ALLDAY_STRIP_H // 2),
                    label,
                    font=font_day_hdr,
                    fill=_hex_to_rgb(palette["INK"]),
                    anchor="mm",
                )
                if is_selected:
                    draw.line(
                        [(col_x, allday_bottom - 2), (col_x + day_col_w - 1, allday_bottom - 2)],
                        fill=_hex_to_rgb(palette["RULE_STRONG"]),
                        width=2,
                    )

            # Vertical column separator
            if di > 0:
                draw.line(
                    [(col_x, allday_y), (col_x, h - FOOTER_HEIGHT - 1)],
                    fill=_hex_to_rgb(palette["RULE"]),
                    width=1,
                )

        # Hourly grid lines + time labels
        for hour in range(WEEKLY_HOURS + 1):
            y = int(grid_y + hour * slot_h)
            draw.line([(grid_x, y), (w - 1, y)],
                      fill=_hex_to_rgb(palette["RULE"]), width=1)
            hour_actual = WEEKLY_START_HOUR + hour
            if hour_actual <= WEEKLY_END_HOUR:
                draw.text(
                    (time_col_x - 4, y),
                    f"{hour_actual:02d}:00",
                    font=font_hour,
                    fill=_hex_to_rgb(palette["INK_MUTED"]),
                    anchor="rt",
                )

        # Current time indicator
        now = datetime.now()
        if monday <= now.date() <= monday + timedelta(days=6):
            now_h = now.hour + now.minute / 60.0
            if WEEKLY_START_HOUR <= now_h <= WEEKLY_END_HOUR:
                now_y = int(grid_y + (now_h - WEEKLY_START_HOUR) * slot_h)
                draw.line([(grid_x, now_y), (w - 1, now_y)],
                          fill=_hex_to_rgb(palette["ACCENT"]), width=1)

        # Event blocks
        timed_events = [e for e in events if not e.all_day]
        allday_events = [e for e in events if e.all_day]

        # All-day events in the strip
        allday_font = self._font("body_regular", TEXT_XS)
        allday_x = grid_x
        for ev in allday_events:
            di = (ev.start.date() - monday).days
            if 0 <= di <= 6:
                col_x = grid_x + di * day_col_w
                draw.rectangle(
                    [col_x + 1, allday_y + 2, col_x + day_col_w - 2, allday_bottom - 3],
                    fill=_hex_to_rgb(palette["BG_ALT"]),
                    outline=_hex_to_rgb(palette["RULE_STRONG"]),
                    width=1,
                )
                draw.text(
                    (col_x + 4, allday_y + ALLDAY_STRIP_H // 2),
                    ev.title,
                    font=allday_font,
                    fill=_hex_to_rgb(palette["INK"]),
                    anchor="lm",
                )

        # Timed events
        for ev in timed_events:
            di = (ev.start.date() - monday).days
            if not (0 <= di <= 6):
                continue

            ev_start_h = ev.start.hour + ev.start.minute / 60.0
            ev_end_h = ev.end.hour + ev.end.minute / 60.0
            ev_start_h = _clamp(ev_start_h, WEEKLY_START_HOUR, WEEKLY_END_HOUR)
            ev_end_h = _clamp(ev_end_h, WEEKLY_START_HOUR, WEEKLY_END_HOUR)

            if ev_start_h >= ev_end_h:
                continue

            col_x = grid_x + di * day_col_w
            y1 = int(grid_y + (ev_start_h - WEEKLY_START_HOUR) * slot_h)
            y2 = int(grid_y + (ev_end_h - WEEKLY_START_HOUR) * slot_h)
            y2 = max(y2, y1 + TEXT_SM + 4)

            is_selected = (ev.uid == state.selected_event_uid)
            if is_selected:
                bg_fill = _hex_to_rgb(palette["ACCENT"])
                text_fill = _hex_to_rgb(palette["BG"])
                border_w = 2
            else:
                bg_fill = _hex_to_rgb(palette["BG_ALT"])
                text_fill = _hex_to_rgb(palette["INK"])
                border_w = 1

            draw.rectangle(
                [col_x + 2, y1, col_x + day_col_w - 3, y2],
                fill=bg_fill,
                outline=_hex_to_rgb(palette["RULE_STRONG"]),
                width=border_w,
            )
            draw.text(
                (col_x + 4, y1 + 2),
                ev.title,
                font=font_event,
                fill=text_fill,
            )
            time_label = ev.start.strftime("%H:%M")
            draw.text(
                (col_x + 4, y1 + TEXT_SM + 4),
                time_label,
                font=font_event_time,
                fill=text_fill,
            )

    # ------------------------------------------------------------------
    # Daily view
    # ------------------------------------------------------------------

    def _draw_daily(
        self,
        draw: ImageDraw.ImageDraw,
        img: Image.Image,
        state: NavigationState,
        palette: dict[str, str],
        events: list[CalendarEvent],
    ) -> None:
        w = self._config.width
        h = self._config.height
        content_y = HEADER_HEIGHT + 1
        content_h = h - FOOTER_HEIGHT - content_y

        day_events = sorted(
            [e for e in events if e.start.date() == state.selected_date],
            key=lambda e: e.start,
        )

        font_time = self._font("mono_regular", TEXT_SM)
        font_title = self._font("body_semibold", TEXT_BASE)
        font_interval = self._font("body_regular", TEXT_SM)
        font_free = self._font("body_regular", TEXT_XS)

        time_col_w = DAILY_TIME_COL_W
        event_x = time_col_w + 8
        row_h = 52  # approximate height per event block
        visible_count = content_h // row_h

        # Pagination: scroll by selected event index
        selected_idx = 0
        if state.selected_event_uid:
            for i, ev in enumerate(day_events):
                if ev.uid == state.selected_event_uid:
                    selected_idx = i
                    break

        page_start = max(0, selected_idx - (visible_count // 2))
        page_start = min(page_start, max(0, len(day_events) - visible_count))

        # Build display list inserting "Libero" slots
        display_items: list[tuple[str, CalendarEvent | None, str]] = []
        prev_end: datetime | None = None

        for ev in day_events[page_start:page_start + visible_count]:
            if prev_end is not None:
                gap_min = (ev.start - prev_end).total_seconds() / 60
                if gap_min >= FREE_SLOT_MIN_MINUTES:
                    display_items.append(("free", None, ""))
            display_items.append(("event", ev, ""))
            prev_end = ev.end

        y = content_y + 4

        if not day_events:
            draw.text(
                (w // 2, content_y + content_h // 2),
                "Nessun appuntamento",
                font=self._font("body_regular", TEXT_BASE),
                fill=_hex_to_rgb(palette["INK_FAINT"]),
                anchor="mm",
            )
            return

        for item_type, ev, _ in display_items:
            if item_type == "free":
                draw.text(
                    (event_x, y + 8),
                    "────  Libero  ────",
                    font=font_free,
                    fill=_hex_to_rgb(palette["INK_FAINT"]),
                )
                y += 24
                continue

            if ev is None:
                continue

            is_selected = (ev.uid == state.selected_event_uid)

            # Top rule
            draw.line([(0, y), (w - 1, y)],
                      fill=_hex_to_rgb(palette["RULE"]), width=1)

            # Selected indicator: left border + background
            if is_selected:
                draw.rectangle(
                    [0, y + 1, w - 1, y + row_h - 1],
                    fill=_hex_to_rgb(palette["BG_ALT"]),
                )
                draw.rectangle(
                    [0, y + 1, 3, y + row_h - 1],
                    fill=_hex_to_rgb(palette["RULE_STRONG"]),
                )

            # Time label in left column
            time_str = ev.start.strftime("%H:%M")
            draw.text(
                (time_col_w - 4, y + row_h // 2),
                time_str,
                font=font_time,
                fill=_hex_to_rgb(palette["INK_MUTED"]),
                anchor="rm",
            )

            # Event title
            draw.text(
                (event_x, y + 6),
                ev.title,
                font=font_title,
                fill=_hex_to_rgb(palette["INK"]),
            )

            # Time interval
            interval_str = (
                f"{ev.start.strftime('%H:%M')} – {ev.end.strftime('%H:%M')}"
            )
            draw.text(
                (event_x, y + 6 + TEXT_BASE + 4),
                interval_str,
                font=font_interval,
                fill=_hex_to_rgb(palette["INK_MUTED"]),
            )

            y += row_h

    # ------------------------------------------------------------------
    # Detail view
    # ------------------------------------------------------------------

    def _draw_detail(
        self,
        draw: ImageDraw.ImageDraw,
        img: Image.Image,
        state: NavigationState,
        palette: dict[str, str],
        events: list[CalendarEvent],
    ) -> None:
        w = self._config.width
        h = self._config.height
        content_y = HEADER_HEIGHT + 1
        content_h = h - FOOTER_HEIGHT - content_y

        # Find the event
        ev: CalendarEvent | None = None
        if state.selected_event_uid:
            for e in events:
                if e.uid == state.selected_event_uid:
                    ev = e
                    break

        if ev is None:
            draw.text(
                (w // 2, content_y + content_h // 2),
                "Nessun appuntamento selezionato",
                font=self._font("body_regular", TEXT_BASE),
                fill=_hex_to_rgb(palette["INK_FAINT"]),
                anchor="mm",
            )
            return

        ink = _hex_to_rgb(palette["INK"])
        ink_muted = _hex_to_rgb(palette["INK_MUTED"])
        ink_faint = _hex_to_rgb(palette["INK_FAINT"])
        rule = _hex_to_rgb(palette["RULE"])

        margin = 24
        x = margin
        y = content_y + 16

        # Double-line separator above title
        sep = "═" * ((w - 2 * margin) // 10)
        font_sep = self._font("mono_regular", TEXT_SM)
        draw.text((x, y), sep, font=font_sep, fill=_hex_to_rgb(palette["RULE_STRONG"]))
        y += TEXT_SM + 4

        # Title
        font_title = self._font("display_bold", TEXT_XL)
        title_text = ev.title.upper()
        draw.text((x, y), title_text, font=font_title, fill=ink)
        y += TEXT_XL + 6

        # Double-line separator below title
        draw.text((x, y), sep, font=font_sep, fill=_hex_to_rgb(palette["RULE_STRONG"]))
        y += TEXT_SM + 16

        font_label = self._font("body_regular", TEXT_BASE)
        icon_size = 16
        row_spacing = tokens.DETAIL_ROW_SPACING

        # Date/time row
        duration_min = int((ev.end - ev.start).total_seconds() / 60)
        duration_str = self._format_duration(duration_min)
        day_str = (
            f"{_DAYS_SHORT_IT[ev.start.weekday()]},  "
            f"{ev.start.day} {_MONTHS_IT[ev.start.month - 1]} {ev.start.year}"
        )
        time_str = f"{ev.start.strftime('%H:%M')} – {ev.end.strftime('%H:%M')}  ({duration_str})"
        self._draw_info_row(draw, img, x, y, palette, "clock", day_str, second_line=time_str)
        y += TEXT_BASE * 2 + row_spacing + 4

        # Location row
        if ev.location:
            self._draw_info_row(draw, img, x, y, palette, "map-pin", ev.location)
            y += TEXT_BASE + row_spacing

        # Attendees row
        if ev.attendees:
            attendees_str = ", ".join(ev.attendees)
            self._draw_info_row(draw, img, x, y, palette, "users", attendees_str)
            y += TEXT_BASE + row_spacing

        # Recurrence row
        recurrence_str = "Ricorrente" if ev.recurrent else "Non ricorrente"
        self._draw_info_row(draw, img, x, y, palette, "repeat", recurrence_str)
        y += TEXT_BASE + row_spacing + 8

        # Notes section
        if ev.description:
            draw.line([(x, y), (w - margin, y)], fill=rule, width=1)
            y += 8
            font_notes_label = self._font("body_semibold", TEXT_SM)
            draw.text((x, y), "NOTE", font=font_notes_label, fill=ink_muted)
            y += TEXT_SM + 6

            font_notes = self._font("body_regular", TEXT_SM)
            notes_area_h = h - FOOTER_HEIGHT - y - 24
            lines = self._wrap_text(ev.description, font_notes, w - 2 * margin, draw)
            line_h = TEXT_SM + 4
            max_lines = notes_area_h // line_h
            offset = state.detail_scroll_offset
            visible_lines = lines[offset: offset + max_lines]

            for line in visible_lines:
                draw.text((x, y), line, font=font_notes, fill=ink)
                y += line_h

            # Overflow indicator
            if offset + max_lines < len(lines):
                draw.text(
                    (w - margin, h - FOOTER_HEIGHT - 16),
                    "▼",
                    font=self._font("body_regular", TEXT_SM),
                    fill=ink_faint,
                    anchor="rm",
                )

    def _draw_info_row(
        self,
        draw: ImageDraw.ImageDraw,
        img: Image.Image,
        x: int,
        y: int,
        palette: dict[str, str],
        icon_name: str,
        text: str,
        second_line: str | None = None,
    ) -> None:
        """Draw an icon + text row in the detail view."""
        icon_size = 16
        text_x = x + icon_size + 8
        font = self._font("body_regular", TEXT_BASE)
        ink = _hex_to_rgb(palette["INK"])

        # Icon (if available)
        icon_key_candidates = [
            f"{icon_name}-{icon_size}",
            icon_name,
        ]
        icon_img = None
        for key in icon_key_candidates:
            if key in self._icons:
                icon_img = self._icons[key]
                break

        if icon_img is not None:
            icon_resized = icon_img.resize((icon_size, icon_size), Image.Resampling.LANCZOS)
            # Tint the icon to the ink colour
            tinted = self._tint_icon(icon_resized, palette["INK"])
            img.paste(tinted, (x, y), tinted)

        draw.text((text_x, y), text, font=font, fill=ink)
        if second_line:
            draw.text(
                (text_x, y + TEXT_BASE + 2),
                second_line,
                font=self._font("mono_regular", TEXT_SM),
                fill=_hex_to_rgb(palette["INK_MUTED"]),
            )

    @staticmethod
    def _tint_icon(icon: Image.Image, hex_color: str) -> Image.Image:
        """Return a copy of *icon* (RGBA) tinted to *hex_color*."""
        r, g, b = _hex_to_rgb(hex_color)
        tinted = Image.new("RGBA", icon.size, (r, g, b, 0))
        _, _, _, alpha = icon.split()
        tinted.putalpha(alpha)
        return tinted

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _font(self, name: str, size: int) -> ImageFont.FreeTypeFont:
        """Return the font *name* at *size*, falling back gracefully."""
        font_map = self._fonts.get(name, {})
        if size in font_map:
            return font_map[size]
        # Try the closest available size
        if font_map:
            closest = min(font_map.keys(), key=lambda s: abs(s - size))
            return font_map[closest]
        return ImageFont.load_default()

    @staticmethod
    def _wrap_text(
        text: str,
        font: ImageFont.FreeTypeFont,
        max_width: int,
        draw: ImageDraw.ImageDraw,
    ) -> list[str]:
        """Wrap *text* to lines that fit within *max_width* pixels."""
        lines: list[str] = []
        for paragraph in text.splitlines():
            words = paragraph.split()
            current = ""
            for word in words:
                candidate = f"{current} {word}".strip()
                bbox = draw.textbbox((0, 0), candidate, font=font)
                if bbox[2] - bbox[0] <= max_width:
                    current = candidate
                else:
                    if current:
                        lines.append(current)
                    current = word
            if current:
                lines.append(current)
        return lines

    @staticmethod
    def _format_duration(minutes: int) -> str:
        """Format a duration in minutes as a human-readable Italian string."""
        h, m = divmod(minutes, 60)
        if h and m:
            return f"{h}h {m}min"
        if h:
            return f"{h}h"
        return f"{m}min"
