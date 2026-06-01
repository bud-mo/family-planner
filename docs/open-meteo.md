# Open-Meteo - Integration in Family Planner

## Overview

Family Planner uses [Open-Meteo](https://open-meteo.com) as the default weather provider.
The service is **public, free, and API-keyless**, GDPR-compliant, with hourly updates.

The provider is implemented in `app/weather/open_meteo.py` and implements the `WeatherProvider` interface (`app/weather/provider.py`).

---

## API Endpoint

```text
GET https://api.open-meteo.com/v1/forecast
```

### Sent parameters

| Parameter          | Value                                         | Notes                                                   |
|--------------------|-----------------------------------------------|---------------------------------------------------------|
| `latitude`         | `<float>`                                     | Latitude from config (`weather.latitude`)               |
| `longitude`        | `<float>`                                     | Longitude from config (`weather.longitude`)             |
| `current`          | `temperature_2m,weather_code`                 | Current conditions                                      |
| `hourly`           | `temperature_2m,weather_code`                 | Hourly array for bi-hourly forecasts                    |
| `daily`            | `temperature_2m_max,temperature_2m_min`       | Daily max and min temperatures                          |
| `temperature_unit` | `celsius` (default) or `fahrenheit`           | Configurable via `weather.units`                        |
| `timezone`         | `auto`                                        | Automatically detected from coordinates                 |
| `forecast_days`    | `2`                                           | 48 hourly slots - required for late-day bi-hourly cells |

> `forecast_days=2` is mandatory: it guarantees that the 6 bi-hourly cells shown in the banner never exceed the array bounds, even in late afternoon/evening.

---

## Provider Architecture

```text
OpenMeteoProvider.get()
  └─ in-memory cache (TTL 3600 s)
       ├─ valid cache -> returns cached WeatherData
       └─ expired cache -> _fetch()
            ├─ HTTP GET -> JSON response
            ├─ _parse_hourly() -> 6x HourlySlot (bi-hourly)
            └─ WeatherData(condition_icon, description, temp_*, hourly_forecast)
```

### Cache

- **TTL**: 3600 seconds (1 hour) - aligned with Open-Meteo update frequency
- **Thread-safe**: uses `threading.Lock()` to protect reads and writes
- **Graceful degradation**: on network or parsing errors, the last valid cache is returned; if no data exists yet, an empty `WeatherData()` is returned (all fields `None`) and the banner shows only the date

### Returned data - `WeatherData`

| Field              | Type                | API Source                             |
|--------------------|---------------------|----------------------------------------|
| `condition_icon`   | `str \| None`       | `current.weather_code` -> `_WMO_TO_ICON` |
| `description`      | `str \| None`       | `current.weather_code` -> `_WMO_TO_DESC` |
| `temp_current`     | `float \| None`     | `current.temperature_2m`               |
| `temp_max`         | `float \| None`     | `daily.temperature_2m_max[0]`          |
| `temp_min`         | `float \| None`     | `daily.temperature_2m_min[0]`          |
| `hourly_forecast`  | `list[HourlySlot]`  | `hourly.*` -> `_parse_hourly()`        |

### Bi-hourly forecasts - `HourlySlot`

`_parse_hourly()` extracts 6 two-hour slots starting from the current time window:

- The current hour is rounded down to the nearest even number (example: 15:xx -> slot 14:00)
- Applied offsets are `+0, +2, +4, +6, +8, +10` hours
- With `forecast_days=2` (48 slots), out-of-range access cannot happen

---

## Configuration

In `config/config.yaml` (`weather` section):

```yaml
weather:
  provider: open_meteo
  latitude: 45.4654
  longitude: 9.1859
  units: celsius     # celsius | fahrenheit
```

---

## WMO 4677 Codes - Full Table

The `weather_code` values returned by the API follow the **WMO Weather Interpretation Codes (WMO 4677)** standard.
The table shows, for each code: official description, app-specific Italian description, and associated Tabler icon name.

| Code   | WMO Description (EN)                                     | IT Description (app)            | Tabler Icon          |
|-------:|----------------------------------------------------------|---------------------------------|----------------------|
| `0`    | Clear sky                                                | Sereno                          | `sun`                |
| `1`    | Mainly clear                                             | Prevalentemente sereno          | `sun`                |
| `2`    | Partly cloudy                                            | Parzialmente nuvoloso           | `cloud`              |
| `3`    | Overcast                                                 | Nuvoloso                        | `cloud`              |
| `45`   | Fog                                                      | Nebbia                          | `cloud`              |
| `48`   | Depositing rime fog                                      | Nebbia con brina                | `cloud`              |
| `51`   | Drizzle: light intensity                                 | Pioggerella                     | `cloud-rain`         |
| `53`   | Drizzle: moderate intensity                              | Pioggerella moderata            | `cloud-rain`         |
| `55`   | Drizzle: dense intensity                                 | Pioggerella intensa             | `cloud-rain`         |
| `56`   | Freezing drizzle: light intensity                        | Pioggerella gelata              | `snowflake`          |
| `57`   | Freezing drizzle: heavy intensity                        | Pioggerella gelata intensa      | `snowflake`          |
| `61`   | Rain: slight intensity                                   | Pioggia leggera                 | `cloud-rain`         |
| `63`   | Rain: moderate intensity                                 | Pioggia                         | `cloud-rain`         |
| `65`   | Rain: heavy intensity                                    | Pioggia intensa                 | `cloud-rain`         |
| `66`   | Freezing rain: light intensity                           | Pioggia gelata                  | `cloud-rain`         |
| `67`   | Freezing rain: heavy intensity                           | Pioggia gelata intensa          | `cloud-rain`         |
| `71`   | Snow fall: slight intensity                              | Neve leggera                    | `snowflake`          |
| `73`   | Snow fall: moderate intensity                            | Neve                            | `snowflake`          |
| `75`   | Snow fall: heavy intensity                               | Neve intensa                    | `snowflake`          |
| `77`   | Snow grains                                              | Granelli di neve                | `snowflake`          |
| `80`   | Rain showers: slight intensity                           | Rovesci                         | `cloud-rain`         |
| `81`   | Rain showers: moderate intensity                         | Rovesci moderati                | `cloud-rain`         |
| `82`   | Rain showers: violent intensity                          | Rovesci intensi                 | `cloud-rain`         |
| `85`   | Snow showers: slight intensity                           | Rovesci di neve                 | `snowflake`          |
| `86`   | Snow showers: heavy intensity                            | Rovesci di neve intensi         | `snowflake`          |
| `95`   | Thunderstorm: slight or moderate                         | Temporale                       | `cloud-rain`         |
| `96`   | Thunderstorm with slight hail                            | Temporale con grandine          | `cloud-rain`         |
| `99`   | Thunderstorm with heavy hail                             | Temporale con grandine intensa  | `cloud-rain`         |

> Codes not listed in the table (for example, 2x and 4x values other than 45/48) are not returned by Open-Meteo and have no mapping.
> An unknown code produces `condition_icon = None` and `description = None`, so the banner has no icon/description but still works.

---

## Python Dependencies

| Library      | Usage                                  |
|--------------|----------------------------------------|
| `requests`   | HTTP GET to the Open-Meteo API         |
| `threading`  | Lock for thread-safe cache             |
| `datetime`   | Current time-slot calculation          |

`requests` is the only external dependency; it is already in `requirements.txt`.