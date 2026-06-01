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
import subprocess
import threading
import time
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


# ---------------------------------------------------------------------------
# E-ink change-detection debug helpers
# ---------------------------------------------------------------------------


def _log_events_diff(old_events: list, new_events: list) -> None:
    """Log a DEBUG summary of which events were added, removed, or modified."""
    import dataclasses

    old_by_uid = {e.uid: e for e in old_events}
    new_by_uid = {e.uid: e for e in new_events}
    added   = [e for uid, e in new_by_uid.items() if uid not in old_by_uid]
    removed = [e for uid, e in old_by_uid.items() if uid not in new_by_uid]
    changed = [
        e for uid, e in new_by_uid.items()
        if uid in old_by_uid and e != old_by_uid[uid]
    ]
    if added:
        logger.debug(
            "E-ink diff eventi — aggiunti (%d): %s",
            len(added),
            [f"{e.title!r} ({e.start:%Y-%m-%d})" for e in added[:5]],
        )
    if removed:
        logger.debug(
            "E-ink diff eventi — rimossi (%d): %s",
            len(removed),
            [f"{e.title!r} ({e.start:%Y-%m-%d})" for e in removed[:5]],
        )
    for e in changed[:5]:
        old = old_by_uid[e.uid]
        diff_fields = [
            f.name
            for f in dataclasses.fields(e)
            if getattr(e, f.name) != getattr(old, f.name)
        ]
        logger.debug(
            "E-ink diff eventi — modificato %r, campi: %s",
            e.title,
            diff_fields,
        )
    if not added and not removed and not changed:
        logger.debug(
            "E-ink diff eventi — lista diversa ma nessuna diff per uid/contenuto "
            "(conteggio: %d→%d)",
            len(old_events),
            len(new_events),
        )


def _log_weather_diff(old: object, new: object) -> None:
    """Log a DEBUG summary of which WeatherData fields changed."""
    import dataclasses

    diffs = []
    for f in dataclasses.fields(old):  # type: ignore[arg-type]
        ov, nv = getattr(old, f.name), getattr(new, f.name)
        if ov != nv:
            if f.name == "hourly_forecast":
                diffs.append(f"hourly_forecast: {len(ov)} slot → {len(nv)} slot")
            else:
                diffs.append(f"{f.name}: {ov!r} → {nv!r}")
    if diffs:
        logger.debug("E-ink diff meteo — %s", ", ".join(diffs))
    else:
        logger.debug("E-ink diff meteo — oggetti diversi ma stesso contenuto per tutti i campi")


def _eink_loop(
    renderer_ref: list,
    eink_renderer_ref: list,
    display: "EinkDisplay",
    aggregator: CalendarAggregator,
    interval: int,
    stop_event: threading.Event,
    artwork_mode: threading.Event,
    wake_event: threading.Event,
    weather_provider: "WeatherProvider | None" = None,
) -> None:
    """Periodically render and push frames to the e-ink panel.

    Runs in a dedicated daemon thread.

    When *artwork_mode* is set the loop still refreshes calendar data but
    suppresses the panel push so the artwork displayed by button B is not
    overwritten.  Setting *wake_event* causes the loop to skip the remaining
    sleep and re-render immediately (used by button A to return to planner).

    Change detection: the panel push is skipped when state, events and weather
    are all unchanged since the last push.  Detailed differences are logged at
    DEBUG level to help diagnose spurious refreshes.  *force_refresh* is set
    True on the first iteration and whenever *wake_event* fires (button A
    return-to-planner) so those pushes are never suppressed.
    """
    from app.calendar.data_builders import events_range_for_state
    from app.renderer.tokens import WeatherData

    # Maximum time allowed for a single panel push (epd.init + Clear + display + sleep).
    # Waveshare 7.5" V2 typically completes in 20-30 s; 120 s is a generous safety margin.
    # If the BUSY pin hangs, the push thread stays alive but we keep the loop running.
    _PUSH_TIMEOUT = 120

    last_state: NavigationState | None = None
    last_events: list = []
    last_weather: WeatherData = WeatherData()
    force_refresh: bool = True  # always push on first iteration

    while not stop_event.is_set():
        state = NavigationState()
        start, end = events_range_for_state(state)
        try:
            events = aggregator.get_events(start, end)
            weather = weather_provider.get() if weather_provider is not None else WeatherData()

            # --- change detection with debug logging ---
            content_changed = force_refresh
            if not force_refresh:
                if state != last_state:
                    logger.debug(
                        "E-ink diff stato — anchor_date: %s → %s",
                        last_state.anchor_date if last_state else None,
                        state.anchor_date,
                    )
                    content_changed = True
                if events != last_events:
                    _log_events_diff(last_events, events)
                    content_changed = True
                if weather != last_weather:
                    _log_weather_diff(last_weather, weather)
                    content_changed = True

            if content_changed:
                img = renderer_ref[0].render(state, events)
                processed = eink_renderer_ref[0].process(img)
                last_state = state
                last_events = events
                last_weather = weather

                if not artwork_mode.is_set():
                    push_thread = threading.Thread(
                        target=display.push,
                        args=(processed,),
                        daemon=True,
                        name="eink-push",
                    )
                    push_thread.start()
                    push_thread.join(timeout=_PUSH_TIMEOUT)
                    if push_thread.is_alive():
                        logger.error(
                            "E-ink push did not complete within %ds — "
                            "panel BUSY pin may be stuck. Skipping frame; "
                            "the push thread will finish in the background "
                            "once the panel responds.",
                            _PUSH_TIMEOUT,
                        )
                    else:
                        logger.info("E-ink: variazione rilevata — push completato.")
            else:
                logger.debug("E-ink: nessuna variazione — push saltato.")

        except Exception as exc:  # noqa: BLE001
            logger.error("E-ink render/push error: %s", exc)

        force_refresh = False

        # Interruptible sleep: wake early if wake_event fires (button A) or
        # stop_event fires (shutdown).  Poll every 0.5 s so the loop remains
        # responsive without busy-waiting.
        deadline = time.monotonic() + interval
        while not stop_event.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            if wake_event.wait(timeout=min(remaining, 0.5)):
                wake_event.clear()
                force_refresh = True  # ritorno da artwork: push incondizionato
                break

    logger.info("E-ink loop fermato.")


