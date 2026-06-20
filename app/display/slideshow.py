"""Slideshow controller for artwork/pictures mode.

``SlideshowController`` drives automatic artwork advancement on a configurable
interval.  A single worker thread sleeps ``interval_minutes()`` (read live each
cycle), then performs one artwork advance+push, repeating until the slideshow is
stopped, artwork mode is left, or the app stops.

The controller is deliberately free of any rendering or GPIO imports: the
``advance`` callable injected by ``main()`` is the only place that touches the
renderer/display.  This keeps the module trivially unit-testable with a fake
clock and a stub push (no real time, no GPIO, no network).
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable

logger = logging.getLogger(__name__)


class SlideshowController:
    """Drives automatic artwork advancement on a configurable interval.

    Toggling is idempotent and a no-op outside artwork mode.  All public
    methods are safe to call from the GPIO callback thread.

    Args:
        advance: Performs one artwork advance + push (render_artwork →
            process_photo → display.push).  Called only from the worker thread.
        artwork_mode: Set while the panel shows artwork; the slideshow only
            runs while this is set.
        stop_event: App-wide shutdown signal; when set the worker exits.
        interval_minutes: Returns the current interval in minutes, read live
            each cycle so a SIGHUP config reload changes the *next* interval.
    """

    def __init__(
        self,
        *,
        advance: Callable[[], None],
        artwork_mode: threading.Event,
        stop_event: threading.Event,
        interval_minutes: Callable[[], int],
    ) -> None:
        self._advance = advance
        self._artwork_mode = artwork_mode
        self._stop = stop_event
        self._interval_minutes = interval_minutes
        self._active = False
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    @property
    def active(self) -> bool:
        """``True`` while the slideshow worker is running."""
        return self._active

    def toggle(self) -> None:
        """Start the slideshow if stopped, stop it if running.

        No-op (logged at INFO) if artwork mode is not active.
        """
        with self._lock:
            if self._active:
                self._stop_locked()
                return
            if not self._artwork_mode.is_set():
                logger.info("Slideshow: no-op (non in modalità artwork).")
                return
            self._active = True
            self._cancel.clear()
            self._thread = threading.Thread(
                target=self._run, daemon=True, name="slideshow"
            )
            self._thread.start()
            logger.info("Slideshow attivato.")

    def stop(self) -> None:
        """Stop the slideshow if running.  Idempotent.

        Called when leaving artwork mode or shutting down.
        """
        with self._lock:
            self._stop_locked()

    def _stop_locked(self) -> None:
        if not self._active:
            return
        self._active = False
        self._cancel.set()  # wakes the interruptible sleep so the worker exits

    def _run(self) -> None:
        while self._active and self._artwork_mode.is_set() and not self._stop.is_set():
            # Interruptible sleep: wake immediately on cancel/stop.
            interval = max(1, self._interval_minutes())
            if self._cancel.wait(timeout=interval * 60):
                break  # toggled off / stopped
            if not (self._artwork_mode.is_set() and self._active):
                break  # mode changed during the wait
            if self._stop.is_set():
                break
            try:
                self._advance()  # render_artwork → process_photo → push
            except Exception:
                logger.exception("Slideshow: errore durante l'avanzamento.")
        self._active = False
        logger.info("Slideshow fermato.")
