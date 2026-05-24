"""Family Planner — application entry point.

Wires together all subsystems:
  - Configuration (Pydantic / YAML)
  - Calendar aggregator (ICS + CalDAV)
  - Renderer (PlaywrightRenderer — headless Chromium for e-ink)
  - Display (HDMI Playwright non-headless *or* e-ink periodic push)
  - Web server (FastAPI / Uvicorn)

Usage::

    python app/main.py --config config/default.yaml
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# sys.path bootstrap
# ---------------------------------------------------------------------------
# When the script is run directly (`python app/main.py`), Python prepends the
# `app/` directory to sys.path.  This causes `app/calendar/` to shadow the
# stdlib `calendar` module, breaking uvicorn's transitive imports.
# We replace the script directory with the project root so that absolute
# package imports (`from app.xxx import ...`) resolve correctly.
import sys as _sys
from pathlib import Path as _Path

_here = _Path(__file__).parent          # app/
_project_root = _here.parent            # project root

if str(_here) in _sys.path:
    _sys.path.remove(str(_here))
if str(_project_root) not in _sys.path:
    _sys.path.insert(0, str(_project_root))

import argparse
import asyncio
import logging
import signal
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import uvicorn

from app.calendar.aggregator import CalendarAggregator
from app.config import load_config
from app.renderer.playwright_renderer import PlaywrightRenderer
from app.server.app import create_app

if TYPE_CHECKING:
    from app.display.eink import EinkDisplay
    from app.display.hdmi import HdmiDisplay
    from app.renderer.eink_renderer import EinkRenderer

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Family Planner — calendar display and web server",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/default.yaml"),
        metavar="PATH",
        help="Path to the YAML configuration file (default: config/default.yaml)",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# E-ink periodic loop
# ---------------------------------------------------------------------------


def _eink_loop(
    renderer: PlaywrightRenderer,
    eink_renderer: "EinkRenderer",
    display: "EinkDisplay",
    port: int,
    interval: int,
    stop_event: threading.Event,
) -> None:
    """Connect the headless renderer, then push frames to the e-ink panel.

    Must run in its own daemon thread — Playwright sync API must be used
    from the thread that called ``start()``.
    """
    logger.info("E-ink loop started (interval=%ds).", interval)
    try:
        renderer.start(port)  # waits for server, launches headless Chromium
    except TimeoutError as exc:
        logger.error("E-ink loop: %s — aborting.", exc)
        return

    # Initial render immediately on start
    _eink_push(renderer, eink_renderer, display)

    while not stop_event.wait(timeout=interval):
        _eink_push(renderer, eink_renderer, display)

    renderer.stop()
    logger.info("E-ink loop stopped.")


def _eink_push(
    renderer: PlaywrightRenderer,
    eink_renderer: "EinkRenderer",
    display: "EinkDisplay",
) -> None:
    """Capture one screenshot and push it to the e-ink panel."""
    try:
        image = renderer.screenshot()
        processed = eink_renderer.process(image)
        display.push(processed)
    except Exception as exc:  # noqa: BLE001
        logger.error("E-ink render/push error: %s", exc)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    _setup_logging()
    args = _parse_args()

    config_path: Path = args.config.resolve()
    config = load_config(config_path)

    aggregator = CalendarAggregator(
        config.calendars,
        cache_ttl=config.display.refresh_interval,
    )

    # ------------------------------------------------------------------
    # Renderer (shared between display pipeline and web server)
    # ------------------------------------------------------------------
    renderer = PlaywrightRenderer(config, aggregator)

    # ------------------------------------------------------------------
    # Display initialisation
    # ------------------------------------------------------------------
    display_obj: HdmiDisplay | EinkDisplay | None = None
    eink_stop_event: threading.Event | None = None

    if config.display.type == "hdmi":
        from app.display.hdmi import HdmiDisplay

        display_obj = HdmiDisplay(config.display, port=config.server.port)

    elif config.display.type == "eink":
        from app.display.eink import EinkDisplay
        from app.renderer.eink_renderer import EinkRenderer

        eink_renderer = EinkRenderer(config.display)
        display_obj = EinkDisplay(config.display)

        eink_stop_event = threading.Event()
        eink_thread = threading.Thread(
            target=_eink_loop,
            args=(
                renderer,
                eink_renderer,
                display_obj,
                config.server.port,
                config.display.refresh_interval,
                eink_stop_event,
            ),
            daemon=True,
            name="eink-loop",
        )
        eink_thread.start()
        logger.info(
            "E-ink loop started (model=%s, palette=%s, interval=%ds).",
            config.display.eink_model,
            config.display.eink_palette,
            config.display.refresh_interval,
        )

    # ------------------------------------------------------------------
    # Web server
    # ------------------------------------------------------------------
    web_app = create_app(config, aggregator, config_path, renderer)

    uv_config = uvicorn.Config(
        web_app,
        host=config.server.host,
        port=config.server.port,
        log_config=None,  # use the root logging configuration set above
    )
    server = uvicorn.Server(uv_config)

    # ------------------------------------------------------------------
    # Signal handlers
    # ------------------------------------------------------------------
    # We disable uvicorn's own install_signal_handlers so that our
    # handlers are not overridden.
    server.install_signal_handlers = lambda: None  # type: ignore[method-assign]

    def _shutdown(signum: int, frame: object) -> None:
        logger.info("Signal %d received — initiating graceful shutdown.", signum)
        # Signal the e-ink loop to stop (non-blocking — just sets an event).
        if eink_stop_event is not None:
            eink_stop_event.set()
        # Uvicorn handles SIGINT via its own asyncio signal handlers; setting
        # should_exit here is a belt-and-suspenders fallback for other signals.
        server.should_exit = True

    def _reload_config(signum: int, frame: object) -> None:
        """SIGHUP: re-read config and update web app state.

        Per spec: the display is NOT restarted — only the server's view of
        the configuration is refreshed.  The aggregator picks up the new
        calendars at the next cache expiry.
        """
        logger.info("SIGHUP received — reloading configuration from %s.", config_path)
        try:
            new_config = load_config(config_path)
            web_app.state.config = new_config
            # Rebuild the aggregator providers so new calendar sources take effect.
            new_aggregator = CalendarAggregator(
                new_config.calendars,
                cache_ttl=new_config.display.refresh_interval,
            )
            web_app.state.aggregator = new_aggregator
            logger.info("Configuration reloaded successfully.")
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to reload configuration: %s", exc)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    if hasattr(signal, "SIGHUP"):  # not available on Windows
        signal.signal(signal.SIGHUP, _reload_config)

    # ------------------------------------------------------------------
    # Run (blocks until server exits)
    # ------------------------------------------------------------------
    logger.info(
        "Web server starting on http://%s:%d",
        config.server.host,
        config.server.port,
    )
    if display_obj is not None and config.display.type == "hdmi":
        display_obj.start()  # launch Chromium in background; Uvicorn runs below

    async def _serve() -> None:
        """Run uvicorn with an exception handler that suppresses harmless
        BrokenPipeError futures that arise when the browser connection closes
        while uvicorn is still flushing HTTP write buffers on shutdown."""
        loop = asyncio.get_running_loop()

        def _exc_handler(
            loop: asyncio.AbstractEventLoop, context: dict
        ) -> None:
            exc = context.get("exception")
            if isinstance(exc, BrokenPipeError):
                return  # harmless: client disconnected before write completed
            loop.default_exception_handler(context)

        loop.set_exception_handler(_exc_handler)
        await server.serve()

    asyncio.run(_serve())

    # ------------------------------------------------------------------
    # Post-exit cleanup
    # ------------------------------------------------------------------
    if eink_stop_event is not None:
        eink_stop_event.set()
    if display_obj is not None:
        display_obj.stop()
    logger.info("Family Planner stopped.")


if __name__ == "__main__":
    main()
