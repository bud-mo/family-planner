"""Display drivers for Family Planner.

Available drivers:
- ``EinkDisplay``: Waveshare e-ink panel driver (lazy hardware import).
- ``InkyDisplay``: Pimoroni Inky Impression driver (lazy hardware import).

Imports are intentionally lazy so that hardware-specific dependencies
(e.g. ``waveshare_epd``, ``inky``, ``gpiod``) are only loaded when the
driver is actually used.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.display.eink import EinkDisplay, InkyDisplay

__all__ = ["EinkDisplay", "InkyDisplay"]