# ---------------------------------------------------------------------------
# Physical button helpers (Inky Impression)
# ---------------------------------------------------------------------------


def _perform_shutdown(
    renderer: PillowEinkRenderer,
    eink_renderer: "EinkRenderer",
    display: "InkyDisplay",
    stop_event: threading.Event,
    server: "uvicorn.Server",
) -> None:
    """Render a shutdown screen, push it to the panel, then power off.

    Called from a daemon thread spawned by the GPIO callback.  Protected
    against double-invocation by ``_shutdown_triggered`` at the call site.

    Sequence:
      1. Stop the normal e-ink refresh loop.
      2. Render a plain background (fast, no network) and push to the panel.
      3. Signal the web server to exit.
      4. Issue ``sudo shutdown -h now``.
    """
    logger.info("Shutdown avviato dal pulsante D — rendering artwork prima dello spegnimento.")
    stop_event.set()

    try:
        img = renderer.render_artwork()
        processed = eink_renderer.process(img)
        display.push(processed)
        logger.info("_perform_shutdown: artwork inviato al pannello.")
    except Exception:  # noqa: BLE001
        logger.exception("_perform_shutdown: errore artwork, fallback a schermata bianca.")
        try:
            from app.renderer.tokens import get_palette
            from PIL import Image

            palette = get_palette()
            W, H = renderer._size  # noqa: SLF001
            img = Image.new("RGB", (W, H), palette["BG"])
            processed = eink_renderer.process(img)
            display.push(processed)
        except Exception:  # noqa: BLE001
            logger.exception("_perform_shutdown: errore anche nel fallback.")

    server.should_exit = True
    logger.info("_perform_shutdown: esecuzione sudo shutdown -h now")
    result = subprocess.run(["sudo", "shutdown", "-h", "now"], check=False)  # noqa: S603 S607
    if result.returncode != 0:
        logger.error(
            "_perform_shutdown: sudo shutdown fallito (exit %d). "
            "Verificare che sudoers sia configurato con setup-autostart.sh.",
            result.returncode,
        )


