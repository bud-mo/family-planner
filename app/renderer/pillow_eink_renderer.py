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

import io
import logging
import random
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from PIL import Image, ImageColor, ImageDraw, ImageFont, ImageOps

from app.calendar.data_builders import _build_month_grid, _build_rolling_week_grid
from app.renderer.emoji_icons import load_icon, split_text_emoji
from app.renderer.locale_it import (
    DAY_NAMES_FULL_IT as _DAY_NAMES_FULL_IT,
    DAY_NAMES_IT as _DAY_NAMES_IT,
    MONTH_NAMES_IT as _MONTH_NAMES_IT,
    MONTH_NAMES_SHORT_IT as _MONTH_NAMES_SHORT_IT,
)
from app.renderer.state import NavigationState
from app.renderer.rich_text import RichLine, RichSpan, parse_html_description
from app.renderer.tokens import (
    BANNER_HEIGHT,
    BANNER_HOURLY_HEIGHT,
    BANNER_MAIN_HEIGHT,
    CALENDAR_HEIGHT,
    COL_LEFT_RATIO,
    FONT_BODY_ITALIC,
    FONT_BODY_REGULAR,
    FONT_BODY_SEMIBOLD,
    FONT_DISPLAY_REGULAR,
    FONT_MONO_REGULAR,
    FONTS_DIR,
    FOOTER_HEIGHT,
    HourlySlot,
    Rect,
    TEXT_BASE,
    TEXT_LG,
    TEXT_MD,
    TEXT_SM,
    TEXT_XL,
    TEXT_XS,
    WEATHER_ICON_COLORS,
    WeatherData,
    get_palette,
)

if TYPE_CHECKING:
    from app.calendar.base import CalendarEvent
    from app.config import AppConfig
    from app.weather.provider import WeatherProvider

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Artwork — Art Institute of Chicago public API (no key required)
# ---------------------------------------------------------------------------

_ARTIC_SEARCH_URL: str = "https://api.artic.edu/api/v1/artworks/search"
_ARTIC_IIIF_TPL: str = (
    "https://www.artic.edu/iiif/2/{image_id}/full/{width},/0/default.jpg"
)


_ARTWORK_QUERY_DEFAULT: str = "landscape painting"


