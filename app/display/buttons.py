"""Physical button handler for Pimoroni Inky Impression panels.

``InkyButtonHandler`` listens for GPIO falling-edge events from the four
physical buttons of any Inky Impression panel (A=BCM5, B=BCM6, C=BCM16,
D=BCM24) and invokes a callback with the button label.

Only buttons **A**, **B** and **D** are requested from the GPIO chip — button
**C** (BCM16) is **not** acquired because pin 16 is also used as SPI CS1 by
the Pimoroni Inky library.  Requesting that pin simultaneously would prevent
the Inky driver from initialising correctly.

The ``gpiod`` library is imported lazily so this module can be imported on
any platform (macOS, Linux dev machines) without raising ``ImportError``.
``start()`` is a no-op if ``gpiod`` is not available — it logs a WARNING
and returns without starting any thread.

Usage::

    handler = InkyButtonHandler()
    handler.start(callback=my_callback, stop_event=my_stop_event)
    # my_callback("A") is called when button A is pressed
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import timedelta

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hardware constants — standard Pimoroni Inky Impression (all models)
# ---------------------------------------------------------------------------

# Default pin mapping for Inky Impression (all models except 13.3").
# On the Impression 13.3" (inky_impression_13) button C is wired to BCM25
# instead of BCM16 because BCM16 is used as SPI CS1 by the Inky driver
# (inky_el133uf1.py CS1_PIN=16).  Passing eink_model to InkyButtonHandler
# selects the correct pin automatically.
_BUTTON_PINS_DEFAULT: dict[str, int] = {
    "A": 5,
    "B": 6,
    "C": 16,
    "D": 24,
}
_BUTTON_PINS_IMPRESSION_13: dict[str, int] = {
    "A": 5,
    "B": 6,
    "C": 25,   # BCM25 on Impression 13.3" — avoids conflict with SPI CS1 (BCM16)
    "D": 24,
}

# GPIO chip search order: RPi 5 first, RPi 3B+/4 second.
_GPIO_CHIP_CANDIDATES: list[str] = ["/dev/gpiochip4", "/dev/gpiochip0"]

# Minimum seconds between two accepted presses of the same button.
_DEBOUNCE_SECONDS: float = 0.300


class InkyButtonHandler:
    """Listens for button presses on a Pimoroni Inky Impression panel via GPIO.

    All GPIO access is performed on a dedicated daemon thread.  The public
    API is safe to call on any platform — if ``gpiod`` is not installed,
    ``start()`` logs a warning and returns immediately.

    Args:
        eink_model: Value of ``display.eink_model`` from the app config.
            Used to select the correct GPIO pin for button C:
            ``inky_impression_13`` uses BCM25; all other models use BCM16.
    """

    def __init__(self, eink_model: str = "") -> None:
        self._last_press: dict[str, float] = {}
        if eink_model == "inky_impression_13":
            self._button_pins = _BUTTON_PINS_IMPRESSION_13
        else:
            self._button_pins = _BUTTON_PINS_DEFAULT
        self._pin_to_label: dict[int, str] = {v: k for k, v in self._button_pins.items()}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(
        self,
        callback: Callable[[str], None],
        stop_event: threading.Event,
    ) -> None:
        """Start the GPIO listener daemon thread.

        Args:
            callback: Called with the button label (``"A"``, ``"B"``,
                      ``"C"`` or ``"D"``) whenever a button press is
                      detected.  Invoked from the listener thread —
                      keep it short and thread-safe; offload heavy work.
            stop_event: When set, the listener thread exits within one
                        ``wait_edge_events`` timeout cycle (~100 ms).

        If ``gpiod`` is not available (non-RPi environment), logs a
        ``WARNING`` and returns immediately without starting any thread.
        """
        try:
            import gpiod  # noqa: F401 — availability check
        except ImportError:
            logger.warning(
                "InkyButtonHandler: gpiod non disponibile — "
                "gestione pulsanti fisici disabilitata."
            )
            return

        chip_path = self._find_chip()
        if chip_path is None:
            logger.warning(
                "InkyButtonHandler: nessun chip GPIO trovato in %s — "
                "gestione pulsanti fisici disabilitata.",
                _GPIO_CHIP_CANDIDATES,
            )
            return

        thread = threading.Thread(
            target=self._listen,
            args=(chip_path, callback, stop_event),
            daemon=True,
            name="inky-buttons",
        )
        thread.start()
        active_labels = ", ".join(
            f"{label}={pin}" for label, pin in self._button_pins.items()
        )
        logger.info(
            "InkyButtonHandler avviato su %s (%s).",
            chip_path,
            active_labels,
        )

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _find_chip(self) -> str | None:
        """Return the path of the first usable GPIO chip, or ``None``."""
        import gpiod

        for path in _GPIO_CHIP_CANDIDATES:
            try:
                with gpiod.Chip(path):
                    return path
            except (OSError, PermissionError):
                continue
        return None

    def _listen(
        self,
        chip_path: str,
        callback: Callable[[str], None],
        stop_event: threading.Event,
    ) -> None:
        """Main loop — runs on the daemon thread."""
        import gpiod
        from gpiod.line import Bias, Direction, Edge

        pins = tuple(self._button_pins.values())
        settings = gpiod.LineSettings(
            direction=Direction.INPUT,
            edge_detection=Edge.FALLING,
            bias=Bias.PULL_UP,
        )

        try:
            request = gpiod.request_lines(
                chip_path,
                consumer="family-planner-buttons",
                config={pins: settings},
            )
        except Exception:
            logger.exception(
                "InkyButtonHandler: impossibile aprire le linee GPIO su %s.", chip_path
            )
            return

        logger.debug("InkyButtonHandler: loop GPIO attivo.")
        try:
            while not stop_event.is_set():
                if request.wait_edge_events(timeout=timedelta(milliseconds=100)):
                    for event in request.read_edge_events():
                        label = self._pin_to_label.get(event.line_offset)
                        if label is not None and self._debounce(label):
                            logger.debug("InkyButtonHandler: pulsante %s premuto.", label)
                            try:
                                callback(label)
                            except Exception:
                                logger.exception(
                                    "InkyButtonHandler: errore nella callback per pulsante %s.",
                                    label,
                                )
        finally:
            try:
                request.release()
            except Exception:
                pass
            logger.debug("InkyButtonHandler: loop GPIO terminato.")

    def _debounce(self, label: str) -> bool:
        """Return ``True`` if the event should be processed (debounce check).

        Ignores events occurring within ``_DEBOUNCE_SECONDS`` of the
        previous accepted event for the same button.
        """
        now = time.monotonic()
        last = self._last_press.get(label, 0.0)
        if now - last < _DEBOUNCE_SECONDS:
            return False
        self._last_press[label] = now
        return True
