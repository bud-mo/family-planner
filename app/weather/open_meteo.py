"""Open-Meteo weather provider with in-memory TTL cache.

Uses the Open-Meteo public API (https://api.open-meteo.com) — no API key
required, GDPR-compliant, updates available every hour.

API endpoint:
    GET https://api.open-meteo.com/v1/forecast
    ?latitude=<lat>&longitude=<lon>
    &current=temperature_2m,weather_code
    &hourly=temperature_2m,weather_code
    &daily=temperature_2m_max,temperature_2m_min
    &temperature_unit=celsius
    &timezone=auto
    &forecast_days=2

The response ``current.weather_code`` follows WMO Weather Interpretation Codes
(WMO 4677). These are mapped to Tabler icon names and Italian descriptions as
defined in docs/design.md.

``forecast_days=2`` (48 hourly slots) is required so that the 6 bihourly
forecast cells never overflow past the end of today's data.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime

import requests

from app.renderer.tokens import HourlySlot, WeatherData
from app.weather.provider import WeatherProvider

logger = logging.getLogger(__name__)

_OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
_CACHE_TTL: int = 3600  # seconds — refresh at most once per hour

# ---------------------------------------------------------------------------
# WMO 4677 weather code → Tabler icon name (subset used in design.md)
# ---------------------------------------------------------------------------
_WMO_TO_ICON: dict[int, str] = {
    0: "sun",
    1: "sun",
    2: "cloud",
    3: "cloud",
    45: "cloud",
    48: "cloud",
    51: "cloud-rain",
    53: "cloud-rain",
    55: "cloud-rain",
    56: "snowflake",
    57: "snowflake",
    61: "cloud-rain",
    63: "cloud-rain",
    65: "cloud-rain",
    66: "cloud-rain",
    67: "cloud-rain",
    71: "snowflake",
    73: "snowflake",
    75: "snowflake",
    77: "snowflake",
    80: "cloud-rain",
    81: "cloud-rain",
    82: "cloud-rain",
    85: "snowflake",
    86: "snowflake",
    95: "cloud-rain",
    96: "cloud-rain",
    99: "cloud-rain",
}

# ---------------------------------------------------------------------------
# WMO 4677 weather code → Italian human-readable description
# ---------------------------------------------------------------------------
_WMO_TO_DESC: dict[int, str] = {
    0: "Sereno",
    1: "Prevalentemente sereno",
    2: "Parzialmente nuvoloso",
    3: "Nuvoloso",
    45: "Nebbia",
    48: "Nebbia con brina",
    51: "Pioggerella",
    53: "Pioggerella moderata",
    55: "Pioggerella intensa",
    56: "Pioggerella gelata",
    57: "Pioggerella gelata intensa",
    61: "Pioggia leggera",
    63: "Pioggia",
    65: "Pioggia intensa",
    66: "Pioggia gelata",
    67: "Pioggia gelata intensa",
    71: "Neve leggera",
    73: "Neve",
    75: "Neve intensa",
    77: "Granelli di neve",
    80: "Rovesci",
    81: "Rovesci moderati",
    82: "Rovesci intensi",
    85: "Rovesci di neve",
    86: "Rovesci di neve intensi",
    95: "Temporale",
    96: "Temporale con grandine",
    99: "Temporale con grandine intensa",
}


class OpenMeteoProvider(WeatherProvider):
    """Fetches current conditions from the Open-Meteo API.

    Results are cached in-memory for ``_CACHE_TTL`` seconds (1 hour).
    On fetch or parse errors the last known data is returned; if no data has
    ever been fetched successfully an empty ``WeatherData()`` is returned so
    the renderer degrades gracefully to showing the date only.

    Args:
        latitude: Geographic latitude of the target location.
        longitude: Geographic longitude of the target location.
        units: Temperature unit — ``"celsius"`` (default) or ``"fahrenheit"``.
    """

    def __init__(
        self,
        latitude: float,
        longitude: float,
        units: str = "celsius",
    ) -> None:
        self._latitude = latitude
        self._longitude = longitude
        self._units = units
        self._lock = threading.Lock()
        self._cached: WeatherData | None = None
        self._cached_at: float = 0.0

    def get(self) -> WeatherData:
        """Return cached or freshly-fetched weather data (never raises)."""
        with self._lock:
            if (
                self._cached is not None
                and time.monotonic() - self._cached_at < _CACHE_TTL
            ):
                return self._cached

        # Fetch outside the lock so other threads are not blocked during the
        # HTTP request.
        fresh = self._fetch()

        with self._lock:
            if fresh is not None:
                self._cached = fresh
                self._cached_at = time.monotonic()
            return self._cached if self._cached is not None else WeatherData()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch(self) -> WeatherData | None:
        """Perform the HTTP call and parse the response.

        Returns ``None`` on any error so the caller keeps the stale cache.
        """
        params: dict[str, object] = {
            "latitude": self._latitude,
            "longitude": self._longitude,
            "current": "temperature_2m,weather_code",
            "hourly": "temperature_2m,weather_code",
            "daily": "temperature_2m_max,temperature_2m_min",
            "temperature_unit": self._units,
            "timezone": "auto",
            "forecast_days": 2,
        }
        try:
            resp = requests.get(_OPEN_METEO_URL, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            logger.warning("OpenMeteoProvider: fetch failed: %s", exc)
            return None

        try:
            current = data["current"]
            daily = data["daily"]
            code = int(current["weather_code"])
            hourly_forecast = self._parse_hourly(data.get("hourly", {}))
            return WeatherData(
                condition_icon=_WMO_TO_ICON.get(code),
                description=_WMO_TO_DESC.get(code),
                temp_current=float(current["temperature_2m"]),
                temp_max=float(daily["temperature_2m_max"][0]),
                temp_min=float(daily["temperature_2m_min"][0]),
                hourly_forecast=hourly_forecast,
            )
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            logger.warning("OpenMeteoProvider: response parse error: %s", exc)
            return None

    @staticmethod
    def _parse_hourly(hourly: dict) -> list[HourlySlot]:
        """Extract 6 bihourly forecast slots starting from the current 2-hour window.

        The hourly arrays from Open-Meteo contain one entry per hour, indexed
        from midnight of today (index 0 = 00:00, index H = H:00). With
        ``forecast_days=2`` we have 48 entries covering tomorrow as well, so
        the 6 slots never overflow even at 23:xx.
        """
        temps = hourly.get("temperature_2m", [])
        codes = hourly.get("weather_code", [])
        if not temps or not codes:
            return []

        current_hour = datetime.now().hour
        slot_start = (current_hour // 2) * 2  # round down to nearest even hour

        slots: list[HourlySlot] = []
        for offset in range(0, 12, 2):  # 0, 2, 4, 6, 8, 10 — 6 slots
            idx = slot_start + offset
            try:
                temp = float(temps[idx])
                icon = _WMO_TO_ICON.get(int(codes[idx]))
            except (IndexError, TypeError, ValueError):
                temp = None
                icon = None
            slots.append(HourlySlot(hour=idx % 24, condition_icon=icon, temp=temp))
        return slots