def _fetch_artwork(
    width: int,
    height: int,
    query: str = _ARTWORK_QUERY_DEFAULT,
) -> "tuple[Image.Image, str] | None":
    """Fetch a random public-domain artwork matching *query* from the Art
    Institute of Chicago and resize it to cover *width* × *height* exactly.

    Issues a POST search using *query* (public domain, with image) then
    downloads the chosen artwork via the IIIF endpoint, requesting *width*
    pixels wide (height is computed server-side, preserving aspect ratio).
    The resulting image is then crop-filled to the exact target size via
    ``ImageOps.fit``.

    Some IIIF images return 403 even when marked public domain — up to
    ``_MAX_ATTEMPTS`` candidates are tried before giving up.

    Returns a ``(image, caption)`` tuple where *caption* is a pre-formatted
    string (may be empty if no metadata is available), or ``None`` on any
    network or parse error — the caller falls back to a plain background.
    """
    _MAX_ATTEMPTS = 5
    # CloudFront protects the IIIF image server — a browser-like User-Agent
    # and Referer header are required to avoid 403/challenge responses.
    _BROWSER_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux aarch64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.artic.edu/",
    }
    try:
        import requests

        session = requests.Session()
        session.headers.update(_BROWSER_HEADERS)

        resp = session.post(
            _ARTIC_SEARCH_URL,
            json={
                "q": query,
                "query": {
                    "bool": {
                        "must": [
                            {"term": {"is_public_domain": True}},
                            {"exists": {"field": "image_id"}},
                        ]
                    }
                },
                "fields": ["id", "image_id", "title", "artist_display", "date_display"],
                "limit": 100,
            },
            timeout=8,
        )
        resp.raise_for_status()
        artworks = [a for a in resp.json().get("data", []) if a.get("image_id")]
        if not artworks:
            logger.warning("_fetch_artwork: nessun artwork trovato in risposta ARTIC.")
            return None

        random.shuffle(artworks)
        for attempt, artwork in enumerate(artworks[:_MAX_ATTEMPTS], start=1):
            img_url = _ARTIC_IIIF_TPL.format(image_id=artwork["image_id"], width=width)
            try:
                img_resp = session.get(img_url, timeout=15)
                img_resp.raise_for_status()
            except requests.exceptions.HTTPError as exc:
                logger.warning(
                    "_fetch_artwork: tentativo %d/%d fallito (%s) — provo il prossimo.",
                    attempt, _MAX_ATTEMPTS, exc,
                )
                continue
            img = Image.open(io.BytesIO(img_resp.content)).convert("RGB")
            cover = ImageOps.fit(img, (width, height), Image.Resampling.LANCZOS)

            # Build caption: "Title, Artist (Year)" — all fields optional.
            title = (artwork.get("title") or "").strip()
            # artist_display may be multi-line ("Name\nNationality, Dates") — keep first line only.
            artist = (artwork.get("artist_display") or "").split("\n")[0].strip()
            year = (artwork.get("date_display") or "").strip()
            parts = [p for p in [title, artist] if p]
            caption = ", ".join(parts)
            if year:
                caption = f"{caption} ({year})" if caption else f"({year})"

            logger.info(
                "_fetch_artwork: «%s» di %s",
                title or "?",
                artist or "?",
            )
            return cover, caption

        logger.warning("_fetch_artwork: tutti i %d tentativi falliti — uso sfondo BG.", _MAX_ATTEMPTS)
        return None
    except Exception:  # noqa: BLE001
        logger.exception("_fetch_artwork: impossibile scaricare artwork — uso sfondo BG.")
        return None



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
        _artwork_cfg = getattr(config, "artwork", None)
        self._artwork_query: str = _artwork_cfg.query if _artwork_cfg is not None else _ARTWORK_QUERY_DEFAULT

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
        # Pre-compute the widest Italian weekday abbreviation so the day number always
        # sits at the same x position regardless of which day is rendered.
        self._date_abbrev_slot_w: int = (
            max(int(self._font_label.getlength(a)) for a in _DAY_NAMES_IT) + 2
        )
        self._font_mono: ImageFont.FreeTypeFont = self._load_font(FONT_MONO_REGULAR, TEXT_SM)
        self._font_mono_xs: ImageFont.FreeTypeFont = self._load_font(FONT_MONO_REGULAR, TEXT_XS)
        self._font_temp: ImageFont.FreeTypeFont = self._load_font(FONT_BODY_SEMIBOLD, 40)
        self._font_hourly_temp: ImageFont.FreeTypeFont = self._load_font(FONT_BODY_SEMIBOLD, TEXT_SM)
        # Description rich-text fonts (TEXT_XS = 11 px)
        self._font_desc: ImageFont.FreeTypeFont = self._load_font(FONT_BODY_REGULAR, TEXT_XS)
        self._font_desc_bold: ImageFont.FreeTypeFont = self._load_font(FONT_BODY_SEMIBOLD, TEXT_XS)
        self._font_desc_italic: ImageFont.FreeTypeFont = self._load_font(FONT_BODY_ITALIC, TEXT_XS)
        # Icon size for inline emoji in description lines
        self._icon_size_desc: int = max(8, int(TEXT_XS * 0.75))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def render(
        self,
        state: NavigationState,
        events: list["CalendarEvent"],
        *,
        updated_at: datetime | None = None,
    ) -> Image.Image:
        """Render the Home view for *state* and *events* as an RGB ``PIL.Image``.

        *updated_at* is the moment the displayed data last changed; it is shown
        in the footer ("Ultimo aggiornamento").  When ``None`` (browser preview,
        HDMI) the current time is used, since those callers re-render on demand.
        """
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
        self._draw_footer(draw, footer_rect, palette, updated_at)
        return img

    def render_artwork(self) -> Image.Image:
        """Render a random public-domain landscape painting as an RGB ``PIL.Image``.

        Fetches the artwork from the Art Institute of Chicago Collection API and
        crop-fills the display area via ``ImageOps.fit``.  Falls back to a plain
        ``BG`` background if the network is unavailable or the request fails for
        any reason.  A caption with title, artist and year is drawn at the bottom
        centre when metadata is available.

        Returns:
            An RGB ``PIL.Image`` at the configured display resolution.
        """
        palette = get_palette()
        W, H = self._size
        img = Image.new("RGB", (W, H), palette["BG"])
        result = _fetch_artwork(W, H, self._artwork_query)
        if result is not None:
            artwork_img, caption = result
            img.paste(artwork_img)
            if caption:
                self._draw_artwork_caption(img, caption, palette)
        return img

    def _draw_artwork_caption(
        self,
        img: Image.Image,
        caption: str,
        palette: dict[str, str],
    ) -> None:
        """Draw a caption box centred at the bottom edge of *img*."""
        W, H = self._size
        draw = ImageDraw.Draw(img)
        font = self._font_desc_italic

        PAD_X = 16
        PAD_Y = 7
        MARGIN_BOTTOM = 30
        MAX_W = int(W * 0.80)  # caption at most 80% of display width

        # Truncate with ellipsis if the text is too wide.
        text = caption
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        if text_w > MAX_W - PAD_X * 2:
            while text and text_w > MAX_W - PAD_X * 2 - draw.textlength("…", font=font):
                text = text[:-1]
                bbox = draw.textbbox((0, 0), text, font=font)
                text_w = bbox[2] - bbox[0]
            text = text.rstrip(", ") + "…"
            bbox = draw.textbbox((0, 0), text, font=font)
            text_w = bbox[2] - bbox[0]

        text_h = bbox[3] - bbox[1]
        box_w = text_w + PAD_X * 2
        box_h = text_h + PAD_Y * 2

        x0 = (W - box_w) // 2
        y0 = H - box_h - MARGIN_BOTTOM

        # Solid background box.
        draw.rectangle([x0, y0, x0 + box_w, y0 + box_h], fill=palette["BG"])
        # Top border line.
        draw.line([x0, y0, x0 + box_w, y0], fill=palette["INK_MUTED"], width=1)
        # Caption text.
        draw.text((x0 + PAD_X, y0 + PAD_Y), text, font=font, fill=palette["INK"])

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
        # In narrow landscape columns, shorten the date to prevent overflow onto weather data
        _max_date_w = int(w * 0.65)
        if draw.textlength(date_str, font=self._font_display) > _max_date_w:
            date_str = (
                f"{_DAY_NAMES_FULL_IT[today.weekday()]}, "
                f"{today.day} {_MONTH_NAMES_SHORT_IT[today.month - 1]} {today.year}"
            )
            if draw.textlength(date_str, font=self._font_display) > _max_date_w:
                date_str = (
                    f"{_DAY_NAMES_FULL_IT[today.weekday()]}, "
                    f"{today.day} {_MONTH_NAMES_SHORT_IT[today.month - 1]}"
                )
        y_mid = y0 + BANNER_MAIN_HEIGHT // 2
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
                _half_lh = (TEXT_XS + 5) // 2  # half visual line-height of font_label
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

            # Step 4: draw condition icon (48px), left of temperature
            if weather.condition_icon is not None:
                icon_img = load_icon(weather.condition_icon, 48)
                if icon_img is not None:
                    icon_color = WEATHER_ICON_COLORS.get(weather.condition_icon, palette["INK"])
                    r, g, b = self._hex_to_rgb(icon_color)
                    _, _, _, alpha = icon_img.split()
                    tinted = Image.new("RGBA", icon_img.size, (r, g, b, 255))
                    tinted.putalpha(alpha)
                    icon_x = temp_right_x - temp_w - 10 - 48
                    icon_y = y_mid - 24
                    img.paste(tinted, (icon_x, icon_y), mask=tinted)

        self._draw_hourly_row(
            draw, img, (x0, y0 + BANNER_MAIN_HEIGHT, w, BANNER_HOURLY_HEIGHT), weather, palette
        )
        draw.line(
            [(x0, y0 + h - 1), (x0 + w, y0 + h - 1)],
            fill=palette["RULE_STRONG"],
            width=2,
        )

    def _draw_hourly_row(
        self,
        draw: ImageDraw.ImageDraw,
        img: Image.Image,
        rect: Rect,
        weather: WeatherData,
        palette: dict[str, str],
    ) -> None:
        """Render the 6-cell bihourly forecast strip inside *rect*.

        Layout per cell (column, horizontally centred)::

            y+4   orario (centrato, mono xs)
            y+24  icona 48px (centrata)
            y-4   temperatura (centrata, semibold sm) — baseline ancorata in basso
        """
        if not weather.hourly_forecast:
            return

        x0, y0, w, _h = rect
        cell_w = w // 6
        r_ink, g_ink, b_ink = self._hex_to_rgb(palette["INK"])

        _PAD_TOP = 4    # padding from cell top edge to time-label anchor
        _PAD_BOTTOM = 27  # padding from last temp pixel to border (mirrors 27px gap above hourly row)
        _BORDER_H = 2  # border line thickness at bottom of cell

        # Measure actual text heights using tight font bounding boxes.
        # getbbox(anchor="lb") returns offsets relative to the baseline:
        #   [1] negative = ascent above baseline, [3] positive = descent below baseline
        _time_h = (
            self._font_mono_xs.getbbox("00:00")[3]
            - self._font_mono_xs.getbbox("00:00")[1]
        )
        _temp_bbox = self._font_hourly_temp.getbbox("0°", anchor="lb")
        _temp_ascent = -_temp_bbox[1]   # pixels above baseline
        _temp_descent = _temp_bbox[3]   # pixels below baseline
        _temp_h = _temp_ascent + _temp_descent

        # anchor="mt" at y0+_PAD_TOP → text bottom at y0+_PAD_TOP+_time_h
        _time_bottom = y0 + _PAD_TOP + _time_h
        # Bottom pixel of temp text lands at y0+_h-_BORDER_H-_PAD_BOTTOM
        _temp_baseline = y0 + _h - _BORDER_H - _PAD_BOTTOM - _temp_descent
        _temp_top = _temp_baseline - _temp_ascent
        _icon_y = (_time_bottom + _temp_top) // 2 - 24  # vertically centred 48px icon

        for i, slot in enumerate(weather.hourly_forecast[:6]):
            cx = x0 + i * cell_w + cell_w // 2
            cell_x = x0 + i * cell_w

            # Vertical separator (skip leftmost edge)
            if i > 0:
                draw.line(
                    [(cell_x, y0), (cell_x, y0 + _h)],
                    fill=palette["RULE"],
                    width=1,
                )

            # Time label — centered, top of cell
            draw.text(
                (cx, y0 + _PAD_TOP),
                f"{slot.hour:02d}:00",
                font=self._font_mono_xs,
                fill=palette["INK_MUTED"],
                anchor="mt",
            )

            # Condition icon (48px) — centred between time text and temperature text
            if slot.condition_icon is not None:
                icon_img = load_icon(slot.condition_icon, 48)
                if icon_img is not None:
                    icon_color = WEATHER_ICON_COLORS.get(slot.condition_icon, palette["INK"])
                    ir, ig, ib = self._hex_to_rgb(icon_color)
                    _, _, _, alpha = icon_img.split()
                    tinted = Image.new("RGBA", icon_img.size, (ir, ig, ib, 255))
                    tinted.putalpha(alpha)
                    img.paste(tinted, (cx - 24, _icon_y), mask=tinted)

            # Temperature — number part centred on cx, degree symbol to the right
            if slot.temp is not None:
                num_str = f"{slot.temp:.0f}"
                num_w = int(draw.textlength(num_str, font=self._font_hourly_temp))
                draw.text(
                    (cx - num_w // 2, _temp_baseline),
                    f"{num_str}°",
                    font=self._font_hourly_temp,
                    fill=palette["INK"],
                    anchor="lb",
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

    @staticmethod
    def _ellipsize(
        text: str, font: "ImageFont.FreeTypeFont", max_width: int
    ) -> str:
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
        dow_header_h = 24
        separator_h = 40  # height reserved for each between-row month separator

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
        day_area_h = 24    # height reserved for the day number at the top of each cell
        event_line_h = 20  # TEXT_XS (18px) + 2px gap
        cell_pad_x = 3     # horizontal margin inside cell for event text
        dot_r = 3          # radius of the calendar-colour dot

        # Dynamic overflow limit: how many event lines fit in the available cell area
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
                    event_ink = palette["INK"] if cell["date"] >= today else palette["INK_MUTED"]

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
                    # Coloured dot — consistent with agenda view
                    try:
                        dot_fill: tuple = ImageColor.getrgb(evt.color) if evt.color else ImageColor.getrgb(palette["INK_FAINT"])
                    except (ValueError, AttributeError):
                        dot_fill = ImageColor.getrgb(palette["INK_FAINT"])
                    dot_cx = int(cx0 + cell_pad_x) + dot_r
                    draw.ellipse(
                        [(dot_cx - dot_r, line_y - dot_r), (dot_cx + dot_r, line_y + dot_r)],
                        fill=dot_fill,
                    )
                    text = self._ellipsize(
                        evt.title, self._font_event, max_text_w
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
                    overflow_fill = palette["INK"] if cell["date"] >= today else palette["INK_FAINT"]
                    draw.text(
                        (cx0 + text_x_offset, overflow_y),
                        f"+{overflow_count}",
                        font=self._font_event,
                        fill=overflow_fill,
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
        date_col_w = 84
        event_row_h = 60
        event_row_loc_h = 88
        event_row_loc_desc_h = 94
        # time_col_w budget: left_pad(8) + dot(14) + gap(6) + text("Tutto il giorno"=165px) + right_gap(≥7) = 200
        time_col_w = 200

        # Group events across the full 30-day window (matches events_range_for_state)
        _WINDOW_DAYS = 30
        window_start = state.anchor_date
        window_end = state.anchor_date + timedelta(days=_WINDOW_DAYS - 1)

        days_events: dict[date, list] = {}
        for d_offset in range(_WINDOW_DAYS):
            days_events[window_start + timedelta(days=d_offset)] = []

        for evt in events:
            if evt.all_day:
                evt_date = evt.start.date()
            else:
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
        # Each entry: (day, evt, max_desc_lines)  — 10 = full, 0 = no description
        rendered: list[tuple[date, object, int]] = []
        remaining_count = 0
        in_overflow = False

        _desc_max_w = w - (padding_x + date_col_w + time_col_w + 8 + 8)

        def _row_height(evt: object, max_desc_lines: int = 10) -> int:
            has_loc = bool(getattr(evt, "location", None))
            desc_raw: str = getattr(evt, "description", None) or ""
            if desc_raw and max_desc_lines > 0:
                rich_lines = parse_html_description(desc_raw, max_lines=max_desc_lines)
                wrapped = self._wrap_rich_lines(rich_lines, _desc_max_w, max_lines=max_desc_lines)
                if wrapped:
                    # 8 px bottom margin ≈ visual whitespace above title glyph
                    # line_h must match _draw_rich_description: font_desc.size + 4 = TEXT_XS + 4
                    return 60 + (20 if has_loc else 0) + len(wrapped) * (TEXT_XS + 4) + 8
            return 60 + (28 if has_loc else 0)

        for day, evt in items:
            if in_overflow:
                remaining_count += 1
                continue

            full_h = _row_height(evt, 10)
            # Reserve one event_row_h for the overflow indicator
            available = max_y - cur_y - event_row_h

            if full_h <= available:
                # Event fits with full description
                rendered.append((day, evt, 10))
                cur_y += full_h
            else:
                # Try to fit with a truncated (or no) description
                base_h = _row_height(evt, 0)  # height with no description
                if base_h > available:
                    # Not even the title fits — true overflow
                    in_overflow = True
                    remaining_count += 1
                    continue

                has_desc = bool(getattr(evt, "description", None))
                if has_desc:
                    # Max desc lines that fit: base_h + N*(TEXT_XS+4) + 8 <= available
                    max_lines_fit = max(0, (available - base_h - 8) // (TEXT_XS + 4))
                    max_lines_fit = min(10, max_lines_fit)
                else:
                    max_lines_fit = 0

                effective_h = _row_height(evt, max_lines_fit)
                rendered.append((day, evt, max_lines_fit))
                cur_y += effective_h
                # Do NOT set in_overflow: subsequent events may still fit

        # Second pass: draw
        cur_y = y0
        prev_day: date | None = None
        is_first_rendered = True
        for day, evt, max_desc_lines in rendered:
            first_in_day = day != prev_day
            row_h_item = _row_height(evt, max_desc_lines)
            self._draw_event_row(
                draw, img, evt, x0, cur_y, w, row_h_item,  # type: ignore[arg-type]
                padding_x, time_col_w, date_col_w, palette,
                day_date=day if first_in_day else None,
                draw_top_separator=not is_first_rendered,
                max_desc_lines=max_desc_lines,
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
        max_desc_lines: int = 10,
    ) -> None:
        first_in_day = day_date is not None

        # Horizontal separator:
        #   - first rendered row: none
        #   - day boundary: full-width (covers date column area)
        #   - same-day continuation: starts after the date column
        if draw_top_separator and first_in_day:
            # Day-boundary separator: full-width, dark — survives e-ink BW quantisation.
            # Same-day event continuations use no line; the 30 px top margin provides
            # sufficient visual separation without relying on near-white RULE colour.
            draw.line([(x0 + padding_x, y0), (x0 + w, y0)], fill=palette["RULE_STRONG"], width=1)

        # --- Date column ---
        if day_date is not None:
            # Single line aligned with the event title (y0+30): "31 DOM" style.
            # A fixed slot for the abbreviation (self._date_abbrev_slot_w) keeps
            # the day number at a consistent x across all rendered rows.
            date_col_right = x0 + padding_x + date_col_w - 4
            day_abbrev = _DAY_NAMES_IT[day_date.weekday()]
            draw.text(
                (date_col_right, y0 + 30),
                day_abbrev,
                font=self._font_label,
                fill=palette["INK_MUTED"],
                anchor="rm",
            )
            draw.text(
                (date_col_right - self._date_abbrev_slot_w - 5, y0 + 30),
                str(day_date.day),
                font=self._font_date_num,
                fill=palette["INK"],
                anchor="rm",
            )

        # --- Time column ---
        time_area_x = x0 + padding_x + date_col_w
        sep_x = time_area_x + time_col_w

        # Vertical position: title is centred in the first 60 px block (fixed)
        time_y = y0 + 30

        # Coloured dot — calendar-colour indicator at the left of the time area
        raw_color = getattr(evt, "color", "") or ""
        if raw_color.startswith("#") and len(raw_color) == 7:
            try:
                dot_rgb: tuple[int, int, int] = self._hex_to_rgb(raw_color)
            except ValueError:
                dot_rgb = self._hex_to_rgb(palette["RULE"])
        else:
            dot_rgb = self._hex_to_rgb(palette["RULE"])
        dot_r = 7
        time_col_pad = 8  # padding between date col and dot, mirrored on right (sep_x + 8)
        dot_cx = time_area_x + time_col_pad + dot_r
        draw.ellipse(
            [(dot_cx - dot_r, time_y - dot_r), (dot_cx + dot_r, time_y + dot_r)],
            fill=dot_rgb,
        )

        # Time text — single line to the right of the dot
        time_text_x = time_area_x + time_col_pad + dot_r * 2 + 6
        if evt.all_day:
            draw.text(
                (time_text_x, time_y),
                "Tutto il giorno",
                font=self._font_mono_xs,
                fill=palette["INK"],
                anchor="lm",
            )
        else:
            local_start = evt.start.astimezone(self._tz) if self._tz else evt.start
            local_end = evt.end.astimezone(self._tz) if self._tz else evt.end
            draw.text(
                (time_text_x, time_y),
                f"{local_start.strftime('%H:%M')} - {local_end.strftime('%H:%M')}",
                font=self._font_mono_xs,
                fill=palette["INK"],
                anchor="lm",
            )

        # --- Content ---
        title_x = sep_x + 8
        title_max_w = w - (title_x - x0) - 8
        icon_size_title = int(self._font_body.size * 0.75)
        title_segs = split_text_emoji(evt.title)
        title_segs = self._fit_mixed(draw, title_segs, self._font_body, icon_size_title, title_max_w)
        self._draw_mixed(draw, img, title_segs, title_x, time_y, self._font_body, palette["INK"], icon_size_title)

        icon_size_sub = int(self._font_label.size * 0.75)
        # Location line: centred in a 14 px block immediately after the 60 px title block
        loc_y: int | None = (y0 + 70) if evt.location else None
        # Description block starts after location (or after title if no location)
        desc_block_y: int | None = None
        if evt.description and max_desc_lines > 0:
            desc_block_y = y0 + 60 + (20 if evt.location else 0)

        if evt.location and loc_y is not None:
            loc_segs = split_text_emoji(evt.location)
            loc_segs = self._fit_mixed(draw, loc_segs, self._font_label, icon_size_sub, title_max_w)
            self._draw_mixed(draw, img, loc_segs, title_x, loc_y, self._font_label, palette["INK_MUTED"], icon_size_sub)

        if evt.description and desc_block_y is not None:
            rich_lines = parse_html_description(evt.description, max_lines=max_desc_lines)
            if rich_lines:
                self._draw_rich_description(
                    draw, rich_lines, title_x, desc_block_y, title_max_w, palette,
                    max_lines=max_desc_lines,
                    img=img,
                )


    # ------------------------------------------------------------------
    # Footer
    # ------------------------------------------------------------------

    def _draw_footer(
        self,
        draw: ImageDraw.ImageDraw,
        rect: Rect,
        palette: dict[str, str],
        updated_at: datetime | None = None,
    ) -> None:
        x0, y0, w, h = rect

        # Top separator
        draw.line([(x0, y0), (x0 + w, y0)], fill=palette["RULE"])

        # Status indicator (right-aligned, sollevato di un'altezza testo + 4px dal bordo).
        # *updated_at* riflette l'ultima variazione dei dati, non il mero repaint;
        # se assente (anteprima web / HDMI) si usa l'ora corrente.
        ts = updated_at or datetime.now()
        status_text = f"Ultimo aggiornamento: {ts.strftime('%H:%M')}"
        _bbox = draw.textbbox((0, 0), status_text, font=self._font_label)
        _text_h = _bbox[3] - _bbox[1]
        draw.text(
            (x0 + w - 12, y0 + h - 4 - _text_h),
            status_text,
            font=self._font_label,
            fill=palette["INK_MUTED"],
            anchor="rb",
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

    # ------------------------------------------------------------------
    # Mixed text + inline-icon rendering helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
        """Convert a ``#rrggbb`` colour string to an (r, g, b) tuple."""
        h = hex_color.lstrip("#")
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

    def _draw_rich_description(
        self,
        draw: ImageDraw.ImageDraw,
        lines: list[RichLine],
        x0: int,
        y0: int,
        max_w: int,
        palette: dict[str, str],
        max_lines: int = 10,
        img: "Image.Image | None" = None,
    ) -> None:
        """Render *lines* as rich text starting at (*x0*, *y0* top-left).

        Each line occupies ``self._font_desc.size + 4`` px vertically.
        Spans use Bold / Italic / Regular fonts as indicated; underlines and
        links are decorated with a 1 px horizontal rule below the text.
        Long lines are wrapped at word boundaries by ``_wrap_rich_lines``.
        Emoji sequences are rendered as inline icon images when *img* is provided.
        """
        visual_lines = self._wrap_rich_lines(lines, max_w, max_lines=max_lines)
        line_h = self._font_desc.size + 4

        for line_idx, line in enumerate(visual_lines):
            cy = y0 + line_idx * line_h + line_h // 2
            cx = float(x0)
            for span in line:
                if not span.text:
                    continue
                font = self._span_font(span)
                color = palette["INK_MUTED"] if span.is_link else palette["INK_FAINT"]
                r, g, b = self._hex_to_rgb(color)
                for seg_type, content in split_text_emoji(span.text):
                    if seg_type == "text":
                        if not content:
                            continue
                        seg_w = font.getlength(content)
                        draw.text((int(cx), cy), content, font=font, fill=color, anchor="lm")
                        if span.underline or span.is_link:
                            uy = cy + font.size // 2 + 1
                            draw.line(
                                [(int(cx), uy), (int(cx + seg_w), uy)], fill=color, width=1
                            )
                        cx += seg_w
                    else:  # "icon"
                        if img is not None:
                            icon_img = load_icon(content, self._icon_size_desc)
                            if icon_img is not None:
                                colored = Image.new("RGBA", icon_img.size, (r, g, b, 255))
                                _, _, _, alpha = icon_img.split()
                                colored.putalpha(alpha)
                                icon_top = cy - self._icon_size_desc // 2
                                img.paste(colored, (int(cx), icon_top), mask=colored)
                        cx += self._icon_size_desc + 1

    def _span_font(self, span: RichSpan) -> ImageFont.FreeTypeFont:
        """Return the correct description font for *span*'s inline style."""
        if span.bold:
            return self._font_desc_bold
        if span.italic:
            return self._font_desc_italic
        return self._font_desc

    def _measure_span_text(self, text: str, font: ImageFont.FreeTypeFont) -> float:
        """Measure pixel width of *text*, treating emoji as inline icons."""
        total = 0.0
        for seg_type, content in split_text_emoji(text):
            if seg_type == "text":
                total += font.getlength(content)
            else:  # icon
                total += self._icon_size_desc + 1
        return total

    def _wrap_rich_lines(
        self,
        lines: list[RichLine],
        max_w: int,
        max_lines: int = 10,
    ) -> list[RichLine]:
        """Wrap logical RichLines into visual lines that fit within *max_w* px.

        Words are split at space boundaries.  A single word wider than max_w
        is placed alone on its line and truncated with '\u2026'.  Total output is
        capped at *max_lines*.
        """
        from app.renderer.rich_text import RichSpan as _RS

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

            current: list[_RS] = []
            current_w = 0.0

            def _flush() -> None:
                nonlocal current, current_w
                # Strip trailing space from the last span
                if current:
                    last = current[-1]
                    stripped = last.text.rstrip(" ")
                    if stripped != last.text:
                        current[-1] = _RS(text=stripped, bold=last.bold, italic=last.italic,
                                          underline=last.underline, is_link=last.is_link)
                if any(s.text for s in current):
                    wrapped.append(current)
                current = []
                current_w = 0.0

            for text, bold, italic, underline, is_link in tokens:
                if len(wrapped) >= max_lines:
                    break
                font = self._font_desc_bold if bold else (
                    self._font_desc_italic if italic else self._font_desc
                )
                tw = self._measure_span_text(text, font)

                # Skip leading space at the start of a new visual line
                if text == " " and current_w == 0.0:
                    continue

                if current_w + tw <= max_w or current_w == 0.0:
                    new_span = _RS(text=text, bold=bold, italic=italic,
                                   underline=underline, is_link=is_link)
                    # Merge with previous span if same style
                    if (current
                            and current[-1].bold == bold
                            and current[-1].italic == italic
                            and current[-1].underline == underline
                            and current[-1].is_link == is_link):
                        current[-1] = _RS(
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
                            text = self._ellipsize(text, font, max_w)
                            tw = font.getlength(text)
                        current = [_RS(text=text, bold=bold, italic=italic,
                                       underline=underline, is_link=is_link)]
                        current_w = tw

            if len(wrapped) < max_lines:
                _flush()

        return wrapped

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
