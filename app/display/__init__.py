"""Display drivers for Family Planner.

Available drivers:
- ``HdmiDisplay``: pygame-based HDMI window driver.
- ``EinkDisplay``: Waveshare e-ink panel driver (lazy hardware import).
"""
from app.display.eink import EinkDisplay
from app.display.hdmi import HdmiDisplay

__all__ = ["HdmiDisplay", "EinkDisplay"]
