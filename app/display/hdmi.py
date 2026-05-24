"""HDMI display driver for Family Planner.

``HdmiDisplay`` launches Chromium via the Playwright Python API in
non-headless mode, pointing at the FastAPI web server.  HTMX handles
navigation updates inside the page without full reloads.

The driver is non-blocking: ``start()`` launches a daemon thread that
waits for the server, opens the browser window, and then blocks until
``stop()`` is called.  The Uvicorn server therefore runs on the calling
thread as usual.

On Raspberry Pi with Wayland the environment variables ``WAYLAND_DISPLAY``
and ``XDG_RUNTIME_DIR`` must be set before this process starts (configured
in the systemd unit).  With X11 set ``DISPLAY=:0``.
"""
from __future__ import annotations

import logging
import threading
import time
import urllib.error
import urllib.request

from app.config import DisplayConfig

logger = logging.getLogger(__name__)

_READY_POLL_INTERVAL: float = 0.5   # seconds between readiness checks
_READY_TIMEOUT: float = 30.0        # give up after this many seconds


class HdmiDisplay:
    """Drives an HDMI display by launching Chromium via Playwright (non-headless)."""

    def __init__(self, config: DisplayConfig, port: int) -> None:
        self._config = config
        self._port = port
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Launch the browser window in a daemon thread (non-blocking)."""
        if self._thread and self._thread.is_alive():
            logger.warning("HdmiDisplay.start() called while already running — ignored")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="hdmi-display",
            daemon=True,
        )
        self._thread.start()

    def run(self) -> None:
        """Alias for ``start()`` — present for interface symmetry with EinkDisplay."""
        self.start()

    def stop(self) -> None:
        """Signal the browser thread to close and wait for it to exit."""
        if not self._stop_event.is_set():
            self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=8)
            self._thread = None
            logger.info("HdmiDisplay stopped.")

    # ------------------------------------------------------------------
    # Private — runs in daemon thread
    # ------------------------------------------------------------------

    def _run(self) -> None:
        """Wait for the server, open the browser, block until stop() is called."""
        from playwright.sync_api import sync_playwright

        url = f"http://localhost:{self._port}/"
        self._wait_for_server(url)

        executable = self._config.playwright_executable or None
        logger.info(
            "HdmiDisplay: launching Chromium (headless=False, executable=%s)",
            executable or "playwright-bundle",
        )

        playwright = None
        browser = None
        try:
            playwright = sync_playwright().start()

            launch_args: list[str] = ["--no-first-run", "--disable-infobars", "--noerrdialogs"]
            if self._config.fullscreen:
                launch_args.append("--kiosk")
            else:
                launch_args += [
                    f"--app={url}",
                    f"--window-size={self._config.width},{self._config.height}",
                ]

            browser = playwright.chromium.launch(
                headless=False,
                executable_path=executable,
                args=launch_args,
            )
            context = browser.new_context(
                viewport=(
                    None if self._config.fullscreen
                    else {"width": self._config.width, "height": self._config.height}
                ),
                no_viewport=self._config.fullscreen,
            )
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded")
            logger.info("HdmiDisplay: browser window open at %s", url)

            # Block here until stop() is signalled.
            self._stop_event.wait()

        except Exception as exc:  # noqa: BLE001
            logger.error("HdmiDisplay: error in browser thread: %s", exc)
        finally:
            if browser is not None:
                try:
                    browser.close()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("HdmiDisplay: error closing browser: %s", exc)
            if playwright is not None:
                try:
                    playwright.stop()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("HdmiDisplay: error stopping playwright: %s", exc)
            logger.info("HdmiDisplay: browser thread exited.")

    def _wait_for_server(self, url: str) -> None:
        """Poll *url* until it returns HTTP 200 or the timeout expires."""
        deadline = time.monotonic() + _READY_TIMEOUT
        logger.info("HdmiDisplay: waiting for server at %s …", url)
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=2) as resp:  # noqa: S310
                    if resp.status == 200:
                        logger.info("HdmiDisplay: server is ready")
                        return
            except (urllib.error.URLError, OSError):
                pass
            time.sleep(_READY_POLL_INTERVAL)
        logger.warning(
            "HdmiDisplay: server not ready after %.0f s — opening browser anyway",
            _READY_TIMEOUT,
        )
