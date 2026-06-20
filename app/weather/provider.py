"""Abstract base class for weather data providers."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import replace
from datetime import datetime

from app.renderer.tokens import WeatherData


def drop_past_hourly_slots(weather: WeatherData, now: datetime) -> WeatherData:
    """Return *weather* with already-elapsed bihourly forecast slots removed.

    Each slot describes a 2-hour window anchored to an even hour *at the moment
    the data was fetched* (see ``OpenMeteoProvider._parse_hourly``). When stale
    cached data is served — typically because the latest fetch failed — the
    leading slots may describe windows that have already elapsed, e.g. showing a
    ``22:00`` cell just after midnight.

    This drops every leading slot whose window precedes the one containing
    *now*, so the first cell shown is always the current bihourly window. Slots
    store ``hour`` modulo 24 and therefore wrap across midnight, so we locate the
    slot matching the current window (``(now.hour // 2) * 2``) and slice from
    there. If no slot matches — the cache is so stale that every window has
    elapsed — the forecast is cleared and the renderer simply omits the strip.

    Fresh data is unaffected: its first slot already is the current window, so
    the result is identical to the input.
    """
    if not weather.hourly_forecast:
        return weather

    current_window = (now.hour // 2) * 2
    for i, slot in enumerate(weather.hourly_forecast):
        if slot.hour == current_window:
            return weather if i == 0 else replace(
                weather, hourly_forecast=weather.hourly_forecast[i:]
            )

    # Current window not represented — every cached slot has already elapsed.
    return replace(weather, hourly_forecast=[])


class WeatherProvider(ABC):
    """Returns current weather data for the configured location.

    Implementations must be thread-safe: ``get()`` may be called concurrently
    from the e-ink daemon thread and FastAPI routes.
    """

    @abstractmethod
    def get(self, force: bool = False) -> WeatherData:
        """Return the latest available weather data.

        With *force* True the implementation bypasses its TTL cache and fetches
        fresh data (used at the hourly tick and on a manual refresh).

        Must never raise — return an empty ``WeatherData()`` on any error so
        that the renderer degrades gracefully (shows only the date).
        """

    @property
    def last_fetch_failed(self) -> bool:
        """True if the most recent fetch *attempt* failed and stale/empty data is served.

        Consumers use this to retry sooner (at the next quarter-hour tick)
        instead of waiting for the next scheduled hourly fetch. Providers that
        never reach the network may leave the default (always ``False``).
        """
        return False
