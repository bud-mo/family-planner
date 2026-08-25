"""Family Planner — application entry point.

Wires together all subsystems:
  - Configuration (Pydantic / YAML)
  - Calendar aggregator (ICS + CalDAV)
  - Renderer (PillowEinkRenderer — Pillow-native, no browser)
  - Display (e-ink periodic push; web-server-only when no panel is attached)
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
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import uvicorn

from app.calendar.aggregator import CalendarAggregator
from app.config import load_config
from app.renderer.pillow_eink_renderer import PillowEinkRenderer
from app.renderer.state import NavigationState
from app.scheduling import RefreshPolicy
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


def _round(value: float | None) -> int | None:
    """Round to the integer precision the banner actually prints (``:.0f``)."""
    return None if value is None else round(value)


def _calendar_signature(state: "NavigationState", events: list) -> tuple:
    """Return an order-independent signature of the calendar half of the frame.

    Only fields that are actually drawn take part, so that invisible churn never
    costs a repaint.  Deliberately excluded:

      * ``uid`` — event identity is not on screen.  Feeds regenerated per request
        can hand back the same appointment under a fresh uid; a set of events
        that *looks* identical must sign identically.  Additions and deletions
        are still caught, because they change the number of entries.
      * ``attendees``, ``recurrent``, ``calendar_name`` — never rendered (no
        occurrence anywhere in ``app/renderer/``).  Editing the guest list of an
        appointment used to repaint the panel to pixel-identical output.

    ``description`` and ``location`` *are* included: the agenda renders both
    (see ``app/renderer/components/agenda.py``).  The agenda drops them when a
    row runs out of vertical space, so an edit to a hidden description can still
    trigger a repaint — over-triggering is the safe direction, and it keeps this
    function free of layout knowledge.

    Start/end are truncated to the minute, the precision shown by the ``HH:MM``
    label, and the events are sorted into a canonical order so that two fetches
    with the same content always produce the same signature.
    """

    def _minute(dt: datetime) -> str:
        return dt.replace(second=0, microsecond=0).isoformat()

    events_sig = tuple(sorted(
        (
            e.title,
            _minute(e.start),
            _minute(e.end),
            e.all_day,
            e.location or "",
            e.description or "",
            e.color,
        )
        for e in events
    ))
    return (state.anchor_date.isoformat(), events_sig)


def _weather_signature(weather: object) -> tuple:
    """Return a signature of the weather banner as drawn.

    Temperatures are rounded to the displayed precision so sub-degree jitter
    never repaints the panel.  ``description`` is excluded: it is carried in
    ``WeatherData`` but no component draws it, and it is finer-grained than the
    icon it accompanies (WMO 61/63/65 all map to ``cloud-rain`` while the text
    differs), so it used to be a pure source of invisible repaints.

    Inside the quiet band the instantaneous fields arrive already cleared (see
    :func:`app.weather.provider.strip_instant_fields`), which is what makes the
    night frames stable: only the bihourly strip can still move them.
    """
    return (
        weather.condition_icon,
        _round(weather.temp_current),
        _round(weather.temp_max),
        _round(weather.temp_min),
        tuple(
            (s.hour, s.condition_icon, _round(s.temp))
            for s in weather.hourly_forecast
        ),
    )


def _content_signature(
    state: "NavigationState",
    events: list,
    weather: object,
) -> tuple:
    """Return the full frame signature as ``(calendar, weather)``.

    Kept split so the loop can tell *which half* moved: a calendar change earns
    an immediate repaint (someone added an appointment and wants to see it),
    while a weather change waits for the next display tick.
    """
    return (_calendar_signature(state, events), _weather_signature(weather))


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
    aggregator_ref: list,
    stop_event: threading.Event,
    artwork_mode: threading.Event,
    wake_event: threading.Event,
    policy_ref: list,
    weather_provider: "WeatherProvider | None" = None,
) -> None:
    """Render and push frames to the e-ink panel, repainting as rarely as possible.

    Runs in a dedicated daemon thread.  A repaint costs 20-30 s of flashing and
    panel wear, so the loop separates three things that are easy to conflate:

      * **poll** — the network fetch, every ``calendar_poll_minutes``.  Cheap;
        it never repaints anything on its own.
      * **display tick** — the clock-aligned grid on which the panel is allowed
        to repaint, bihourly by default so it lands exactly when the weather's
        bihourly window advances.  See [app/scheduling.py].
      * **push** — the repaint itself, which happens only when the content that
        reaches the panel actually differs from what is already on it.

    Consequences, in order of how often they bite:

      * a display tick with unchanged content pushes nothing;
      * a calendar change earns an immediate push (someone added an appointment
        and expects to see it), rate-limited to one per
        ``min_push_interval_minutes`` so a burst of edits from a phone collapses
        into a single repaint;
      * a weather change *between* ticks is held back until the next tick — it
        is never urgent — unless it is the recovery from a failed fetch, in which
        case the panel is currently showing degraded data and the catch-up push
        is worth it;
      * inside the quiet band nothing is pushed except the ticks listed in
        ``quiet_hours.allowed_ticks``, and the loop does not even poll: an e-ink
        panel holds its image for free, and at 03:00 nobody is reading it.

    Frames rendered inside the quiet band drop the instantaneous weather fields
    (see :func:`app.weather.provider.strip_instant_fields`).  The midnight frame
    stays up until 06:00, and a temperature read at midnight is simply wrong by
    dawn.  The projection is applied *before* the signature is computed, so what
    is signed is always exactly what is drawn.

    When *artwork_mode* is set the loop keeps refreshing its data but suppresses
    the push, so the artwork shown by button B is not overwritten.  Setting
    *wake_event* skips the remaining sleep and re-renders at once, forcing a
    fresh fetch of *both* weather and calendar (button A: return to planner).

    Two baselines are tracked on purpose.  ``last_pushed_sig`` is what is on the
    glass and decides whether a push is needed; it advances only when a push
    actually succeeds, so a change deferred by the quiet band or the cooldown is
    still pending — and still pushed — at the next opportunity.
    ``last_seen_sig`` tracks data changes for the footer's "Ultimo
    aggiornamento", which reports when the data last changed rather than the
    wall-clock time of the repaint.
    """
    from app.calendar.data_builders import events_range_for_state
    from app.renderer.tokens import WeatherData
    from app.weather.provider import strip_instant_fields

    # Maximum time allowed for a single panel push (epd.init + Clear + display + sleep).
    # Waveshare 7.5" V2 typically completes in 20-30 s; 120 s is a generous safety margin.
    # If the BUSY pin hangs, the push thread stays alive but we keep the loop running.
    _PUSH_TIMEOUT = 120

    last_events: list = []
    last_weather: WeatherData = WeatherData()
    last_pushed_sig: tuple | None = None   # cosa c'è sul pannello
    last_seen_sig: tuple | None = None     # cosa abbiamo visto nei dati
    last_change_at: datetime = datetime.now()
    last_push_at: datetime | None = None
    force_refresh: bool = True   # always push on first iteration
    manual_refresh: bool = True  # first iteration: fetch both weather + calendar fresh
    weather_retry: bool = False  # last weather fetch failed: retry at the next wake
    # Il momento per cui il loop si è svegliato.  Si valuta la griglia su questo
    # istante esatto, non su `datetime.now()`: il risveglio arriva con qualche
    # decina di millisecondi di ritardo, e un confronto sull'ora reale
    # mancherebbe ogni singolo confine.
    tick_moment: datetime = datetime.now()

    while not stop_event.is_set():
        policy = policy_ref[0]
        state = NavigationState()
        start, end = events_range_for_state(state)
        try:
            now = datetime.now()
            display_tick = force_refresh or policy.is_display_tick(tick_moment)
            fetch_weather = display_tick or manual_refresh or weather_retry

            events = aggregator_ref[0].get_events(start, end, force=True)
            if weather_provider is not None:
                weather = weather_provider.get(force=fetch_weather)
                weather_recovered = (
                    weather_retry and not weather_provider.last_fetch_failed
                )
                weather_retry = fetch_weather and weather_provider.last_fetch_failed
                if weather_retry:
                    logger.info(
                        "Meteo: fetch fallito — uso cache (slot scaduti rimossi), "
                        "nuovo tentativo al prossimo risveglio."
                    )
            else:
                weather = WeatherData()
                weather_recovered = False
                weather_retry = False

            # Variante notturna: applicata qui, prima della firma, così che
            # contenuto firmato e contenuto disegnato non possano divergere.
            # Copre la fascia di quiete *e* i tick che la servono (sigillo e
            # mezzanotte), che restano notturni anche se configurati fuori dai
            # confini — i loro frame durano comunque fino al mattino.
            if policy.is_night_frame(now):
                weather = strip_instant_fields(weather)

            signature = _content_signature(state, events, weather)

            # --- il footer segue le variazioni dei dati, non i repaint ---
            if signature != last_seen_sig:
                last_change_at = now
                last_seen_sig = signature

            content_changed = last_pushed_sig is None or signature != last_pushed_sig
            calendar_changed = (
                last_pushed_sig is None or signature[0] != last_pushed_sig[0]
            )

            # DEBUG diff: explain *what* changed (only when it did, to keep logs quiet).
            if content_changed and not force_refresh and logger.isEnabledFor(logging.DEBUG):
                if events != last_events:
                    _log_events_diff(last_events, events)
                if weather != last_weather:
                    _log_weather_diff(last_weather, weather)

            cooldown = timedelta(minutes=policy.min_push_interval_minutes)
            cooled_down = last_push_at is None or (now - last_push_at) >= cooldown

            # --- decisione di push ---
            push_reason: str | None = None
            if force_refresh:
                push_reason = "refresh forzato"
            elif not content_changed:
                logger.debug("E-ink: nessuna variazione — push saltato.")
            elif display_tick:
                push_reason = "tick display"
            elif not policy.push_allowed(now):
                logger.debug(
                    "E-ink: variazione in fascia di quiete — push differito al "
                    "tick di riapertura."
                )
            elif not cooled_down:
                logger.debug(
                    "E-ink: variazione entro il cooldown di %d min — push differito.",
                    policy.min_push_interval_minutes,
                )
            elif calendar_changed:
                push_reason = "variazione calendario"
            elif weather_recovered:
                push_reason = "recupero dati meteo"
            else:
                logger.debug(
                    "E-ink: variazione solo meteo fuori tick — push differito al "
                    "prossimo tick display."
                )

            if push_reason is not None and artwork_mode.is_set():
                logger.debug(
                    "E-ink: push (%s) saltato — modalità artwork attiva.", push_reason
                )
            elif push_reason is not None:
                img = renderer_ref[0].render(
                    state, events, updated_at=last_change_at, weather=weather
                )
                processed = eink_renderer_ref[0].process(img)
                push_thread = threading.Thread(
                    target=display.push,
                    args=(processed,),
                    daemon=True,
                    name="eink-push",
                )
                push_thread.start()
                push_thread.join(timeout=_PUSH_TIMEOUT)
                if push_thread.is_alive():
                    # Baseline deliberatamente non aggiornata: il frame non è
                    # (ancora) sul pannello, quindi la variazione resta pendente
                    # e verrà ritentata al prossimo risveglio.
                    logger.error(
                        "E-ink push did not complete within %ds — "
                        "panel BUSY pin may be stuck. Skipping frame; "
                        "the push thread will finish in the background "
                        "once the panel responds.",
                        _PUSH_TIMEOUT,
                    )
                else:
                    last_pushed_sig = signature
                    last_events = events
                    last_weather = weather
                    last_push_at = datetime.now()
                    logger.info("E-ink: push completato (%s).", push_reason)

        except Exception as exc:  # noqa: BLE001
            logger.error("E-ink render/push error: %s", exc)

        force_refresh = False
        manual_refresh = False

        # Sleep until the next useful moment — a display tick or a calendar poll,
        # whichever comes first (during the quiet band the polls are skipped, so
        # this is a single long sleep).  Interruptible: wake early if wake_event
        # fires (button A) or stop_event fires (shutdown).  Poll every 0.5 s so
        # the loop stays responsive without busy-waiting.
        target = policy_ref[0].next_wake(datetime.now())
        tick_moment = target
        while not stop_event.is_set():
            remaining = (target - datetime.now()).total_seconds()
            if remaining <= 0:
                break
            if wake_event.wait(timeout=min(remaining, 0.5)):
                wake_event.clear()
                force_refresh = True   # ritorno da artwork: push incondizionato
                manual_refresh = True  # pulsante A: rifetch meteo + calendario
                tick_moment = datetime.now()
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
        processed = eink_renderer.process_photo(img)
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

    When the mode is freshly entered (it was not already active) the folder
    cursor is reset, so each entry starts from the first picture; pressing the
    button again while already in artwork mode advances to the next image.
    """
    if not artwork_mode.is_set():
        renderer.reset_artwork_cursor()
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
            processed = eink_renderer.process_photo(img)
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

    # Il TTL della cache eventi segue il *poll* del calendario, non la cadenza
    # dei repaint: legarlo alla griglia bihoraria congelerebbe l'anteprima web
    # per due ore, e ricaricare una pagina non costa un refresh del pannello.
    aggregator = CalendarAggregator(
        config.calendars,
        cache_ttl=config.refresh.calendar_poll_minutes * 60,
    )

    policy = RefreshPolicy.from_config(config.refresh)
    logger.info(
        "Politica refresh: display ogni %d min, poll calendario ogni %d min, "
        "cooldown push %d min, quiete %s.",
        policy.display_interval_minutes,
        policy.calendar_poll_minutes,
        policy.min_push_interval_minutes,
        (
            f"{config.refresh.quiet_hours.start}–{config.refresh.quiet_hours.end} "
            f"(tick consentiti: {', '.join(config.refresh.quiet_hours.allowed_ticks) or 'nessuno'})"
            if config.refresh.quiet_hours.enabled
            else "disattivata"
        ),
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
            cache_ttl=config.refresh.display_interval_minutes * 60,
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
    _eink_renderer_ref: list = [None]
    _renderer_ref: list = [renderer]
    _aggregator_ref: list = [aggregator]
    _policy_ref: list = [policy]

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
                cache_ttl=new_config.refresh.calendar_poll_minutes * 60,
            )
            web_app.state.aggregator = new_aggregator
            _aggregator_ref[0] = new_aggregator
            # Le cadenze sono ricaricabili a caldo: il loop rilegge la politica
            # a ogni iterazione, quindi la nuova griglia vale dal prossimo
            # risveglio senza riavviare il processo.
            _policy_ref[0] = RefreshPolicy.from_config(new_config.refresh)
            # Rebuild weather provider with updated settings.
            new_weather_provider: "WeatherProvider | None" = None
            if new_config.weather.enabled:
                from app.weather import OpenMeteoProvider
                new_weather_provider = OpenMeteoProvider(
                    latitude=new_config.weather.latitude,
                    longitude=new_config.weather.longitude,
                    units=new_config.weather.units,
                    cache_ttl=new_config.refresh.display_interval_minutes * 60,
                )
            # Rebuild renderer so display/layout/timezone changes take effect.
            new_renderer = PillowEinkRenderer(new_config, weather_provider=new_weather_provider)
            web_app.state.renderer = new_renderer
            _renderer_ref[0] = new_renderer
            # Rebuild EinkRenderer so palette/dithering/rotation changes take effect
            # in the e-ink push loop without requiring a full process restart.
            if _eink_renderer_ref[0] is not None:
                from app.renderer.eink_renderer import EinkRenderer as _EinkRenderer
                _eink_renderer_ref[0] = _EinkRenderer(new_config.display)
            # Refresh template globals used by the browser preview.
            web_app.state.templates.env.globals["show_buttons"] = new_config.display.show_buttons
            logger.info("Configuration reloaded successfully.")
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to reload configuration: %s", exc)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    if hasattr(signal, "SIGHUP"):  # not available on Windows
        signal.signal(signal.SIGHUP, _reload_config)

    from app.display.eink import panel_available

    if panel_available():
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
                _aggregator_ref,
                eink_stop_event,
                _artwork_mode,
                _wake_event,
                _policy_ref,
            ),
            kwargs={"weather_provider": weather_provider},
            daemon=True,
            name="eink-loop",
        )
        eink_thread.start()
        logger.info(
            "E-ink loop avviato (model=%s, palette=%s).",
            config.display.eink_model,
            config.display.eink_palette,
        )

        # ----------------------------------------------------------
        # Physical button handler (Inky Impression only)
        # ----------------------------------------------------------
        if config.display.eink_model.startswith("inky_"):
            from app.display.buttons import InkyButtonHandler, resolve_button_roles
            from app.display.slideshow import SlideshowController

            _shutdown_triggered = threading.Event()

            # Buttons keep the same *physical* position across mounting
            # orientations: a 180°/270° flip swaps A↔D and B↔C.
            #   standard (0°/90°)  : A=planner  B=artwork  C=slideshow  D=shutdown
            #   inverted (180°/270°): A=shutdown C=artwork  B=slideshow  D=planner
            roles = resolve_button_roles(config.display.rotation)
            _planner_button = roles["planner"]
            _artwork_button = roles["artwork"]
            _slideshow_button = roles["slideshow"]
            _shutdown_button = roles["shutdown"]

            def _advance_slideshow() -> None:
                # Reuse the artwork push so the slideshow moves forward.
                # render_artwork() advances the folder cursor / fetches a fresh
                # random work itself, so no extra cursor handling is needed.
                # The mode-change guard mirrors _perform_show_artwork._push.
                img = _renderer_ref[0].render_artwork()
                if not _artwork_mode.is_set():
                    logger.info("slideshow: avanzamento annullato (uscita da artwork).")
                    return
                processed = _eink_renderer_ref[0].process_photo(img)
                display_obj.push(processed)  # type: ignore[union-attr]
                logger.info("Slideshow: immagine successiva inviata al pannello.")

            _slideshow = SlideshowController(
                advance=_advance_slideshow,
                artwork_mode=_artwork_mode,
                stop_event=eink_stop_event,
                interval_minutes=lambda: web_app.state.config.artwork.slideshow_interval_minutes,
            )

            def _on_button(button: str) -> None:
                if _shutdown_triggered.is_set():
                    return  # ignore all buttons after shutdown is initiated

                if button == _artwork_button:
                    # Show a random landscape painting from Art Institute of Chicago.
                    _perform_show_artwork(
                        _renderer_ref[0],
                        _eink_renderer_ref[0],
                        display_obj,  # type: ignore[arg-type]
                        _artwork_mode,
                    )

                elif button == _slideshow_button:
                    # Toggle the auto-advance slideshow. No-op outside artwork mode.
                    _slideshow.toggle()

                elif button == _planner_button:
                    # Return to the planner.  We must not wake the eink loop
                    # directly: if an artwork push is in progress the loop would
                    # queue a planner push that starts immediately after the
                    # artwork finishes, causing two back-to-back panel refreshes.
                    # Instead we start a daemon thread that waits for the panel
                    # to become free (_push_lock) and only then wakes the loop.
                    if _artwork_mode.is_set():
                        _artwork_mode.clear()
                        _slideshow.stop()  # leaving artwork stops the slideshow
                        logger.info(
                            "Modalit\u00e0 artwork disattivata (pulsante %s) \u2014 ritorno al planner.",
                            _planner_button,
                        )

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

                elif button == _shutdown_button:
                    # Shutdown: stop the loop and power off the device.
                    _slideshow.stop()  # defensive — no auto-advance during shutdown
                    _shutdown_triggered.set()
                    threading.Thread(
                        target=_perform_shutdown,
                        args=(_renderer_ref[0], _eink_renderer_ref[0], display_obj, eink_stop_event, server),
                        daemon=True,
                        name="shutdown",
                    ).start()

            _button_handler = InkyButtonHandler(eink_model=config.display.eink_model)
            _button_handler.start(_on_button, eink_stop_event)
            logger.info(
                "InkyButtonHandler avviato (rotation=%d\u00b0: %s=planner, %s=artwork, "
                "%s=slideshow, %s=shutdown).",
                config.display.rotation,
                _planner_button,
                _artwork_button,
                _slideshow_button,
                _shutdown_button,
            )
    else:
        logger.info(
            "No e-ink panel detected (not running on a Raspberry Pi) — "
            "running in web-server-only mode; open the browser preview at /."
        )

    # ------------------------------------------------------------------
    # Run (blocks until server exits) — Uvicorn always runs on the main thread.
    # The e-ink panel (when present) refreshes from its own daemon loop started
    # above; when no panel is attached the app serves only the browser preview.
    # ------------------------------------------------------------------
    logger.info(
        "Web server starting on http://%s:%d",
        config.server.host,
        config.server.port,
    )

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
