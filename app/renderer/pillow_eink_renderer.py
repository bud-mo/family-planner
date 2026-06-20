"""Pillow-native renderer for Family Planner — Home view.

Single-screen layout: weather banner · mini-calendar · agenda · footer.

``PillowEinkRenderer`` orchestrates the per-component drawing modules in
:mod:`app.renderer.components`, rendering a ``PIL.Image`` directly from
``NavigationState`` and a list of ``CalendarEvent`` objects, without involving a
browser or network.  It is the sole renderer for both HDMI (pygame) and e-ink
(Waveshare / Inky) displays.

On e-ink, colours are resolved against the panel palette (see
:func:`app.renderer.palette.resolve_palette`) and a *dither mask* is built during
drawing and attached to the returned image's ``info`` dict, so the post-processor
(:class:`app.renderer.eink_renderer.EinkRenderer`) dithers only the elements that
need it (photographic content and secondary greys) while keeping primary text and
fills crisp.

Usage::

    renderer = PillowEinkRenderer(config)
    state = NavigationState()
    start, end = events_range_for_state(state)
    events = aggregator.get_events(start, end)
    img = renderer.render(state, events)      # PIL.Image RGB (+ info["dither_mask"])
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from PIL import Image, ImageFont

from app.renderer.components import agenda as _agenda
from app.renderer.components import artwork as _artwork
from app.renderer.components import calendar as _calendar
from app.renderer.components import footer as _footer
from app.renderer.components import text as _text
from app.renderer.components import weather as _weather
from app.renderer.components.context import RenderContext, build_fonts
from app.renderer.palette import resolve_palette
from app.renderer.state import NavigationState
from app.renderer.tokens import (
    BANNER_HEIGHT,
    CALENDAR_HEIGHT,
    COL_LEFT_RATIO,
    FOOTER_HEIGHT,
    Rect,
    WeatherData,
)

if TYPE_CHECKING:
    from app.calendar.base import CalendarEvent
    from app.config import AppConfig
    from app.renderer.rich_text import RichLine
    from app.weather.provider import WeatherProvider

logger = logging.getLogger(__name__)

# Backwards-compatible alias — the artwork fetch lives in the component module.
_ARTWORK_QUERY_DEFAULT = _artwork.ARTWORK_QUERY_DEFAULT


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
        self._eink_palette: str = getattr(config.display, "eink_palette", "bw")
        self._weather_provider = weather_provider
        _artwork_cfg = getattr(config, "artwork", None)
        self._artwork_query: str = (
            _artwork_cfg.query if _artwork_cfg is not None else _ARTWORK_QUERY_DEFAULT
        )
        # Artwork source: "endpoint" (ARTIC API query) or "folder" (local pictures).
        self._artwork_source: str = (
            getattr(_artwork_cfg, "source", "endpoint") if _artwork_cfg is not None else "endpoint"
        )
        # Folder scanned in "folder" mode; relative paths resolve against the
        # project root (two levels above this file: app/renderer/ -> project/).
        _folder = (
            getattr(_artwork_cfg, "folder", "pictures") if _artwork_cfg is not None else "pictures"
        )
        _folder_path = Path(_folder)
        if not _folder_path.is_absolute():
            _folder_path = Path(__file__).resolve().parents[2] / _folder_path
        self._artwork_folder: Path = _folder_path
        # Cursor into the alphabetically-sorted folder; advances on each render so
        # a button press shows the next image. Cycles via modulo in the loader.
        self._artwork_index: int = 0

        # E-ink artwork enhancement — only meaningful when display_type == "eink".
        # Values can be overridden via config.display.eink_gamma / saturation / brightness.
        _disp = config.display
        self._eink_gamma: float = float(getattr(_disp, "eink_gamma", 0.50))
        self._eink_saturation: float = float(getattr(_disp, "eink_saturation", 1.45))
        self._eink_brightness: float = float(getattr(_disp, "eink_brightness", 1.15))

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

        # Resolved semantic palette for the target display (snapped on e-ink).
        self._palette: dict[str, str] = resolve_palette(
            self._display_type, self._eink_palette
        )

        # Fonts are loaded once and shared across renders.
        self._fonts = build_fonts()
        # Back-compat attributes referenced by the test-suite.
        self._font_desc: ImageFont.FreeTypeFont = self._fonts.desc
        self._icon_size_desc: int = self._fonts.icon_size_desc

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
        HDMI) the current time is used.  The returned image carries a dither mask
        in ``img.info["dither_mask"]``.
        """
        W, H = self._size
        palette = self._palette
        img = Image.new("RGB", (W, H), palette["BG"])
        ctx = self._make_ctx(img, palette)

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

        _weather.draw_weather(ctx, weather_rect, weather)
        _calendar.draw_mini_calendar(ctx, calendar_rect, state, events)
        _agenda.draw_agenda(ctx, agenda_rect, state, events)
        _footer.draw_footer(ctx, footer_rect, updated_at)

        ctx.attach_mask()
        return img

    def reset_artwork_cursor(self) -> None:
        """Reset the folder cursor so the next artwork render shows the first image.

        Called when artwork mode is (re)entered, so each entry starts from the
        alphabetically-first picture in ``config.artwork.folder``.  No effect in
        ``"endpoint"`` mode (each render is already random).
        """
        self._artwork_index = 0

    def render_artwork(self) -> Image.Image:
        """Render an artwork image as an RGB ``PIL.Image``.

        When ``config.artwork.source`` is ``"endpoint"`` (default) a random
        public-domain painting is fetched from the ARTIC API.  When it is
        ``"folder"`` the images in ``config.artwork.folder`` are shown in
        alphabetical order, advancing to the next one on each call (so a button
        press cycles through the folder).

        The picture is shown as-is: no e-ink enhancement and no dithering are
        applied (for both sources), so it keeps its original tones.  Falls back
        The picture is shown as-is: no e-ink enhancement and no dithering are
        applied (for both sources), so it keeps its original tones.  Falls back
        to a plain ``BG`` background if the fetch fails.
        """
        W, H = self._size
        palette = self._palette
        img = Image.new("RGB", (W, H), palette["BG"])
        ctx = self._make_ctx(img, palette)

        # Artwork mode shows pictures as-is: no e-ink enhancement and no
        # dithering, for both folder and endpoint sources.
        if self._artwork_source == "folder":
            # Local pictures: alphabetical order, next image on each call.
            result = _artwork.load_folder_artwork(
                self._artwork_folder, self._artwork_index, W, H,
                eink_enhance=False,
            )
            if result is not None:
                self._artwork_index += 1
        else:
            result = _artwork.fetch_artwork(
                W, H, self._artwork_query,
                eink_enhance=False,
            )
        if result is not None:
            artwork_img, caption = result
            img.paste(artwork_img)
            if caption:
                _artwork.draw_artwork_caption(ctx, caption)

        ctx.attach_mask()
        return img

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _make_ctx(
        self, img: Image.Image, palette: dict[str, str] | None = None
    ) -> RenderContext:
        return RenderContext(
            img,
            palette if palette is not None else self._palette,
            self._fonts,
            layout=self._layout,
            display_type=self._display_type,
            eink_palette=self._eink_palette,
            tz=self._tz,
        )

    # ------------------------------------------------------------------
    # Backwards-compatible shims (exercised by the existing test-suite).
    # The real drawing logic lives in app.renderer.components.*.
    # ------------------------------------------------------------------

    def _draw_weather(self, draw, img, rect, weather, palette) -> None:  # noqa: ANN001
        _weather.draw_weather(self._make_ctx(img, palette), rect, weather)

    def _draw_mini_calendar(self, draw, rect, state, events, palette) -> None:  # noqa: ANN001
        _calendar.draw_mini_calendar(self._make_ctx(draw._image, palette), rect, state, events)

    def _draw_agenda(self, draw, img, rect, state, events, palette) -> None:  # noqa: ANN001
        _agenda.draw_agenda(self._make_ctx(img, palette), rect, state, events)

    def _draw_mixed(self, draw, img, segments, x, y, font, fill, icon_size) -> None:  # noqa: ANN001
        _text.draw_mixed(self._make_ctx(img), segments, x, y, font, fill, icon_size)

    def _draw_rich_description(  # noqa: ANN001
        self, draw, lines, x0, y0, max_w, palette, max_lines=10, img=None
    ) -> None:
        target = img if img is not None else draw._image
        _text.draw_rich_description(
            self._make_ctx(target, palette), lines, x0, y0, max_w, max_lines=max_lines
        )

    def _measure_span_text(self, text: str, font: "ImageFont.FreeTypeFont") -> float:
        return _text.measure_span_text(text, font, self._fonts.icon_size_desc)

    def _wrap_rich_lines(
        self, lines: list["RichLine"], max_w: int, max_lines: int = 10
    ) -> list["RichLine"]:
        return _text.wrap_rich_lines(lines, max_w, self._fonts, max_lines=max_lines)

    @staticmethod
    def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
        return _text.hex_to_rgb(hex_color)

    @staticmethod
    def _measure_mixed(draw, segments, font, icon_size) -> float:  # noqa: ANN001
        return _text.measure_mixed(draw, segments, font, icon_size)

    @staticmethod
    def _fit_mixed(draw, segments, font, icon_size, max_width):  # noqa: ANN001
        return _text.fit_mixed(draw, segments, font, icon_size, max_width)
