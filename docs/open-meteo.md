# Open-Meteo — Integrazione nel Family Planner

## Panoramica

Family Planner usa [Open-Meteo](https://open-meteo.com) come provider meteo predefinito.  
Il servizio è **pubblico, gratuito e senza chiave API**, GDPR-compliant, con aggiornamenti ogni ora.

Il provider è implementato in `app/weather/open_meteo.py` e implementa l'interfaccia `WeatherProvider` (`app/weather/provider.py`).

---

## Endpoint API

```
GET https://api.open-meteo.com/v1/forecast
```

### Parametri inviati

| Parametro          | Valore                                        | Note                                                   |
|--------------------|-----------------------------------------------|--------------------------------------------------------|
| `latitude`         | `<float>`                                     | Latitudine dal config (`weather.latitude`)             |
| `longitude`        | `<float>`                                     | Longitudine dal config (`weather.longitude`)           |
| `current`          | `temperature_2m,weather_code`                 | Condizioni attuali                                     |
| `hourly`           | `temperature_2m,weather_code`                 | Array orario per le previsioni biorarie                |
| `daily`            | `temperature_2m_max,temperature_2m_min`       | Massima e minima giornaliere                           |
| `temperature_unit` | `celsius` (default) o `fahrenheit`            | Configurabile via `weather.units`                      |
| `timezone`         | `auto`                                        | Rilevato automaticamente dalle coordinate              |
| `forecast_days`    | `2`                                           | 48 slot orari — necessari per le fasce biorarie serali |

> `forecast_days=2` è obbligatorio: garantisce che le 6 celle biorarie mostrate nel banner non eccedano mai l'array anche a tardo pomeriggio/sera.

---

## Architettura del provider

```
OpenMeteoProvider.get()
  └─ cache in-memory (TTL 3600 s)
       ├─ cache valida → restituisce WeatherData cached
       └─ cache scaduta → _fetch()
            ├─ HTTP GET → risposta JSON
            ├─ _parse_hourly() → 6× HourlySlot (biorari)
            └─ WeatherData(condition_icon, description, temp_*, hourly_forecast)
```

### Cache

- **TTL**: 3600 secondi (1 ora) — allineato alla frequenza di aggiornamento di Open-Meteo
- **Thread-safe**: usa `threading.Lock()` per proteggere lettura e scrittura
- **Graceful degradation**: in caso di errore di rete o parsing, viene restituita l'ultima cache valida; se non esiste ancora nessun dato, viene restituito un `WeatherData()` vuoto (tutti i campi `None`) e il banner mostra solo la data

### Dati restituiti — `WeatherData`

| Campo               | Tipo                | Sorgente API                           |
|---------------------|---------------------|----------------------------------------|
| `condition_icon`    | `str \| None`       | `current.weather_code` → `_WMO_TO_ICON`  |
| `description`       | `str \| None`       | `current.weather_code` → `_WMO_TO_DESC`  |
| `temp_current`      | `float \| None`     | `current.temperature_2m`               |
| `temp_max`          | `float \| None`     | `daily.temperature_2m_max[0]`          |
| `temp_min`          | `float \| None`     | `daily.temperature_2m_min[0]`          |
| `hourly_forecast`   | `list[HourlySlot]`  | `hourly.*` → `_parse_hourly()`         |

### Previsioni biorarie — `HourlySlot`

`_parse_hourly()` estrae 6 fasce da 2 ore a partire dalla finestra oraria corrente:

- L'ora corrente viene arrotondata al numero pari più vicino (es. 15:xx → slot 14:00)
- Gli offset applicati sono `+0, +2, +4, +6, +8, +10` ore
- Con `forecast_days=2` (48 slot) non si può mai andare fuori range

---

## Configurazione

In `config/config.yaml` (sezione `weather`):

```yaml
weather:
  provider: open_meteo
  latitude: 45.4654
  longitude: 9.1859
  units: celsius     # celsius | fahrenheit
```

---

## Codici WMO 4677 — Tabella completa

I codici `weather_code` restituiti dall'API seguono lo standard **WMO Weather Interpretation Codes (WMO 4677)**.  
La tabella riporta per ogni codice: la descrizione ufficiale, la descrizione italiana usata nell'app, e il nome dell'icona Tabler associata.

| Codice | Descrizione WMO (EN)                                      | Descrizione IT (app)           | Icona Tabler         |
|-------:|-----------------------------------------------------------|--------------------------------|----------------------|
| `0`    | Clear sky                                                 | Sereno                         | `sun`                |
| `1`    | Mainly clear                                              | Prevalentemente sereno         | `sun`                |
| `2`    | Partly cloudy                                             | Parzialmente nuvoloso          | `cloud`              |
| `3`    | Overcast                                                  | Nuvoloso                       | `cloud`              |
| `45`   | Fog                                                       | Nebbia                         | `cloud`              |
| `48`   | Depositing rime fog                                       | Nebbia con brina               | `cloud`              |
| `51`   | Drizzle: light intensity                                  | Pioggerella                    | `cloud-rain`         |
| `53`   | Drizzle: moderate intensity                               | Pioggerella moderata           | `cloud-rain`         |
| `55`   | Drizzle: dense intensity                                  | Pioggerella intensa            | `cloud-rain`         |
| `56`   | Freezing drizzle: light intensity                         | Pioggerella gelata             | `snowflake`          |
| `57`   | Freezing drizzle: heavy intensity                         | Pioggerella gelata intensa     | `snowflake`          |
| `61`   | Rain: slight intensity                                    | Pioggia leggera                | `cloud-rain`         |
| `63`   | Rain: moderate intensity                                  | Pioggia                        | `cloud-rain`         |
| `65`   | Rain: heavy intensity                                     | Pioggia intensa                | `cloud-rain`         |
| `66`   | Freezing rain: light intensity                            | Pioggia gelata                 | `cloud-rain`         |
| `67`   | Freezing rain: heavy intensity                            | Pioggia gelata intensa         | `cloud-rain`         |
| `71`   | Snow fall: slight intensity                               | Neve leggera                   | `snowflake`          |
| `73`   | Snow fall: moderate intensity                             | Neve                           | `snowflake`          |
| `75`   | Snow fall: heavy intensity                                | Neve intensa                   | `snowflake`          |
| `77`   | Snow grains                                               | Granelli di neve               | `snowflake`          |
| `80`   | Rain showers: slight intensity                            | Rovesci                        | `cloud-rain`         |
| `81`   | Rain showers: moderate intensity                          | Rovesci moderati               | `cloud-rain`         |
| `82`   | Rain showers: violent intensity                           | Rovesci intensi                | `cloud-rain`         |
| `85`   | Snow showers: slight intensity                            | Rovesci di neve                | `snowflake`          |
| `86`   | Snow showers: heavy intensity                             | Rovesci di neve intensi        | `snowflake`          |
| `95`   | Thunderstorm: slight or moderate                          | Temporale                      | `cloud-rain`         |
| `96`   | Thunderstorm with slight hail                             | Temporale con grandine         | `cloud-rain`         |
| `99`   | Thunderstorm with heavy hail                              | Temporale con grandine intensa | `cloud-rain`         |

> I codici non presenti in tabella (es. 2x, 4x diversi da 45/48) non sono restituiti da Open-Meteo e non hanno mapping.  
> Un codice sconosciuto produce `condition_icon = None` e `description = None`, rendendo il banner privo di icona e descrizione ma funzionante.

---

## Dipendenze Python

| Libreria    | Uso                                  |
|-------------|--------------------------------------|
| `requests`  | HTTP GET verso l'API Open-Meteo      |
| `threading` | Lock per cache thread-safe           |
| `datetime`  | Calcolo dello slot orario corrente   |

`requests` è l'unica dipendenza esterna; è già in `requirements.txt`.
