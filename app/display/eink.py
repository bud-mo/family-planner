"""E-ink display driver for Family Planner.

``EinkDisplay`` is safe to import on any platform — the Waveshare hardware
libraries are loaded lazily inside ``push()``, guarded by a try/except
``ImportError``.  On macOS or Linux without the Waveshare package the module
imports cleanly and ``push()`` raises ``RuntimeError`` only when actually
called.

Usage (typical):
    from app.renderer.pillow_eink_renderer import PillowEinkRenderer
    from app.renderer.eink_renderer import EinkRenderer

    pillow_renderer = PillowEinkRenderer(config, weather_provider)
    eink_renderer = EinkRenderer(config.display)
    display = EinkDisplay(config.display)

    image = pillow_renderer.render(state, events)
    processed = eink_renderer.process(image)
    display.push(processed)
    display.stop()
"""
from __future__ import annotations

import importlib
import logging
import threading
import time
from typing import Any

from PIL import Image

from app.config import DisplayConfig

logger = logging.getLogger(__name__)

# Map eink_model values to Waveshare EPD module names.
# The pattern is: model string prepended with "epd" gives the module attribute
# name inside the waveshare_epd package (e.g. "7in5_V2" → "epd7in5_V2").
_MODEL_TO_MODULE: dict[str, str] = {
    "7in5_V2":   "epd7in5_V2",
    "7in5":      "epd7in5",
    "4in2":      "epd4in2",
    "4in2_V2":   "epd4in2_V2",
    "2in13":     "epd2in13",
    "2in13_V2":  "epd2in13_V2",
    "2in13_V3":  "epd2in13_V3",
    "1in54":     "epd1in54",
    "1in54_V2":  "epd1in54_V2",
    "5in83":     "epd5in83",
    "5in83_V2":  "epd5in83_V2",
    "3in7":      "epd3in7",
    "2in7":      "epd2in7",
}


def panel_available() -> bool:
    """Return True when running on a Raspberry Pi (where an e-ink panel can drive).

    Used by the entry point to decide between the e-ink push loop and
    web-server-only mode.  Detection reads ``/proc/device-tree/model``; on a
    development machine (macOS / non-Pi Linux) the file is absent and this
    returns False, so the app serves only the browser preview instead of
    spinning an e-ink loop that would fail on every push.
    """
    try:
        from pathlib import Path

        model = Path("/proc/device-tree/model").read_text(errors="ignore")
    except OSError:
        return False
    return "raspberry pi" in model.lower()


