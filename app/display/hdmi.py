"""HDMI display driver for Family Planner.

``HdmiDisplay`` runs a pygame SDL window on the main thread, rendering the
calendar via ``PillowEinkRenderer``.  Uvicorn is expected to be running in
a background daemon thread before ``run_blocking()`` is called.

On Raspberry Pi with Wayland the environment variables ``WAYLAND_DISPLAY``
and ``XDG_RUNTIME_DIR`` must be set before this process starts (configured
in the systemd unit).  With X11 set ``DISPLAY=:0``.
"""
from __future__ import annotations

import logging
import threading
from datetime import date, datetime
from typing import TYPE_CHECKING

import pygame

from app.calendar.data_builders import events_range_for_state
from app.config import DisplayConfig
from app.renderer.state import NavigationState
from app.renderer.tokens import WeatherData
from app.scheduling import floor_to_quarter, is_weather_tick

if TYPE_CHECKING:
    from app.calendar.aggregator import CalendarAggregator
    from app.calendar.base import CalendarEvent
    from app.renderer.pillow_eink_renderer import PillowEinkRenderer
    from app.weather.provider import WeatherProvider

logger = logging.getLogger(__name__)


class HdmiDisplay:
    """Drives an HDMI display via a pygame SDL window (main-thread blocking)."""

    def __init__(
        self,
        config: DisplayConfig,
        renderer: PillowEinkRenderer,
        aggregator: CalendarAggregator,
        weather_provider: "WeatherProvider | None" = None,
    ) -> None:
        self._config = config
        self._renderer = renderer
        self._aggregator = aggregator
        self._weather_provider = weather_provider
        self._stop_event = threading.Event()
        self.shutdown_requested: bool = False

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def stop(self) -> None:
        """Signal the pygame loop to exit on the next frame."""
        self._stop_event.set()

    def set_aggregator(self, aggregator: CalendarAggregator) -> None:
        """Replace the calendar aggregator (called on config reload)."""
        self._aggregator = aggregator

    def set_weather_provider(self, provider: "WeatherProvider | None") -> None:
        """Replace the weather provider (called on config reload)."""
        self._weather_provider = provider

    def set_renderer(self, renderer: "PillowEinkRenderer") -> None:
        """Replace the renderer (called on config reload)."""
        self._renderer = renderer

    @staticmethod
    def probe() -> bool:
        """Return True if pygame can open a display window in the current env.

        Tries to initialise SDL and set a 1×1 mode; catches ``pygame.error``
        (e.g. "kmsdrm not available", "wayland not available") and returns
        False so the caller can fall back gracefully instead of crashing.
        """
        try:
            pygame.init()
            pygame.display.set_mode((1, 1))
            pygame.quit()
            return True
        except pygame.error as exc:
            logger.warning("HdmiDisplay.probe: display not available: %s", exc)
            pygame.quit()
            return False

    def run_blocking(self) -> None:
        """Open the pygame window and block until the user closes it.

        Must be called from the main thread (macOS SDL requirement).
        """
        pygame.init()
        flags = pygame.FULLSCREEN | pygame.NOFRAME if self._config.fullscreen else 0
        screen = pygame.display.set_mode(
            (self._config.width, self._config.height), flags
        )
        pygame.display.set_caption("Family Planner")

        clock = pygame.time.Clock()
        last_slot: datetime | None = None
        last_fetched_anchor: date | None = None
        events: list[CalendarEvent] = []
        last_rendered_state: NavigationState | None = None
        last_rendered_events: list[CalendarEvent] = []
        last_rendered_weather: WeatherData = WeatherData()

        logger.info(
            "HdmiDisplay: pygame window %dx%d (fullscreen=%s)",
            self._config.width,
            self._config.height,
            self._config.fullscreen,
        )

        running = True
        while running and not self._stop_event.is_set():
            # Single state read per iteration — always reflects today.
            state = NavigationState()
            current_slot = floor_to_quarter(datetime.now())

            # Quarter-hour tick (or date rollover at midnight): re-fetch the
            # calendar fresh; refresh the weather only on the hour (xx:00).
            if current_slot != last_slot or state.anchor_date != last_fetched_anchor:
                start, end = events_range_for_state(state)
                try:
                    events = self._aggregator.get_events(start, end, force=True)
                    last_fetched_anchor = state.anchor_date
                except Exception as exc:
                    logger.error("HdmiDisplay: event fetch error: %s", exc)
                if self._weather_provider is not None and is_weather_tick(current_slot):
                    self._weather_provider.get(force=True)  # refresh cache
                last_slot = current_slot

            # Read current weather (from cache) for change detection each frame.
            weather = (
                self._weather_provider.get()
                if self._weather_provider is not None
                else WeatherData()
            )

            # Render only when content has changed since the last frame.
            data_changed = (
                state != last_rendered_state
                or events != last_rendered_events
                or weather != last_rendered_weather
            )
            if data_changed:
                try:
                    pil_img = self._renderer.render(state, events)
                    surface = pygame.image.frombytes(pil_img.tobytes(), pil_img.size, "RGB")
                    screen.blit(surface, (0, 0))
                    pygame.display.flip()
                    last_rendered_state = state
                    last_rendered_events = events
                    last_rendered_weather = weather
                except Exception as exc:
                    logger.error("HdmiDisplay: render error: %s", exc)

            # Handle input events.
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key in (pygame.K_q, pygame.K_F4):
                        running = False
                    elif event.key == pygame.K_d:
                        self.shutdown_requested = True
                        try:
                            artwork_img = self._renderer.render_artwork()
                            artwork_surface = pygame.image.frombytes(
                                artwork_img.tobytes(), artwork_img.size, "RGB"
                            )
                            screen.blit(artwork_surface, (0, 0))
                            pygame.display.flip()
                        except Exception:
                            logger.exception(
                                "HdmiDisplay: errore durante il rendering artwork (tasto D)."
                            )
                        running = False

            clock.tick(10)  # ~100 ms per frame

        pygame.quit()
        logger.info("HdmiDisplay: pygame window closed.")