def _perform_show_artwork(
    renderer: PillowEinkRenderer,
    eink_renderer: "EinkRenderer",
    display: "InkyDisplay",
    artwork_mode: threading.Event,
) -> None:
    """Fetch and push a random landscape painting to the e-ink panel.

    Sets *artwork_mode* immediately so that the refresh loop suppresses its
    next push while the artwork is being fetched and sent to the panel.
    The actual fetch + push runs in a daemon thread to avoid blocking the
    GPIO callback.
    """
    artwork_mode.set()
    logger.info("Modalità artwork attivata (pulsante B).")

    def _push() -> None:
        try:
            img = renderer.render_artwork()
            if not artwork_mode.is_set():
                # Button A was pressed during the fetch — skip the push to avoid
                # a panel refresh that would immediately be overwritten by planner.
                logger.info("artwork-push: annullato durante il fetch (pulsante A premuto).")
                return
            processed = eink_renderer.process(img)
            display.push(processed)
            logger.info("Artwork inviato al pannello.")
        except Exception:  # noqa: BLE001
            logger.exception("_perform_show_artwork: errore durante fetch/push dell'artwork.")

    threading.Thread(target=_push, daemon=True, name="artwork-push").start()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    _setup_logging()
    args = _parse_args()

    config_path: Path = args.config.resolve()
    config = load_config(config_path)

    _loopback = config.server.host in ("127.0.0.1", "localhost", "::1")
    _auth_on = bool(config.server.auth_username and config.server.auth_password)
    if not _loopback and not _auth_on:
        logger.warning(
            "Server in ascolto su %s senza autenticazione: le rotte /config sono "
            "raggiungibili da chiunque sulla rete. Impostare server.auth_username/"
            "auth_password oppure host: 127.0.0.1.",
            config.server.host,
        )

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
    _eink_renderer_ref: list = [None]
    _renderer_ref: list = [renderer]

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
            _renderer_ref[0] = new_renderer
            if _hdmi_ref[0] is not None:
                _hdmi_ref[0].set_renderer(new_renderer)
                _hdmi_ref[0].set_weather_provider(new_weather_provider)
            # Rebuild EinkRenderer so palette/dithering/rotation changes take effect
            # in the e-ink push loop without requiring a full process restart.
            if _eink_renderer_ref[0] is not None:
                from app.renderer.eink_renderer import EinkRenderer as _EinkRenderer
                _eink_renderer_ref[0] = _EinkRenderer(new_config.display)
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

    if config.display.type == "eink":
        from app.renderer.eink_renderer import EinkRenderer

        _eink_renderer_ref[0] = EinkRenderer(config.display)
        eink_renderer = _eink_renderer_ref[0]
        if config.display.eink_model.startswith("inky_"):
            from app.display.eink import InkyDisplay
            display_obj = InkyDisplay(config.display)
        else:
            from app.display.eink import EinkDisplay
            display_obj = EinkDisplay(config.display)

        eink_stop_event = threading.Event()
        _artwork_mode = threading.Event()
        _wake_event = threading.Event()

        eink_thread = threading.Thread(
            target=_eink_loop,
            args=(
                _renderer_ref,
                _eink_renderer_ref,
                display_obj,
                aggregator,
                config.display.refresh_interval,
                eink_stop_event,
                _artwork_mode,
                _wake_event,
            ),
            kwargs={"weather_provider": weather_provider},
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

        # ----------------------------------------------------------
        # Physical button handler (Inky Impression only)
        # ----------------------------------------------------------
        if config.display.eink_model.startswith("inky_"):
            from app.display.buttons import InkyButtonHandler

            _shutdown_triggered = threading.Event()

            def _on_button(button: str) -> None:
                if _shutdown_triggered.is_set():
                    return  # ignore all buttons after shutdown is initiated

                if button == "B":
                    # Show a random landscape painting from Art Institute of Chicago.
                    _perform_show_artwork(
                        _renderer_ref[0],
                        _eink_renderer_ref[0],
                        display_obj,  # type: ignore[arg-type]
                        _artwork_mode,
                    )

                elif button == "A":
                    # Return to the planner.  We must not wake the eink loop
                    # directly: if an artwork push is in progress the loop would
                    # queue a planner push that starts immediately after the
                    # artwork finishes, causing two back-to-back panel refreshes.
                    # Instead we start a daemon thread that waits for the panel
                    # to become free (_push_lock) and only then wakes the loop.
                    if _artwork_mode.is_set():
                        _artwork_mode.clear()
                        logger.info("Modalit\u00e0 artwork disattivata (pulsante A) \u2014 ritorno al planner.")

                    def _return_to_planner() -> None:
                        # Acquiring the lock blocks until any in-progress push
                        # (artwork or planner) completes; releasing it immediately
                        # leaves the panel free for the loop's next push.
                        display_obj._push_lock.acquire()  # type: ignore[union-attr]
                        display_obj._push_lock.release()  # type: ignore[union-attr]
                        # The EL133UF1 ACeP controller continues internal processing
                        # briefly after BUSY goes HIGH and inky.show() returns.
                        # Starting a new refresh within ~1 s of the previous one
                        # results in the new image being silently discarded by the
                        # hardware (panel reports success but pixels do not update).
                        # A short settling delay prevents this race.
                        _PANEL_SETTLE_S = 5
                        logger.info(
                            "return-planner: attesa settling pannello (%ds)...", _PANEL_SETTLE_S
                        )
                        time.sleep(_PANEL_SETTLE_S)
                        _wake_event.set()

                    threading.Thread(
                        target=_return_to_planner, daemon=True, name="return-planner"
                    ).start()

                elif button == "D":
                    # Shutdown: stop the loop and power off the device.
                    _shutdown_triggered.set()
                    threading.Thread(
                        target=_perform_shutdown,
                        args=(_renderer_ref[0], _eink_renderer_ref[0], display_obj, eink_stop_event, server),
                        daemon=True,
                        name="shutdown",
                    ).start()

            _button_handler = InkyButtonHandler(eink_model=config.display.eink_model)
            _button_handler.start(_on_button, eink_stop_event)
            logger.info("InkyButtonHandler avviato (A=planner, B=artwork, D=shutdown).")

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

        if not HdmiDisplay.probe():
            logger.warning(
                "HDMI display not available (pygame could not open a window). "
                "Check SDL_VIDEODRIVER and display hardware. "
                "Falling back to web-server-only mode."
            )
        else:
            hdmi = HdmiDisplay(config.display, renderer, aggregator, weather_provider)
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
            if hdmi.shutdown_requested:
                logger.info("Tasto D: esecuzione sudo shutdown -h now")
                result = subprocess.run(["sudo", "shutdown", "-h", "now"], check=False)  # noqa: S603 S607
                if result.returncode != 0:
                    logger.error(
                        "sudo shutdown fallito (exit %d). "
                        "Verificare che sudoers sia configurato con setup-autostart.sh.",
                        result.returncode,
                    )
            else:
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