class EinkDisplay:
    """Pushes a composed ``PIL.Image`` to a Waveshare e-ink panel."""

    def __init__(self, config: DisplayConfig) -> None:
        self._config = config
        self._epd: Any | None = None  # lazily loaded Waveshare EPD instance

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def push(self, image: Image.Image) -> None:
        """Send *image* to the e-ink panel.

        Sequence: initialise → clear → display → sleep.

        Args:
            image: A ``PIL.Image`` already post-processed by ``EinkRenderer``
                   (correct resolution and palette for the target panel).

        Raises:
            RuntimeError: If the Waveshare driver library is not installed.
        """
        epd = self._load_driver()
        try:
            logger.info("EinkDisplay: initialising panel %s", self._config.eink_model)
            epd.init()
            epd.Clear()
            epd.display(epd.getbuffer(image))
            logger.info("EinkDisplay: image pushed — entering sleep")
            epd.sleep()
        except Exception:
            logger.exception("EinkDisplay: error during push to panel %s",
                             self._config.eink_model)
            raise

    def stop(self) -> None:
        """Put the panel to sleep if a driver has been loaded.

        Safe to call even if ``push()`` was never called (no-op in that case).
        """
        if self._epd is not None:
            try:
                self._epd.sleep()
                logger.info("EinkDisplay: panel %s put to sleep", self._config.eink_model)
            except Exception:
                logger.exception("EinkDisplay: error putting panel to sleep")

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _load_driver(self) -> Any:
        """Dynamically import and instantiate the Waveshare EPD driver.

        The import is deferred to this method so that the module can be
        imported on any platform without raising ``ImportError``.

        Returns:
            An initialised Waveshare EPD object.

        Raises:
            RuntimeError: If the waveshare_epd package is not installed or
                          the model name is unrecognised.
        """
        if self._epd is not None:
            return self._epd

        model = self._config.eink_model
        module_name = _MODEL_TO_MODULE.get(model)
        if module_name is None:
            raise RuntimeError(
                f"EinkDisplay: unknown eink_model {model!r}. "
                f"Supported models: {', '.join(_MODEL_TO_MODULE)}"
            )

        try:
            module = importlib.import_module(f"waveshare_epd.{module_name}")
        except ImportError as exc:
            raise RuntimeError(
                f"EinkDisplay: Waveshare driver for model {model!r} could not be "
                f"imported (waveshare_epd.{module_name}). "
                "Install the waveshare-epaper package on the target Raspberry Pi."
            ) from exc

        try:
            epd_class = getattr(module, "EPD")
        except AttributeError as exc:
            raise RuntimeError(
                f"EinkDisplay: waveshare_epd.{module_name} has no 'EPD' class."
            ) from exc

        self._epd = epd_class()
        logger.debug("EinkDisplay: loaded driver waveshare_epd.%s", module_name)
        return self._epd


