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


def strip_instant_fields(weather: WeatherData) -> WeatherData:
    """Return *weather* without the fields that describe the present moment.

    Used for the frames rendered inside the quiet band (see
    ``RefreshPolicy.in_quiet_hours``). Those frames stay on the panel for hours
    — the one pushed at midnight survives until ``06:00`` — so any reading taken
    at push time silently rots: a temperature measured at midnight is wrong by
    dawn, and ``temp_max``/``temp_min`` describe a day that is barely under way.
    Dropping them is more honest than showing a stale number, and it is what
    keeps the panel from repainting whenever they drift.

    What survives is the bihourly forecast, which is *predictive* and therefore
    stays valid: the midnight frame carries the ``00:00``–``10:00`` windows and
    is still useful at breakfast.

    Idempotent — projecting an already-projected value returns it unchanged, so
    the e-ink loop and the renderer can both apply it without coordination.
    """
    if (
        weather.condition_icon is None
        and weather.description is None
        and weather.temp_current is None
        and weather.temp_max is None
        and weather.temp_min is None
    ):
        return weather
    return replace(
        weather,
        condition_icon=None,
        description=None,
        temp_current=None,
        temp_max=None,
        temp_min=None,
    )


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
