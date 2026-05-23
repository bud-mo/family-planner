"""HDMI display driver for Family Planner.

``HdmiDisplay`` owns the pygame window and event loop.  It runs in a
background daemon thread so that the FastAPI/Uvicorn server can share the
same process.

The pygame event loop polls at 30 fps for keyboard responsiveness.
A full re-render is triggered only when:
  - a navigation key is pressed (immediate), or
  - ``config.refresh_interval`` seconds have elapsed since the last render.

This deliberately decouples interactive latency from the (slow) Pillow
rendering pipeline.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import date, timedelta

from app.calendar.aggregator import CalendarAggregator
from app.config import DisplayConfig
from app.renderer.image_renderer import ImageRenderer
from app.renderer.state import NavigationState

logger = logging.getLogger(__name__)

_POLL_FPS = 30  # pygame event-loop frame rate (keyboard responsiveness)


class HdmiDisplay:
    """Drives a pygame window and translates key events into navigation."""

    def __init__(
        self,
        config: DisplayConfig,
        renderer: ImageRenderer,
        aggregator: CalendarAggregator,
    ) -> None:
        self._config = config
        self._renderer = renderer
        self._aggregator = aggregator
        self._running = False
        self._thread: threading.Thread | None = None
        # Window dimensions (set in _loop before the event loop starts).
        # Used by _handle_click to scale mouse coords to image space.
        self._win_w: int = config.width
        self._win_h: int = config.height
        self._need_scale: bool = False

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the pygame loop in a background daemon thread."""
        if self._thread and self._thread.is_alive():
            logger.warning("HdmiDisplay.start() called while already running — ignored")
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="hdmi-display", daemon=True)
        self._thread.start()
        logger.info("HdmiDisplay started (%dx%d, fullscreen=%s)",
                    self._config.width, self._config.height, self._config.fullscreen)

    def run(self) -> None:
        """Run the pygame loop on the calling thread (blocking).

        On macOS, AppKit requires SDL/pygame to be initialised on the main
        thread (``NSApplication setMainMenu`` must run on the main thread).
        Call this instead of :meth:`start` when the caller owns the main
        thread — typically with uvicorn running in a background thread.
        """
        self._running = True
        logger.info(
            "HdmiDisplay started (%dx%d, fullscreen=%s)",
            self._config.width,
            self._config.height,
            self._config.fullscreen,
        )
        self._loop()

    def stop(self) -> None:
        """Signal the pygame loop to exit and wait for the thread to finish."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        logger.info("HdmiDisplay stopped")

    # ------------------------------------------------------------------
    # Private — pygame loop
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_dpi(pygame) -> float:  # type: ignore[override]
        """Return the screen's logical DPI for window-size calculations.

        On macOS uses CoreGraphics (``CGDisplayScreenSize`` + ``CGDisplayBounds``)
        to compute logical DPI from physical mm and logical-pixel bounds — this
        correctly handles Retina displays without any external dependency.

        Falls back to ``pygame.display.get_dpi()`` on other platforms, with a
        final fallback of 96 DPI if all else fails.
        """
        import sys

        _FALLBACK_DPI = 96.0

        if sys.platform == "darwin":
            try:
                dpi = HdmiDisplay._detect_dpi_macos()
                logger.info("Screen DPI (CoreGraphics): %.1f", dpi)
                return dpi
            except Exception as exc:
                logger.debug("macOS CoreGraphics DPI detection failed: %s", exc)

        try:
            dpi_h, dpi_v = pygame.display.get_dpi()
            dpi = (dpi_h + dpi_v) / 2.0
            if not (60.0 <= dpi <= 400.0):
                raise ValueError(f"DPI out of range: {dpi}")
            logger.info("Screen DPI (pygame): %.1f", dpi)
            return dpi
        except Exception as exc:
            logger.warning("DPI detection failed (%s) — using fallback %g DPI", exc, _FALLBACK_DPI)
            return _FALLBACK_DPI

    @staticmethod
    def _detect_dpi_macos() -> float:
        """Logical DPI via CoreGraphics ctypes — no PyObjC or extra deps needed.

        ``CGDisplayBounds`` returns the display rect in *logical* pixels
        (NSScreen points, already accounting for Retina 2× scaling).
        ``CGDisplayScreenSize`` returns the physical size in mm from EDID.
        Dividing gives the true logical DPI that pygame windows are sized in.
        """
        import ctypes

        class _CGSize(ctypes.Structure):
            _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]

        class _CGPoint(ctypes.Structure):
            _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]

        class _CGRect(ctypes.Structure):
            _fields_ = [("origin", _CGPoint), ("size", _CGSize)]

        cg = ctypes.CDLL(
            "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
        )
        cg.CGMainDisplayID.restype = ctypes.c_uint32
        cg.CGDisplayScreenSize.restype = _CGSize
        cg.CGDisplayScreenSize.argtypes = [ctypes.c_uint32]
        cg.CGDisplayBounds.restype = _CGRect
        cg.CGDisplayBounds.argtypes = [ctypes.c_uint32]

        display_id = cg.CGMainDisplayID()
        physical = cg.CGDisplayScreenSize(display_id)   # mm (from EDID)
        logical  = cg.CGDisplayBounds(display_id)       # logical pixels (points)

        if physical.width <= 0:
            raise ValueError(f"Invalid physical width from CoreGraphics: {physical.width}")

        return logical.size.width / (physical.width / 25.4)

    def _loop(self) -> None:
        """Main pygame loop — runs on whatever thread invokes it."""
        import pygame  # imported here to avoid side-effects at module level

        try:
            pygame.init()

            # --- window size (local dev: scale to physical panel dimensions) ---
            win_w = self._config.width
            win_h = self._config.height
            need_scale = False

            if (
                not self._config.fullscreen
                and self._config.width_mm is not None
                and self._config.height_mm is not None
            ):
                dpi = self._detect_dpi(pygame)
                win_w = round(self._config.width_mm / 25.4 * dpi)
                win_h = round(self._config.height_mm / 25.4 * dpi)
                need_scale = (win_w != self._config.width or win_h != self._config.height)
                logger.info(
                    "Local window: %dx%d px (panel %dx%d px @ %.1fx%.1f mm, screen DPI=%.1f)",
                    win_w, win_h,
                    self._config.width, self._config.height,
                    self._config.width_mm, self._config.height_mm,
                    dpi,
                )

            # Expose to _handle_click (same thread — no lock needed)
            self._win_w = win_w
            self._win_h = win_h
            self._need_scale = need_scale

            flags = pygame.FULLSCREEN if self._config.fullscreen else pygame.SCALED
            screen = pygame.display.set_mode((win_w, win_h), flags)
            pygame.display.set_caption("Family Planner")
            clock = pygame.time.Clock()

            last_render_time: float = 0.0  # force render on first iteration
            render_needed = True

            while self._running:
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        self._running = False
                    elif event.type == pygame.KEYDOWN:
                        render_needed = self._handle_key(event.key)
                    elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                        render_needed = self._handle_click(event.pos)

                now = time.monotonic()
                if render_needed or (now - last_render_time) >= self._config.refresh_interval:
                    try:
                        image = self._renderer.render()
                        if need_scale:
                            # PIL LANCZOS preserves sharpness far better than
                            # pygame smoothscale (bilinear) when downscaling text.
                            from PIL import Image as _PILImage
                            image = image.resize((win_w, win_h), _PILImage.LANCZOS)
                        surface = pygame.image.frombuffer(
                            image.tobytes(), image.size, image.mode
                        )
                        screen.blit(surface, (0, 0))
                        pygame.display.flip()
                        last_render_time = now
                        render_needed = False
                    except Exception:
                        logger.exception("HdmiDisplay: render error")

                clock.tick(_POLL_FPS)

        except Exception:
            logger.exception("HdmiDisplay: unhandled error in pygame loop")
        finally:
            pygame.quit()
            logger.info("HdmiDisplay: pygame quit")

    def _handle_key(self, key: int) -> bool:
        """Translate a pygame key code into a NavigationState transition.

        Returns ``True`` when the display should be re-rendered immediately.
        """
        import pygame

        # Retrieve events relevant to the current view for context-aware
        # navigation (navigate_up/down/enter need the event list).
        events = self._get_current_events()

        with self._renderer._lock:  # noqa: SLF001
            current_state: NavigationState = self._renderer._state  # noqa: SLF001

        if key == pygame.K_ESCAPE:
            new_state = current_state.navigate_escape()
        elif key == pygame.K_UP:
            new_state = current_state.navigate_up(events)
        elif key == pygame.K_DOWN:
            new_state = current_state.navigate_down(events)
        elif key == pygame.K_RETURN:
            new_state = current_state.navigate_enter(events)
        elif key == pygame.K_n:
            new_state = current_state.toggle_night_mode()
        else:
            return False  # unrecognised key — no re-render needed

        if new_state is not current_state:
            self._renderer.update_state(new_state)

        return True

    def _handle_click(self, pos: tuple[int, int]) -> bool:
        """Map a left-click in window-space to a footer button action.

        Scales the click coordinates to image-space if the window is
        zoomed (local-dev DPI scaling), then checks the hit-rects recorded
        by the last ``_draw_footer()`` call and dispatches the matching
        navigation action.  Returns ``True`` when a re-render is needed.
        """
        mx, my = pos
        # Scale from window-space to image-space
        if self._need_scale and self._win_w and self._win_h:
            mx = round(mx * self._config.width / self._win_w)
            my = round(my * self._config.height / self._win_h)

        rects = self._renderer.get_footer_rects()
        action: str | None = None
        for name, (x1, y1, x2, y2) in rects.items():
            if x1 <= mx <= x2 and y1 <= my <= y2:
                action = name
                break

        if action is None:
            return False  # click outside any button

        events = self._get_current_events()
        with self._renderer._lock:  # noqa: SLF001
            current_state: NavigationState = self._renderer._state  # noqa: SLF001

        if action == "escape":
            new_state = current_state.navigate_escape()
        elif action == "up":
            new_state = current_state.navigate_up(events)
        elif action == "down":
            new_state = current_state.navigate_down(events)
        elif action == "enter":
            new_state = current_state.navigate_enter(events)
        else:
            return False

        if new_state is not current_state:
            self._renderer.update_state(new_state)

        return True

    def _get_current_events(self) -> list:
        """Fetch events for the visible week around the selected date.

        Used to provide context to navigate_up/down/enter.
        Failures are logged and an empty list is returned so navigation
        degrades gracefully.
        """
        try:
            from datetime import datetime

            with self._renderer._lock:  # noqa: SLF001
                state = self._renderer._state  # noqa: SLF001

            selected = state.selected_date
            # Fetch the full week that contains the selected date
            week_start = selected - timedelta(days=selected.weekday())
            week_end = week_start + timedelta(days=7)
            start_dt = datetime.combine(week_start, datetime.min.time())
            end_dt = datetime.combine(week_end, datetime.max.time())
            return self._aggregator.get_events(start_dt, end_dt)
        except Exception:
            logger.exception("HdmiDisplay: failed to fetch events for navigation")
            return []