class InkyDisplay:
    """Pushes a composed ``PIL.Image`` to a Pimoroni Inky e-ink panel.

    Uses the ``inky`` Python library (``pip install inky``) which must be
    installed on the Raspberry Pi.  On macOS/Linux without the library the
    module imports cleanly; ``push()`` raises ``RuntimeError`` only when
    actually called.

    Supported models (via ``eink_model``): ``inky_impression_4``,
    ``inky_impression_7``, ``inky_impression_13``.  The display is
    auto-detected at runtime via its onboard EEPROM.
    """

    def __init__(self, config: DisplayConfig) -> None:
        self._config = config
        self._inky: Any | None = None
        self._push_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def push(self, image: Image.Image) -> None:
        """Send *image* to the Inky panel.

        Follows the official Pimoroni example: ``set_image(image)`` then ``show()``.
        Accepts a palette-mode (``"P"``) image as returned by ``EinkRenderer``
        with ``spectra6`` palette, or an ``"RGB"`` image — the Inky library handles
        both.  If the image size does not match the hardware-reported panel
        dimensions it is resized automatically before display.

        Args:
            image: A ``PIL.Image`` in ``"P"`` or ``"RGB"`` mode.

        Raises:
            RuntimeError: If the inky library is not installed or the display
                          cannot be auto-detected.
        """
        inky = self._load_driver()

        target_size = (inky.width, inky.height)
        if image.size != target_size:
            logger.warning(
                "InkyDisplay: image size %s does not match panel %s — resizing",
                image.size,
                target_size,
            )
            # Palette images cannot be scaled with LANCZOS directly; convert
            # through RGB first.  The Inky library handles RGB colour mapping.
            rgb = image.convert("RGB")
            image = rgb.resize(target_size, Image.Resampling.LANCZOS)

        with self._push_lock:
            try:
                logger.info("InkyDisplay: pushing image to panel %s", self._config.eink_model)
                if self._config.eink_model == "inky_impression_13":
                    # Inky 2.4.0 (inky_el133uf1.py) has a bug in _busy_wait():
                    #
                    #   while self._gpio.get_value(self.busy_pin) == Value.ACTIVE:
                    #
                    # The EL133UF1 asserts BUSY LOW (Value.INACTIVE) during
                    # operations (active-low, open-drain with pull-up).  The
                    # while-loop condition is therefore NEVER true when the panel
                    # is busy, so _busy_wait() returns immediately — POF is sent
                    # right after DRF and the ACeP refresh is cut short before
                    # the display pixels update.
                    #
                    # Fix: replace _busy_wait() on the instance with a correct
                    # implementation:
                    #   • BUSY=HIGH at call time → race condition / panel idle →
                    #     sleep for full timeout (library's own safe-fallback logic).
                    #   • BUSY=LOW at call time → panel busy → loop until HIGH.
                    _original_busy_wait = inky._busy_wait
                    try:
                        from gpiod.line import Value as _GpioValue
                        _BUSY_INACTIVE = _GpioValue.INACTIVE  # LOW  = panel busy
                        _BUSY_ACTIVE = _GpioValue.ACTIVE      # HIGH = panel ready
                    except ImportError:
                        # dev environment without gpiod — use integer equivalents
                        _BUSY_INACTIVE = 0
                        _BUSY_ACTIVE = 1

                    def _safe_busy_wait(timeout: float = 40.0) -> None:  # noqa: ANN001
                        if inky._gpio.get_value(inky.busy_pin) == _BUSY_ACTIVE:
                            # BUSY=HIGH: panel not yet signalling busy (race
                            # condition) or genuinely idle.  Sleep conservatively.
                            time.sleep(timeout)
                            return
                        # BUSY=LOW: panel is actively busy.  Wait for HIGH.
                        _t0 = time.monotonic()
                        while inky._gpio.get_value(inky.busy_pin) == _BUSY_INACTIVE:
                            time.sleep(0.1)
                            if time.monotonic() - _t0 > timeout:
                                logger.warning(
                                    "InkyDisplay: _busy_wait timed out after %.1fs",
                                    time.monotonic() - _t0,
                                )
                                return

                    inky._busy_wait = _safe_busy_wait
                    try:
                        _t_show = time.monotonic()
                        try:
                            inky.set_image(image, saturation=self._config.eink_saturation)
                        except TypeError:
                            inky.set_image(image)
                        inky.show()
                        _push_secs = time.monotonic() - _t_show
                        if _push_secs < 25.0:
                            logger.warning(
                                "InkyDisplay: show() completed in %.1fs — "
                                "expected ≥25s for ACeP refresh; "
                                "BUSY pin fix may not be working correctly.",
                                _push_secs,
                            )
                        else:
                            logger.info(
                                "InkyDisplay: ACeP refresh completed in %.1fs.", _push_secs
                            )
                    finally:
                        # Restore original method so subsequent calls are unaffected.
                        try:
                            del inky._busy_wait
                        except AttributeError:
                            inky._busy_wait = _original_busy_wait
                else:
                    try:
                        inky.set_image(image, saturation=self._config.eink_saturation)
                    except TypeError:
                        inky.set_image(image)
                    inky.show()
                logger.info("InkyDisplay: image pushed successfully")
            except Exception:
                logger.exception(
                    "InkyDisplay: error during push to panel %s", self._config.eink_model
                )
                raise

    def stop(self) -> None:
        """No-op — the Inky library handles display sleep internally."""

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _load_driver(self) -> Any:
        """Lazily import and initialise the Pimoroni Inky driver via auto-detect.

        Returns:
            An initialised Inky display object.

        Raises:
            RuntimeError: If the ``inky`` package is not installed or the
                          display cannot be auto-detected via EEPROM.
        """
        if self._inky is not None:
            return self._inky

        try:
            from inky.auto import auto  # type: ignore[import]
        except ImportError as exc:
            raise RuntimeError(
                "InkyDisplay: inky library not installed. "
                "Run: pip install inky  on the Raspberry Pi."
            ) from exc

        try:
            self._inky = auto()
        except Exception as exc:
            raise RuntimeError(
                f"InkyDisplay: failed to auto-detect Inky display: {exc}. "
                "Ensure the display is connected and its EEPROM is readable."
            ) from exc

        logger.debug("InkyDisplay: auto-detected Inky display (%s)", self._config.eink_model)
        return self._inky
