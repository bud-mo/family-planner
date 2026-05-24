"""E-ink display driver for Family Planner.

``EinkDisplay`` is safe to import on any platform — the Waveshare hardware
libraries are loaded lazily inside ``push()``, guarded by a try/except
``ImportError``.  On macOS or Linux without the Waveshare package the module
imports cleanly and ``push()`` raises ``RuntimeError`` only when actually
called (satisfying acceptance criterion #10).

Usage (typical):
    renderer = PlaywrightRenderer(config, aggregator)
    eink_renderer = EinkRenderer(config.display)
    display = EinkDisplay(config.display)

    renderer.start(port=8080)
    image = renderer.screenshot()
    processed = eink_renderer.process(image)
    display.push(processed)
    display.stop()
"""
from __future__ import annotations

import importlib
import logging
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
