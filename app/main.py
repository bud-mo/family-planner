"""Family Planner — application entry point.

Wires together all subsystems:
  - Configuration (Pydantic / YAML)
  - Calendar aggregator (ICS + CalDAV)
  - Renderer (Pillow ImageRenderer)
  - Display (HDMI pygame loop *or* e-ink periodic push)
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
import logging
import signal
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import uvicorn

from app.calendar.aggregator import CalendarAggregator
from app.config import load_config
from app.renderer.image_renderer import ImageRenderer
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
    renderer: ImageRenderer,
    eink_renderer: EinkRenderer,
    display: EinkDisplay,
    interval: int,
    stop_event: threading.Event,
) -> None:
    """Render and push to the e-ink panel every *interval* seconds.

    Runs in a daemon thread.  The loop exits as soon as *stop_event* is set.
    """
    logger.info("E-ink loop started (interval=%ds).", interval)
    # Initial render immediately on start
    _eink_push(renderer, eink_renderer, display)

    while not stop_event.wait(timeout=interval):
        _eink_push(renderer, eink_renderer, display)

    logger.info("E-ink loop stopped.")


def _eink_push(
    renderer: ImageRenderer,
    eink_renderer: EinkRenderer,
    display: EinkDisplay,
) -> None:
    """Render one frame and push it to the e-ink panel."""
    try:
        image = renderer.render()
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
    # Display initialisation
    # ------------------------------------------------------------------
    display_obj: HdmiDisplay | EinkDisplay | None = None
    eink_stop_event: threading.Event | None = None

    if config.display.type == "hdmi":
        from app.display.hdmi import HdmiDisplay

        renderer = ImageRenderer(aggregator, config.display)
        display_obj = HdmiDisplay(config.display, renderer, aggregator)
        # NOTE: do NOT call start() here — pygame must be initialised on the
        # main thread on macOS (AppKit/Cocoa requires it).  display_obj.run()
        # is called below after uvicorn is launched on a background thread.

    elif config.display.type == "eink":
        from app.display.eink import EinkDisplay
        from app.renderer.eink_renderer import EinkRenderer

        renderer = ImageRenderer(aggregator, config.display)
        eink_renderer = EinkRenderer(config.display)
        display_obj = EinkDisplay(config.display)

        eink_stop_event = threading.Event()
        eink_thread = threading.Thread(
            target=_eink_loop,
            args=(
                renderer,
                eink_renderer,
                display_obj,
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
    web_app = create_app(config, aggregator, config_path)

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
        # Stop the display before uvicorn begins draining connections.
        if eink_stop_event is not None:
            eink_stop_event.set()
        if display_obj is not None:
            display_obj.stop()
        # Ask uvicorn to drain and exit.
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
    if config.display.type == "hdmi" and display_obj is not None:
        # On macOS, AppKit requires pygame to run on the main thread.
        # Uvicorn runs in a background daemon thread instead.
        server_thread = threading.Thread(target=server.run, name="uvicorn", daemon=True)
        server_thread.start()
        display_obj.run()          # blocks on main thread until pygame window closes
        server.should_exit = True  # signal uvicorn to drain and exit
        server_thread.join(timeout=10)
    else:
        server.run()

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
