"""Abstract base class for weather data providers."""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.renderer.tokens import WeatherData


class WeatherProvider(ABC):
    """Returns current weather data for the configured location.

    Implementations must be thread-safe: ``get()`` may be called concurrently
    from the pygame render loop, the e-ink daemon thread, and FastAPI routes.
    """

    @abstractmethod
    def get(self) -> WeatherData:
        """Return the latest available weather data.

        Must never raise — return an empty ``WeatherData()`` on any error so
        that the renderer degrades gracefully (shows only the date).
        """
