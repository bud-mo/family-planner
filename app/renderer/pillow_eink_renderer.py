"""Pillow-native renderer for Family Planner — Home view.

Single-screen layout: weather banner · mini-calendar · agenda · footer.

``PillowEinkRenderer`` renders a ``PIL.Image`` directly from ``NavigationState``
and a list of ``CalendarEvent`` objects, without involving a browser or network.
It is the sole renderer for both HDMI (pygame) and e-ink (Waveshare) displays.

Usage::

    renderer = PillowEinkRenderer(config)
    state = state_manager.get()
    start, end = events_range_for_state(state)
    events = aggregator.get_events(start, end)
    img = renderer.render(state, events)      # PIL.Image RGB
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from PIL import Image, ImageDraw, ImageFont

from app.calendar.data_builders import _build_month_grid
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
    TEXT_SM,
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
        self._font_label: ImageFont.FreeTypeFont = self._load_font(FONT_BODY_SEMIBOLD, TEXT_XS)
        self._font_mono: ImageFont.FreeTypeFont = self._load_font(FONT_MONO_REGULAR, TEXT_SM)

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
        palette = get_palette(state.night_mode)
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
        self._draw_footer(draw, footer_rect, state, palette)
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
            temp_str = f"{weather.temp_current:.0f}°"
            draw.text(
                (right_x, y_mid),
                temp_str,
                font=self._font_body,
                fill=palette["INK"],
                anchor="rm",
            )
            if weather.temp_max is not None and weather.temp_min is not None:
                range_str = f"\u2191{weather.temp_max:.0f}° \u2193{weather.temp_min:.0f}°"
                draw.text(
                    (right_x, y_mid + 14),
                    range_str,
                    font=self._font_label,
                    fill=palette["INK_MUTED"],
                    anchor="rm",
                )

            # Weather condition icon (24px Tabler Icons PNG).
            if weather.condition_icon is not None:
                icon_img = load_icon(weather.condition_icon, 24)
                if icon_img is not None:
                    r, g, b = self._hex_to_rgb(palette["INK"])
                    _, _, _, alpha = icon_img.split()
                    tinted = Image.new("RGBA", icon_img.size, (r, g, b, 255))
                    tinted.putalpha(alpha)
                    temp_w = int(draw.textlength(temp_str, font=self._font_body))
                    icon_x = right_x - temp_w - 8 - 24
                    icon_y = y_mid - 12
                    img.paste(tinted, (icon_x, icon_y), mask=tinted)

        draw.line(
            [(x0, y0 + h - 1), (x0 + w, y0 + h - 1)],
            fill=palette["RULE_STRONG"],
            width=2,
        )

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
        year = state.anchor_date.year
        month = state.anchor_date.month
        weeks = _build_month_grid(year, month, events, today)

        month_header_h = 20
        dow_header_h = 16

        # Month header
        month_label = f"{_MONTH_NAMES_IT[month - 1].upper()} {year}"
        draw.text(
            (x0 + w // 2, y0 + month_header_h // 2),
            month_label,
            font=self._font_label,
            fill=palette["INK"],
            anchor="mm",
        )

        # DOW header
        dow_y = y0 + month_header_h + dow_header_h // 2
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

        # Grid
        grid_top = y0 + month_header_h + dow_header_h
        grid_h = h - month_header_h - dow_header_h
        n_rows = len(weeks)
        cell_h = grid_h / n_rows

        for row_idx, week in enumerate(weeks):
            for col_idx, cell in enumerate(week):
                cx0 = x0 + col_idx * cell_w
                cy0 = grid_top + row_idx * cell_h
                cx_mid = cx0 + cell_w / 2
                cy_mid = cy0 + cell_h / 2

                if cell["is_today"]:
                    sq = 16
                    half = sq // 2
                    draw.rectangle(
                        [cx_mid - half, cy_mid - half, cx_mid + half, cy_mid + half],
                        fill=palette["ACCENT"],
                    )
                    ink = palette["BG"]
                else:
                    ink = palette["INK"] if cell["is_current_month"] else palette["INK_FAINT"]

                draw.text(
                    (cx_mid, cy_mid),
                    str(cell["day_number"]),
                    font=self._font_label,
                    fill=ink,
                    anchor="mm",
                )

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
        separator_h = 16
        event_row_h = 28
        event_row_loc_h = 42
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

        # Build ordered list of items: (type, payload) — skip days with no events
        items: list[tuple[str, object]] = []
        for d_offset in range(_WINDOW_DAYS):
            day = window_start + timedelta(days=d_offset)
            if not days_events[day]:
                continue
            items.append(("separator", day))
            for evt in days_events[day]:
                items.append(("event", evt))

        # First pass: determine what fits and count overflow
        cur_y = y0
        max_y = y0 + h
        rendered: list[tuple[str, object]] = []
        remaining_count = 0
        in_overflow = False

        for item_type, item in items:
            if in_overflow:
                if item_type == "event":
                    remaining_count += 1
                continue

            if item_type == "separator":
                if cur_y + separator_h > max_y:
                    in_overflow = True
                    continue
                rendered.append((item_type, item))
                cur_y += separator_h
            else:
                evt = item
                row_h = event_row_loc_h if evt.location else event_row_h  # type: ignore[union-attr]
                # Reserve one event_row_h for the overflow indicator
                if cur_y + row_h > max_y - event_row_h:
                    in_overflow = True
                    remaining_count += 1
                    continue
                rendered.append((item_type, item))
                cur_y += row_h

        # Second pass: draw
        cur_y = y0
        prev_was_separator = False
        for item_type, item in rendered:
            if item_type == "separator":
                self._draw_date_separator(
                    draw, item, x0, cur_y, w, separator_h, padding_x, palette  # type: ignore[arg-type]
                )
                cur_y += separator_h
                prev_was_separator = True
            else:
                evt = item
                row_h = event_row_loc_h if evt.location else event_row_h  # type: ignore[union-attr]
                self._draw_event_row(
                    draw, img, evt, x0, cur_y, w, row_h, padding_x, time_col_w, palette,  # type: ignore[arg-type]
                    first_in_day=prev_was_separator,
                )
                cur_y += row_h
                prev_was_separator = False

        # Overflow indicator
        if remaining_count > 0 and cur_y + event_row_h <= max_y:
            draw.text(
                (x0 + w // 2, cur_y + event_row_h // 2),
                f"… altri {remaining_count} appuntamenti",
                font=self._font_label,
                fill=palette["INK_MUTED"],
                anchor="mm",
            )

    def _draw_date_separator(
        self,
        draw: ImageDraw.ImageDraw,
        day: date,
        x0: int,
        y0: int,
        w: int,
        h: int,
        padding_x: int,
        palette: dict[str, str],
    ) -> None:
        today = date.today()
        if day == today:
            label = (
                f"OGGI, {_DAY_NAMES_FULL_IT[day.weekday()].upper()} "
                f"{day.day} {_MONTH_NAMES_IT[day.month - 1].upper()}"
            )
        else:
            label = (
                f"{_DAY_NAMES_FULL_IT[day.weekday()].upper()} "
                f"{day.day} {_MONTH_NAMES_IT[day.month - 1].upper()}"
            )

        y_mid = y0 + h // 2
        text_x = x0 + padding_x + 8

        bbox = draw.textbbox((0, 0), label, font=self._font_label)
        text_w = bbox[2] - bbox[0]

        # Left rule
        if text_x > x0 + padding_x + 2:
            draw.line(
                [(x0 + padding_x, y_mid), (text_x - 4, y_mid)],
                fill=palette["RULE"],
            )

        draw.text(
            (text_x, y_mid),
            label,
            font=self._font_label,
            fill=palette["INK_MUTED"],
            anchor="lm",
        )

        # Right rule
        right_x = text_x + text_w + 4
        if right_x < x0 + w - padding_x:
            draw.line(
                [(right_x, y_mid), (x0 + w - padding_x, y_mid)],
                fill=palette["RULE"],
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
        palette: dict[str, str],
        first_in_day: bool = False,
    ) -> None:
        # Top separator (omitted for the first event of each day)
        if not first_in_day:
            draw.line([(x0 + padding_x, y0), (x0 + w - padding_x, y0)], fill=palette["RULE"])

        sep_x = x0 + padding_x + time_col_w
        title_x = sep_x + 8
        title_max_w = w - (title_x - x0) - padding_x

        # Vertical position: centre, or upper third if location present
        if evt.location:
            time_y = y0 + row_h // 3
        else:
            time_y = y0 + row_h // 2

        # Time (omitted for all-day events)
        if not evt.all_day:
            local_start = evt.start.astimezone(self._tz) if self._tz else evt.start
            draw.text(
                (sep_x - 4, time_y),
                local_start.strftime("%H:%M"),
                font=self._font_mono,
                fill=palette["INK_MUTED"],
                anchor="rm",
            )

        # Vertical separator
        draw.line([(sep_x, y0 + 4), (sep_x, y0 + row_h - 4)], fill=palette["RULE"])

        # Title — emoji characters are replaced with inline Tabler icons
        icon_size_title = int(self._font_body.size * 0.75)
        title_segs = split_text_emoji(evt.title)
        title_segs = self._fit_mixed(draw, title_segs, self._font_body, icon_size_title, title_max_w)
        self._draw_mixed(draw, img, title_segs, title_x, time_y, self._font_body, palette["INK"], icon_size_title)

        # Location (second line, if present)
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
        state: NavigationState,
        palette: dict[str, str],
    ) -> None:
        x0, y0, w, h = rect

        # Top separator
        draw.line([(x0, y0), (x0 + w, y0)], fill=palette["RULE"])

        y_mid = y0 + h // 2
        button_padding = 16

        buttons: list[tuple[str, bool]] = [
            ("↑ Su", state.page_offset == 0),
            ("↓ Giù", False),
            ("← Oggi", False),
        ]
        if self._display_type == "hdmi":
            buttons.append(("☾ Notte", False))

        # Draw buttons left-to-right
        cur_x = x0
        for label, disabled in buttons:
            ink = palette["INK_FAINT"] if disabled else palette["INK"]
            bbox = draw.textbbox((0, 0), label, font=self._font_label)
            text_w = bbox[2] - bbox[0]
            btn_w = text_w + button_padding * 2
            draw.text(
                (cur_x + btn_w // 2, y_mid),
                label,
                font=self._font_label,
                fill=ink,
                anchor="mm",
            )
            cur_x += btn_w
            draw.line([(cur_x, y0 + 4), (cur_x, y0 + h - 4)], fill=palette["RULE"])

        # Status indicators (right-aligned)
        status_parts: list[tuple[str, ImageFont.FreeTypeFont]] = [
            (self._display_type, self._font_label),
            (self._layout, self._font_label),
        ]
        if self._display_type == "hdmi":
            mode_str = "☾ Notte" if state.night_mode else "☀ Giorno"
            status_parts.append((mode_str, self._font_label))
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
