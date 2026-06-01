"""Unit tests for the weather provider's stale-cache handling.

Covers two behaviours introduced to fix the UX bug where, after a failed
Open-Meteo fetch, the e-ink panel kept showing a forecast cell for a time slot
that had already passed (e.g. ``22:00`` just after midnight):

  * :func:`drop_past_hourly_slots` removes already-elapsed bihourly slots from
    cached data so the first cell is always the current 2-hour window;
  * :attr:`OpenMeteoProvider.last_fetch_failed` flags a failed fetch so the
    e-ink loop can retry at the next quarter-hour tick instead of waiting a
    full hour.
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

from app.renderer.tokens import HourlySlot, WeatherData
from app.weather.open_meteo import OpenMeteoProvider
from app.weather.provider import drop_past_hourly_slots


def _slots(*hours: int) -> list[HourlySlot]:
    """Build forecast slots with deterministic, hour-derived temps."""
    return [HourlySlot(hour=h, condition_icon="sun", temp=float(h)) for h in hours]


def _weather(*hours: int) -> WeatherData:
    return WeatherData(
        condition_icon="sun",
        description="Sereno",
        temp_current=20.0,
        temp_max=25.0,
        temp_min=15.0,
        hourly_forecast=_slots(*hours),
    )


class TestDropPastHourlySlots:
    def test_drops_elapsed_leading_slot_after_midnight(self) -> None:
        """The reported bug: cache fetched at 23:00, now 00:00 — drop the 22:00 cell."""
        weather = _weather(22, 0, 2, 4, 6, 8)

        result = drop_past_hourly_slots(weather, datetime(2026, 6, 2, 0, 0))

        assert [s.hour for s in result.hourly_forecast] == [0, 2, 4, 6, 8]
        # Remaining slots keep their data; non-hourly fields are untouched.
        assert result.hourly_forecast[0].temp == 0.0
        assert result.temp_current == 20.0

    def test_noop_when_first_slot_is_current_window(self) -> None:
        """Fresh data (first slot == current window) is returned unchanged."""
        weather = _weather(0, 2, 4, 6, 8, 10)

        result = drop_past_hourly_slots(weather, datetime(2026, 6, 2, 0, 45))

        assert result is weather  # identity: no copy made

    def test_current_window_is_the_one_containing_now(self) -> None:
        """23:30 still belongs to the 22:00 window — nothing is dropped."""
        weather = _weather(22, 0, 2, 4, 6, 8)

        result = drop_past_hourly_slots(weather, datetime(2026, 6, 1, 23, 30))

        assert result is weather

    def test_drops_multiple_elapsed_slots(self) -> None:
        weather = _weather(0, 2, 4, 6, 8, 10)

        result = drop_past_hourly_slots(weather, datetime(2026, 6, 2, 6, 15))

        assert [s.hour for s in result.hourly_forecast] == [6, 8, 10]

    def test_clears_forecast_when_all_slots_elapsed(self) -> None:
        """Cache so stale that no slot covers the current window — strip is omitted."""
        weather = _weather(0, 2, 4, 6, 8, 10)

        result = drop_past_hourly_slots(weather, datetime(2026, 6, 2, 14, 0))

        assert result.hourly_forecast == []
        # Current conditions are still preserved for the main banner.
        assert result.temp_current == 20.0

    def test_empty_forecast_passthrough(self) -> None:
        weather = WeatherData(temp_current=20.0)

        result = drop_past_hourly_slots(weather, datetime(2026, 6, 2, 0, 0))

        assert result is weather

    def test_does_not_mutate_input(self) -> None:
        weather = _weather(22, 0, 2, 4, 6, 8)

        drop_past_hourly_slots(weather, datetime(2026, 6, 2, 0, 0))

        assert [s.hour for s in weather.hourly_forecast] == [22, 0, 2, 4, 6, 8]


class TestLastFetchFailed:
    def test_failed_fetch_serves_filtered_cache_and_flags_retry(self) -> None:
        provider = OpenMeteoProvider(latitude=45.0, longitude=9.0)

        # 1) First fetch succeeds — populate the cache with a 23:00-anchored forecast.
        cached = _weather(22, 0, 2, 4, 6, 8)
        with patch.object(provider, "_fetch", return_value=cached):
            provider.get(force=True)
        assert provider.last_fetch_failed is False

        # 2) Next fetch fails — stale cache is served, with the elapsed 22:00 slot
        #    dropped, and the failure is flagged so the loop retries next tick.
        with patch.object(provider, "_fetch", return_value=None), patch(
            "app.weather.open_meteo.datetime"
        ) as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 2, 0, 0)
            result = provider.get(force=True)

        assert provider.last_fetch_failed is True
        assert [s.hour for s in result.hourly_forecast] == [0, 2, 4, 6, 8]

    def test_flag_clears_after_successful_retry(self) -> None:
        provider = OpenMeteoProvider(latitude=45.0, longitude=9.0)

        with patch.object(provider, "_fetch", return_value=None):
            provider.get(force=True)
        assert provider.last_fetch_failed is True

        with patch.object(provider, "_fetch", return_value=_weather(0, 2, 4, 6, 8, 10)):
            provider.get(force=True)
        assert provider.last_fetch_failed is False

    def test_empty_weather_when_never_fetched(self) -> None:
        """A failure with no prior cache degrades to an empty banner, not a crash."""
        provider = OpenMeteoProvider(latitude=45.0, longitude=9.0)

        with patch.object(provider, "_fetch", return_value=None):
            result = provider.get(force=True)

        assert result == WeatherData()
        assert provider.last_fetch_failed is True
