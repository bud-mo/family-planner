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
import time
from datetime import date
from typing import TYPE_CHECKING

import pygame

from app.calendar.data_builders import events_range_for_state
from app.config import DisplayConfig
from app.renderer.state import NavigationState

if TYPE_CHECKING:
    from app.calendar.aggregator import CalendarAggregator
    from app.calendar.base import CalendarEvent
    from app.renderer.pillow_eink_renderer import PillowEinkRenderer

logger = logging.getLogger(__name__)


class HdmiDisplay:
    """Drives an HDMI display via a pygame SDL window (main-thread blocking)."""

    def __init__(
        self,
        config: DisplayConfig,
        renderer: PillowEinkRenderer,
        aggregator: CalendarAggregator,
    ) -> None:
        self._config = config
        self._renderer = renderer
        self._aggregator = aggregator
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def stop(self) -> None:
        """Signal the pygame loop to exit on the next frame."""
        self._stop_event.set()

    def set_aggregator(self, aggregator: CalendarAggregator) -> None:
        """Replace the calendar aggregator (called on config reload)."""
        self._aggregator = aggregator

    def set_renderer(self, renderer: "PillowEinkRenderer") -> None:
        """Replace the renderer (called on config reload)."""
        self._renderer = renderer

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
        last_event_fetch: float = 0.0
        last_fetched_anchor: date | None = None
        events: list[CalendarEvent] = []

        logger.info(
            "HdmiDisplay: pygame window %dx%d (fullscreen=%s)",
            self._config.width,
            self._config.height,
            self._config.fullscreen,
        )

        running = True
        while running and not self._stop_event.is_set():
            now = time.monotonic()

            # Single state read per iteration — always reflects today.
            state = NavigationState()

            # Re-fetch if: timer expired OR date rolled over at midnight.
            if (
                now - last_event_fetch >= self._config.refresh_interval
                or state.anchor_date != last_fetched_anchor
            ):
                start, end = events_range_for_state(state)
                try:
                    events = self._aggregator.get_events(start, end)
                    last_fetched_anchor = state.anchor_date
                except Exception as exc:
                    logger.error("HdmiDisplay: event fetch error: %s", exc)
                last_event_fetch = now

            # Render.
            try:
                pil_img = self._renderer.render(state, events)
                surface = pygame.image.frombytes(pil_img.tobytes(), pil_img.size, "RGB")
                screen.blit(surface, (0, 0))
                pygame.display.flip()
            except Exception as exc:
                logger.error("HdmiDisplay: render error: %s", exc)

            # Handle input events.
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key in (pygame.K_q, pygame.K_F4):
                        running = False

            clock.tick(10)  # ~100 ms per frame

        pygame.quit()
        logger.info("HdmiDisplay: pygame window closed.")
