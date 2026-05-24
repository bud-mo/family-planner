"""Weather data providers for Family Planner.

Exposes a single interface (WeatherProvider) and the default implementation
(OpenMeteoProvider) backed by the Open-Meteo public API (no API key required).
"""
from app.weather.open_meteo import OpenMeteoProvider
from app.weather.provider import WeatherProvider

__all__ = ["WeatherProvider", "OpenMeteoProvider"]
