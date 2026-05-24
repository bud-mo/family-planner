"""Playwright-based renderer for Family Planner.

``PlaywrightRenderer`` maintains a persistent headless Chromium instance
pointed at the FastAPI server and produces ``PIL.Image`` screenshots.  It also
owns the ``NavigationState`` that is shared between the display pipeline and
the web-server routes.

Thread safety
-------------
* ``get_state()`` / ``update_state()`` acquire ``_state_lock`` — fast, can be
  called from any thread (e.g. FastAPI route handlers).
* ``screenshot()`` acquires ``_page_lock`` which serialises access to the
  Playwright ``Page`` object.  Playwright's sync API must be used from the
  thread that called ``sync_playwright().start()``.  Call ``start()`` and
  ``screenshot()`` from the *same* thread (e.g. the e-ink daemon loop).

Usage (e-ink loop)::

    renderer = PlaywrightRenderer(config, aggregator)
    renderer.start(port=config.server.port)   # blocks briefly while waiting for server
    while not stop.is_set():
        img = renderer.screenshot()           # PIL.Image
        eink_renderer.process(img) → display.push(...)
        stop.wait(timeout=interval)
    renderer.stop()
"""
from __future__ import annotations

import io
import logging
import threading
import time
import urllib.error
import urllib.request
from typing import TYPE_CHECKING

from PIL import Image

from app.renderer.base import Renderer
from app.renderer.state import NavigationState

if TYPE_CHECKING:
    from app.calendar.aggregator import CalendarAggregator
    from app.config import AppConfig

logger = logging.getLogger(__name__)

_READY_POLL_INTERVAL: float = 0.5  # seconds
_READY_TIMEOUT: float = 30.0       # seconds


class PlaywrightRenderer(Renderer):
    """Headless Chromium renderer that screenshots the FastAPI web page."""

    def __init__(self, config: "AppConfig", aggregator: "CalendarAggregator") -> None:
        self._config = config
        self._aggregator = aggregator
        self._state = NavigationState()
        self._state_lock = threading.Lock()
        self._page_lock = threading.Lock()

        # Set after start() is called — all accesses must be from the same thread.
        self._playwright = None
        self._browser = None
        self._page = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self, port: int) -> None:
        """Wait for the web server then launch a persistent headless Chromium.

        Must be called from the thread that will later call ``screenshot()``.

        Args:
            port: The port on which the FastAPI server is listening.
        """
        from playwright.sync_api import sync_playwright

        url = f"http://localhost:{port}/"
        self._wait_for_server(url)

        executable = self._config.display.playwright_executable or None
        logger.info(
            "PlaywrightRenderer: launching headless Chromium (executable=%s)",
            executable or "playwright-bundle",
        )
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=True,
            executable_path=executable,
        )
        context = self._browser.new_context(
            viewport={
                "width": self._config.display.width,
                "height": self._config.display.height,
            },
            device_scale_factor=1,
        )
        self._page = context.new_page()
        self._page.goto(url, wait_until="networkidle")
        logger.info("PlaywrightRenderer: ready (viewport %dx%d)",
                    self._config.display.width, self._config.display.height)

    def stop(self) -> None:
        """Close the browser and stop the Playwright instance."""
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception as exc:  # noqa: BLE001
                logger.warning("PlaywrightRenderer: error closing browser: %s", exc)
            self._browser = None
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception as exc:  # noqa: BLE001
                logger.warning("PlaywrightRenderer: error stopping playwright: %s", exc)
            self._playwright = None
        self._page = None
        logger.info("PlaywrightRenderer stopped.")

    # ------------------------------------------------------------------
    # Renderer protocol (implements Renderer.render())
    # ------------------------------------------------------------------

    def render(self) -> Image.Image:
        """Alias for ``screenshot()`` — satisfies the ``Renderer`` ABC."""
        return self.screenshot()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def screenshot(self) -> Image.Image:
        """Reload the page and return a full-frame ``PIL.Image`` (RGB).

        Must be called from the same thread that called ``start()``.
        """
        with self._page_lock:
            if self._page is None:
                raise RuntimeError("PlaywrightRenderer.start() has not been called")
            self._page.reload(wait_until="networkidle")
            data: bytes = self._page.screenshot(type="png", full_page=False)
        return Image.open(io.BytesIO(data)).convert("RGB")

    def get_state(self) -> NavigationState:
        """Thread-safe read of the current navigation state."""
        with self._state_lock:
            return self._state

    def update_state(self, new_state: NavigationState) -> None:
        """Thread-safe state update (called from FastAPI routes or display input)."""
        with self._state_lock:
            self._state = new_state

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _wait_for_server(self, url: str) -> None:
        """Poll *url* until it returns HTTP 200 or the timeout elapses."""
        deadline = time.monotonic() + _READY_TIMEOUT
        while time.monotonic() < deadline:
            try:
                urllib.request.urlopen(url, timeout=2)
                return
            except (urllib.error.URLError, OSError):
                time.sleep(_READY_POLL_INTERVAL)
        raise TimeoutError(
            f"PlaywrightRenderer: server at {url} did not become ready "
            f"within {_READY_TIMEOUT}s"
        )
