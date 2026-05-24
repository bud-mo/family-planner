"""Display drivers for Family Planner.

Available drivers:
- ``HdmiDisplay``: Chromium-based HDMI display driver (kiosk subprocess).
- ``EinkDisplay``: Waveshare e-ink panel driver (lazy hardware import).

Imports are intentionally lazy so that hardware-specific dependencies
(e.g. ``pygame``, ``RPi.GPIO``) are only loaded when the driver is actually used.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.display.eink import EinkDisplay
    from app.display.hdmi import HdmiDisplay

__all__ = ["HdmiDisplay", "EinkDisplay"]
