"""Family Planner — application entry point.

Wires together all subsystems:
  - Configuration (Pydantic / YAML)
  - Calendar aggregator (ICS + CalDAV)
  - Renderer (PillowEinkRenderer — Pillow-native, no browser)
  - Display (HDMI pygame main-thread loop *or* e-ink periodic push)
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
from app.renderer.pillow_eink_renderer import PillowEinkRenderer
from app.renderer.state import NavigationState
from app.server.app import create_app

if TYPE_CHECKING:
    from app.display.eink import EinkDisplay, InkyDisplay
    from app.renderer.eink_renderer import EinkRenderer
    from app.weather.provider import WeatherProvider

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
    renderer: PillowEinkRenderer,
    eink_renderer: "EinkRenderer",
    display: "EinkDisplay",
    aggregator: CalendarAggregator,
    interval: int,
    stop_event: threading.Event,
) -> None:
    """Periodically render and push frames to the e-ink panel.

    Runs in a dedicated daemon thread.
    """
    from app.calendar.data_builders import events_range_for_state

    logger.info("E-ink loop avviato (interval=%ds).", interval)

    while not stop_event.is_set():
        state = NavigationState()
        start, end = events_range_for_state(state)
        try:
            events = aggregator.get_events(start, end)
            img = renderer.render(state, events)
            processed = eink_renderer.process(img)
            display.push(processed)
        except Exception as exc:  # noqa: BLE001
            logger.error("E-ink render/push error: %s", exc)
        stop_event.wait(timeout=interval)

    logger.info("E-ink loop fermato.")


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
    # Weather provider (optional — only when weather.enabled)
    # ------------------------------------------------------------------
    weather_provider: "WeatherProvider | None" = None
    if config.weather.enabled:
        from app.weather import OpenMeteoProvider

        weather_provider = OpenMeteoProvider(
            latitude=config.weather.latitude,
            longitude=config.weather.longitude,
            units=config.weather.units,
        )
        logger.info(
            "Weather provider: Open-Meteo (lat=%.4f, lon=%.4f, units=%s)",
            config.weather.latitude,
            config.weather.longitude,
            config.weather.units,
        )

    # ------------------------------------------------------------------
    # Renderer + state (shared between display pipeline and web server)
    # ------------------------------------------------------------------
    renderer = PillowEinkRenderer(config, weather_provider=weather_provider)

    # ------------------------------------------------------------------
    # Display initialisation
    # ------------------------------------------------------------------
    display_obj: "EinkDisplay | InkyDisplay | None" = None
    eink_stop_event: threading.Event | None = None
    _hdmi_ref: list = [None]

    if config.display.type == "eink":
        from app.renderer.eink_renderer import EinkRenderer

        eink_renderer = EinkRenderer(config.display)
        if config.display.eink_model.startswith("inky_"):
            from app.display.eink import InkyDisplay
            display_obj = InkyDisplay(config.display)
        else:
            from app.display.eink import EinkDisplay
            display_obj = EinkDisplay(config.display)

        eink_stop_event = threading.Event()
        eink_thread = threading.Thread(
            target=_eink_loop,
            args=(
                renderer,
                eink_renderer,
                display_obj,
                aggregator,
                config.display.refresh_interval,
                eink_stop_event,
            ),
            daemon=True,
            name="eink-loop",
        )
        eink_thread.start()
        logger.info(
            "E-ink loop avviato (model=%s, palette=%s, interval=%ds).",
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
        # Signal the pygame window to close (if running).
        if _hdmi_ref[0] is not None:
            _hdmi_ref[0].stop()
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
            if _hdmi_ref[0] is not None:
                _hdmi_ref[0].set_aggregator(new_aggregator)
            # Rebuild weather provider with updated settings.
            new_weather_provider: "WeatherProvider | None" = None
            if new_config.weather.enabled:
                from app.weather import OpenMeteoProvider
                new_weather_provider = OpenMeteoProvider(
                    latitude=new_config.weather.latitude,
                    longitude=new_config.weather.longitude,
                    units=new_config.weather.units,
                )
            # Rebuild renderer so display/layout/timezone changes take effect.
            new_renderer = PillowEinkRenderer(new_config, weather_provider=new_weather_provider)
            web_app.state.renderer = new_renderer
            if _hdmi_ref[0] is not None:
                _hdmi_ref[0].set_renderer(new_renderer)
            # Refresh template globals used by the browser preview.
            web_app.state.templates.env.globals["refresh_interval"] = new_config.display.refresh_interval
            web_app.state.templates.env.globals["show_buttons"] = new_config.display.show_buttons
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

    if config.display.type == "hdmi":
        from app.display.hdmi import HdmiDisplay

        hdmi = HdmiDisplay(config.display, renderer, aggregator)
        _hdmi_ref[0] = hdmi

        # Uvicorn in daemon thread — must start before run_blocking()
        uv_thread = threading.Thread(
            target=server.run,
            daemon=True,
            name="uvicorn",
        )
        uv_thread.start()

        hdmi.run_blocking()  # blocks main thread until window is closed

        # Shutdown after pygame exits
        if eink_stop_event is not None:
            eink_stop_event.set()
        server.should_exit = True
        logger.info("Family Planner stopped.")
        return

    # E-ink / no display — Uvicorn runs on the main thread
    async def _serve() -> None:
        """Run uvicorn with an exception handler that suppresses harmless
        BrokenPipeError futures that arise when the client disconnects
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
