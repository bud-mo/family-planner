"""Physical button handler for Pimoroni Inky Impression panels.

``InkyButtonHandler`` listens for GPIO falling-edge events from the four
physical buttons of any Inky Impression panel (A=BCM5, B=BCM6, C=BCM16,
D=BCM24) and invokes a callback with the button label.

All four lines (A, B, C and D) are requested from the GPIO chip.  On every
model except the 13.3″, button **C** is BCM16, which the Inky driver also
uses as SPI CS1.  Acquiring line 16 alongside the others generally succeeds,
but if a particular board/kernel/overlay refuses it, ``_listen`` falls back
to requesting only A, B and D — so a CS1 conflict disables the slideshow
button only, never the planner/artwork/shutdown buttons.  On the 13.3″ model
button C is BCM25 (no conflict) and the first request always succeeds.

``resolve_button_roles`` maps the physical labels (A/B/C/D) to logical roles
for a given panel rotation; it is a pure function and lives here next to the
handler so the mapping can be unit-tested without GPIO.

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


def resolve_button_roles(rotation: int) -> dict[str, str]:
    """Map physical button labels (A/B/C/D) to logical roles for a rotation.

    Standard (0°/90°):    A=planner  B=artwork  C=slideshow  D=shutdown
    Inverted (180°/270°): A=shutdown C=artwork  B=slideshow  D=planner

    The 180° flip swaps A↔D and B↔C, so every role keeps the same *physical*
    button position regardless of mounting orientation.
    """
    inverted = rotation in (180, 270)
    return {
        "planner": "D" if inverted else "A",
        "artwork": "C" if inverted else "B",
        "slideshow": "B" if inverted else "C",
        "shutdown": "A" if inverted else "D",
    }


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

        settings = gpiod.LineSettings(
            direction=Direction.INPUT,
            edge_detection=Edge.FALLING,
            bias=Bias.PULL_UP,
        )

        # Try the full set first; on failure (typically a BCM16/SPI-CS1 conflict
        # on a non-13.3" board) retry without C so the slideshow button is the
        # only casualty — planner/artwork/shutdown keep working.
        pins_all = tuple(self._button_pins.values())
        c_pin = self._button_pins.get("C")
        pins_no_c = tuple(p for p in pins_all if p != c_pin)

        request = None
        for pins in (pins_all, pins_no_c):
            try:
                request = gpiod.request_lines(
                    chip_path,
                    consumer="family-planner-buttons",
                    config={pins: settings},
                )
                break
            except Exception:
                if pins is pins_all and pins_no_c != pins_all:
                    logger.warning(
                        "InkyButtonHandler: richiesta linee %s fallita — "
                        "riprovo senza C (BCM%s).",
                        pins,
                        c_pin,
                    )
                else:
                    logger.exception(
                        "InkyButtonHandler: impossibile aprire le linee GPIO su %s.",
                        chip_path,
                    )
        if request is None:
            return

        active_pins = set(pins)
        active = ", ".join(
            f"{lbl}={pin}"
            for lbl, pin in self._button_pins.items()
            if pin in active_pins
        )
        logger.info("InkyButtonHandler: pulsanti attivi: %s", active)

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
