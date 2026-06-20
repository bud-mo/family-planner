# Architecture — Family Planner Calendar

## Overview

**Family Planner** is a calendar viewer optimised for Raspberry Pi (3+) devices with an e-ink display, also runnable locally (Mac/Linux) in web-server-only mode for development and testing. It exposes a web service for both calendar display and configuration.

---

## Technology Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11+ |
| Web server | FastAPI + Uvicorn |
| HTML templates | Jinja2 (configuration only) |
| Rendering | `PillowEinkRenderer` — native Pillow from `NavigationState` + events, no browser |
| E-ink post-processing | `EinkRenderer` — resize, palette quantisation, Floyd-Steinberg dithering |
| CalDAV calendar | `caldav` + `icalendar` |
| Configuration | YAML (`pyyaml`) + Pydantic v2 |
| E-ink display | Waveshare EPD / Pimoroni Inky (dynamic import — requires RPi hardware) |

---

## Project Structure

```
family-planner/
├── app/
│   ├── main.py                  # Entry point — argument parsing, server startup
│   ├── config.py                # Configuration loading and validation
│   ├── server/
│   │   ├── __init__.py
│   │   ├── app.py               # FastAPI app definition and routes
│   │   ├── auth.py              # Optional Basic Auth dependency for config routes
│   │   ├── pictures.py          # Picture-folder service: safe path, list, upload, rename, delete, thumbnail
│   │   ├── routes/
│   │   │   ├── index.py         # GET / — HTML preview; GET /preview.png — PNG image
│   │   │   └── config.py        # GET/POST /config + /api/pictures* + /api/test-* routes
│   │   └── templates/           # Jinja2 templates
│   │       ├── base.html        # Base configuration layout
│   │       └── config.html      # Configuration interface
│   ├── calendar/
│   │   ├── __init__.py
│   │   ├── base.py              # Abstract CalendarProvider class
│   │   ├── caldav_provider.py   # CalDAV provider (Apple Calendar / iCloud)
│   │   ├── ics_provider.py      # Local .ics file provider
│   │   ├── ical_provider.py     # iCal URL provider (Google Calendar, public feeds)
│   │   ├── aggregator.py        # Aggregates events from multiple providers
│   │   └── data_builders.py     # Shared data preparation between routes and PillowEinkRenderer
│   ├── renderer/
│   │   ├── __init__.py
│   │   ├── base.py                      # Abstract Renderer class
│   │   ├── pillow_eink_renderer.py      # PillowEinkRenderer: native Pillow rendering (e-ink + preview)
│   │   │                                #   render() → calendar screen
│   │   │                                #   render_artwork() → ARTIC painting (privacy/shutdown)
│   │   ├── eink_renderer.py             # E-ink post-processing: resize, palette quantisation,
│   │   │                                #   Floyd-Steinberg dithering, screen rotation
│   │   ├── rich_text.py                 # HTML description parser CalDAV → RichSpan/RichLine
│   │   ├── state.py                     # NavigationState (immutable dataclass — anchor_date = today)
│   │   └── tokens.py                    # Python design tokens
│   ├── weather/
│   │   ├── __init__.py
│   │   ├── provider.py          # WeatherProvider: abstract base class
│   │   └── open_meteo.py        # OpenMeteoProvider: Open-Meteo API + in-memory cache TTL 1h
│   └── display/
│       ├── __init__.py
│       ├── buttons.py           # InkyButtonHandler (GPIO A/B/C/D, gpiod) + resolve_button_roles()
│       ├── slideshow.py         # SlideshowController: auto-advance timer for artwork mode
│       └── eink.py              # EinkDisplay / InkyDisplay: push image via SPI; panel_available()
├── config/
│   └── default.yaml             # Default configuration (included in repo)
├── scripts/
│   ├── deploy.sh                # Deploy via SSH to Raspberry Pi
│   ├── install.sh               # Dependency installation on device
│   ├── setup-autostart.sh       # systemd service setup on device
│   └── start.sh                 # Simplified local startup
├── systemd/
│   └── family-planner.service   # systemd service unit for the Python app
├── docs/
│   ├── design.md                # UX/UI design (rendering reference)
│   └── architecture.md          # This file
├── requirements.txt
└── README.md
```

---

## Configuration

The configuration file is in **YAML** format. Its path is passed as a CLI argument at startup:

```bash
python app/main.py --config /path/to/config.yaml
```

If not specified, the fallback is `./config/default.yaml`.

### Configuration file schema

```yaml
server:
  host: "0.0.0.0"
  port: 8080
  # Optional Basic Auth on /config and /api/config/* routes
  # auth_username: null
  # auth_password: null

weather:
  enabled: true              # false → disables the provider, shows date only
  latitude: 45.4654          # GPS coordinates of the location
  longitude: 9.1866
  units: "celsius"           # "celsius" | "fahrenheit"

display:
  layout: "landscape"        # "landscape" | "portrait"
  show_buttons: false        # on-screen navigation overlay (browser preview only)
  rotation: 0                # screen rotation: 0 | 90 | 180 | 270
  eink_model: "7in5_V2"      # panel model — also determines the canvas resolution
  eink_palette: "bw"         # bw | bwr | 4gray | spectra6
  eink_dither: true          # enable Floyd-Steinberg dithering
  eink_saturation: 0.5       # colour intensity for quantisation (0.0–1.0)
  # The canvas width/height are derived from eink_model + rotation (not configured).

artwork:
  query: "landscape painting"  # artwork search query (Art Institute of Chicago)

calendars:
  - name: "Family"
    type: "caldav"
    url: "https://caldav.icloud.com"
    username: "user@icloud.com"
    password: "app-specific-password"   # Apple ID App-Specific Password
    color: "#4A90D9"

  - name: "Local calendar"
    type: "ics"
    path: "/home/pi/calendars/local.ics"
    color: "#E74C3C"

  - name: "Google Calendar"
    type: "ical"
    url: "https://calendar.google.com/calendar/ical/<id>/basic.ics"  # webcal:// also accepted
    color: "#27AE60"
```

Configuration is validated via **Pydantic v2** at startup; schema errors halt the process with a clear message.

> **Security note**: the configuration file contains no weather credentials (Open-Meteo requires no API key). GPS coordinates are considered non-sensitive data in this context.

---

## Application Flow

```
Startup (main.py --config ...)
        │
        ▼
  Load config.yaml  ──(error)──▶  Exit with message
        │
        ▼
  Initialise CalendarAggregator
  (instantiates providers defined in config)
        │
        ▼
  Initialise OpenMeteoProvider  ← only if weather.enabled: true
  (in-memory cache TTL 1h, thread-safe)
        │
        ▼
  Initialise PillowEinkRenderer(config, weather_provider)  ← single renderer (panel + preview)
        │
        ▼
  Start Display (only when panel_available() — i.e. running on a Raspberry Pi)
        │
        ├── No panel (dev) ──▶  web-server-only mode (browser preview at /)
        │
        └── E-ink ──▶  EinkRenderer(config.display)  [no browser, no display server]
                        Uvicorn on main thread
                        InkyButtonHandler.start() — GPIO daemon thread (gpiod)
                          roles = resolve_button_roles(rotation)  — A/B/C/D → planner/artwork/slideshow/shutdown
                          (line request: all four lines; falls back to A/B/D if BCM16/CS1 is refused)
                          A → wake_event.set()  → skip sleep, immediate re-render (back to planner) + slideshow.stop()
                          B → _perform_show_artwork() → fetch ARTIC → EinkRenderer → push
                              (artwork_mode blocking: suppresses loop pushes while active)
                          C → SlideshowController.toggle() — start/stop the auto-advance timer
                              (no-op outside artwork mode; own daemon thread, interval read live)
                          D → _perform_shutdown() → render_artwork() → push → sudo shutdown -h now
                        Daemon loop (clock-aligned cadence — see app/scheduling.py):
                          wakes at every quarter-hour (xx:00/15/30/45)
                          calendar: re-fetch at every tick; weather: only at xx:00
                          push only if data changes (content signature)
                          NavigationState() → anchor_date = today
                          aggregator.get_events(start, end, force=True) → events
                          PillowEinkRenderer.render(state, events) → PIL.Image
                          if NOT artwork_mode:
                            EinkRenderer.process(img) → resize + palette + dithering + rotation
                            EinkDisplay.push() → SPI → Waveshare panel
```

---

## Web Routes

### `GET /`
Minimal HTML page with auto-refresh that shows the current calendar image via `<img src="/preview.png">`. The refresh interval is fixed at `WEB_REFRESH_SECONDS` (900 s = 15 min, aligned with the calendar cadence; see `app/scheduling.py`). Useful for browser preview during development.

### `GET /preview.png`
Calls `PillowEinkRenderer.render(state, events)` on-demand and returns the resulting PNG image (`Content-Type: image/png`). This is the same image that would be sent to the e-ink panel.

### `GET /config`
Web interface for configuration: add/remove calendars, modify display parameters, test provider connections.

### `POST /config`
Saves changes to the configuration file and restarts the server gracefully (SIGHUP or Uvicorn restart).

### Picture-folder management

The `/config` page can manage the local artwork folder (the directory used by
artwork *folder* mode) directly. These routes mutate the folder on disk only —
they never rewrite the YAML and never trigger a reload; the renderer rescans the
folder on every render, so changes appear on the next artwork frame.

| Method & path | Purpose | Response |
|---|---|---|
| `GET /api/pictures` | list folder images + size/mtime | JSON `{ok, folder, pictures}` |
| `GET /api/pictures/thumbnail?name=` | PIL-downscaled JPEG (never the raw file) | `image/jpeg`, `Cache-Control: no-store` |
| `POST /api/pictures/upload` | upload one image (multipart `file`) | JSON `{ok, name}` |
| `POST /api/pictures/rename` | rename (`old`, `new`) | JSON `{ok, name}` |
| `POST /api/pictures/delete` | delete (`name`) | JSON `{ok}` |
| `POST /api/test-artwork` | dry-run: fetch one image for `query`, return caption + base64 PNG | JSON `{ok, caption, image}` |

The service layer lives in `app/server/pictures.py`. Its `safe_picture_path`
confines every named file inside the configured folder (rejecting `..`,
separators, absolute paths, dotfiles, and symlink escapes); uploads are validated
as real images via Pillow. The folder is resolved through the single helper
`resolve_artwork_folder` (in `app/renderer/components/artwork.py`), shared with
the renderer.

---

## Weather Integration — Open-Meteo

Weather is provided by **Open-Meteo** (`https://api.open-meteo.com`) — a public, free, no-API-key, GDPR-compliant API with hourly updates.

### `app/weather/` module

```
app/weather/
├── __init__.py          # exports WeatherProvider, OpenMeteoProvider
├── provider.py          # WeatherProvider: thread-safe ABC — get() → WeatherData
└── open_meteo.py        # OpenMeteoProvider: fetch + in-memory cache TTL 1h
```

### API endpoint

```
GET https://api.open-meteo.com/v1/forecast
    ?latitude=<lat>
    &longitude=<lon>
    &current=temperature_2m,weather_code
    &daily=temperature_2m_max,temperature_2m_min
    &hourly=temperature_2m,weather_code
    &temperature_unit=celsius
    &timezone=auto
    &forecast_days=2
```

`forecast_days=2` is required to obtain 48 hourly slots, allowing the 6 bi-hourly forecasts for the current day to be shown even in the afternoon/evening hours.

### In-memory cache

`OpenMeteoProvider` maintains an in-memory cache protected by `threading.Lock`:
- The `_cached_at` field records the timestamp of the last fetch (`time.monotonic()`)
- If `now − cached_at < 3600s` and data is present, the cache is returned without network calls
- The HTTP fetch happens **outside the lock** (`timeout=10s`) to avoid blocking the rendering thread
- On HTTP/parse error, the stale cache is returned; if no cache exists yet, an empty `WeatherData()` is returned → the renderer shows date only

### `HourlySlot` and `WeatherData` structures (`renderer/tokens.py`)

```python
@dataclass
class HourlySlot:
    hour: int                            # slot start hour (0-23, e.g. 14 → "14:00")
    condition_icon: str | None = None    # Tabler icon name
    temp: float | None = None            # forecast temperature (°C)

@dataclass
class WeatherData:
    condition_icon: str | None = None   # Tabler icon name (e.g. "sun", "cloud-rain")
    description: str | None = None      # description text (e.g. "Clear", "Rain")
    temp_current: float | None = None   # current temperature
    temp_max: float | None = None       # daily maximum
    temp_min: float | None = None       # daily minimum
    hourly_forecast: list[HourlySlot] = field(default_factory=list)  # 6 bi-hourly slots
```

### WMO 4677 → Tabler icons mapping

| WMO codes | Condition | Tabler icon |
|---|---|---|
| 0, 1 | Clear / Mainly clear | `sun` |
| 2, 3, 45, 48 | Cloudy / Fog | `cloud` |
| 51–65, 66, 67, 80–82, 95–99 | Rain / Showers / Thunderstorm / Freezing rain | `cloud-rain` |
| 56, 57, 71–77, 85, 86 | Snow / Freezing drizzle | `snowflake` |

The corresponding PNG icons are loaded at **48 px** from `app/assets/icons/48/{name}.png` via `load_icon()`. If the icon is unavailable, the area remains empty (no text fallback).

### Rendering in the banner

The banner is split into two rows:

**Main row (`BANNER_MAIN_HEIGHT = 90 px`)** — `_draw_weather()`:
- Current date (Playfair Display)
- Current temperature + daily max/min (IBM Plex Sans)
- **Condition icon** at **48 px** loaded from `app/assets/icons/48/{name}.png` via `load_icon()`, tinted with `palette["INK"]`, positioned to the left of the temperature. If the icon is unavailable, the icon area remains empty (no text fallback to `description`).

**Bi-hourly row (`BANNER_HOURLY_HEIGHT = 127 px`)** — `_draw_hourly_row()`:
- 6 side-by-side cells, each with: time (IBM Plex Mono xs), 48 px condition icon, forecast temperature (IBM Plex Sans semibold sm)
- Data comes from `WeatherData.hourly_forecast` (list of `HourlySlot`)
- If `hourly_forecast` is empty (weather disabled or error), the row is not drawn

### Graceful degradation

In all error cases (no network, unreachable API, malformed response), `OpenMeteoProvider.get()` does not raise exceptions: it returns the stale cache if available, otherwise an empty `WeatherData()`. Rendering is never blocked by missing weather data.

---

## Apple Calendar Integration

Apple Calendar is supported via **CalDAV** through iCloud:

- **Endpoint URL**: `https://caldav.icloud.com`
- **Authentication**: App-Specific Password generated at [appleid.apple.com](https://appleid.apple.com) (required for accounts with 2FA enabled)
- **Library**: `caldav` (Python)
- The provider fetches **all** available calendars on the account (`principal.calendars()`) without filtering. The `name` field in the config is the aggregator's visual label (used in logs), while `color` is the event colour in rendering. No filtering by calendar name is applied.

> **Security note**: the password is never exposed via the web API. The configuration file must have `600` permissions.

---

## Google Calendar Integration (and generic iCal feeds)

Google Calendar and any service that exposes an iCalendar feed via HTTP/HTTPS are supported by the `ical` type:

- **URL**: obtained from Google Calendar → *Settings* → *Integrate calendar* → *Secret address in iCal format*
- **Authentication**: not required — the URL acts as a secret token; no username/password is ever needed
- **`webcal://` scheme**: accepted and automatically converted to `https://` by `IcalProvider`
- **Library**: `requests` (already included) + `icalendar` (same pipeline as `IcsProvider`)

```yaml
calendars:
  - name: "Google Calendar"
    type: "ical"
    url: "https://calendar.google.com/calendar/ical/<id>/basic.ics"
    color: "#27AE60"
```

> **Security note**: the Google Calendar iCal URL contains a secret identifier. Treat it like a password: do not share it and do not include it in logs. The configuration file must have `600` permissions.

---

## Display Strategies

### General architecture

Family Planner uses a **single renderer** — `PillowEinkRenderer` — shared by the e-ink panel and the browser preview. No browser or Chromium process is started.

```
           NavigationState() — always today
                    │
   PillowEinkRenderer (e-ink + browser preview)
   native Pillow — render(state, events)
   → PIL.Image
          │
   ┌──────┴────────┐                  ┌──────────────────┐
   │ GET /preview  │                  │   EinkRenderer   │
   │ .png (browser)│                  │ resize/quantize  │
   │ same PIL.Image│                  │ dither           │
   │ as PNG        │                  └─────────┬────────┘
   └───────────────┘                           │ quantised PIL.Image
                                    ┌──────────▼──────────┐
                                    │ EinkDisplay /        │
                                    │ InkyDisplay (SPI)    │
                                    └─────────────────────┘
```

### Web-server-only mode (development)

When the app is not running on a Raspberry Pi (`panel_available()` returns `False`), no e-ink loop is started: only the web server runs and the calendar is viewed through the browser preview at `/`. This is the standard way to develop on macOS/Linux — no display server or panel libraries are required.

### E-ink — PillowEinkRenderer (native Pillow, no browser)

The e-ink loop starts no Chromium process. Rendering happens entirely in-process via **`PillowEinkRenderer`** (`renderer/pillow_eink_renderer.py`), which produces a `PIL.Image` directly from `NavigationState` and the event list. TTF fonts are loaded from `app/assets/fonts/` — no network calls.

`main.py` starts a daemon thread that wakes at every quarter-hour boundary (`xx:00`/`xx:15`/`xx:30`/`xx:45`, see `app/scheduling.py`). At each tick it re-fetches the calendar; weather only at `xx:00`. When both cadences coincide (`xx:00`) only one cycle is run. The push to the panel happens only if the *content signature* (`_content_signature`) changes. Button A forces an immediate refresh of both weather **and** calendar:

1. **`NavigationState()`** creates a new state with `anchor_date = date.today()`.
2. **`aggregator.get_events(start, end, force=True)`** fetches fresh events for the current view's range.
3. **`PillowEinkRenderer.render(state, events)`** produces an RGB `PIL.Image` at the canvas resolution derived from `eink_model` + `rotation` (`config.display.resolution`).
4. **`EinkRenderer`** (`renderer/eink_renderer.py`) applies:
   - **Resize** to the panel's native resolution (13 Waveshare models supported)
   - **Palette quantisation**: B&W (1-bit), BWR (3 colours), 4-gray — configurable via `eink_palette`
   - **Floyd-Steinberg dithering** — optional, via `eink_dither: true`
5. **`EinkDisplay`** (`display/eink.py`) sends the image to the panel via the appropriate Waveshare driver, loaded dynamically:
   ```python
   # Guarded import — only executed inside the driver, on the device
   from waveshare_epd import epd13in3k  # example 13.3" model
   ```
   This ensures the code is runnable on macOS/Linux without hardware libraries.

> **Supported panels**: 13 Waveshare models (mapping `eink_model → module` in `display/eink.py`) + 3 Pimoroni Inky Impression Spectra 6 (`inky_impression_4`, `inky_impression_7`, `inky_impression_13`) with resolutions defined in `renderer/eink_renderer.py`.

> **Refresh time**: Waveshare e-ink panels typically take 15–30 seconds for a full update. The cadences (calendar 15 min, weather 1 hour) are fixed and well above this limit; the push occurs only when data changes.

> **On RPi**: the e-ink loop requires no display server — it runs on RPi OS Lite without X11 or Wayland.

### Home Screen — Single View

The interface consists of a **single Home screen** — no view hierarchy or navigation exists. `NavigationState` carries a single field: `anchor_date = date.today()`, used to determine the mini-calendar month and the 30-day appointment list window.

`PillowEinkRenderer.render(state, events)` delegates to four components, each receiving its own `Rect`:

| Component | Method | `Rect` (portrait) | `Rect` (landscape) |
|---|---|---|---|
| Weather banner | `_draw_weather()` + `_draw_hourly_row()` | `(0, 0, W, 217)` | `(0, 0, col_left, 217)` |
| Mini-calendar | `_draw_mini_calendar()` | `(0, 217, W, 560)` | `(0, 217, col_left, H−271)` |
| Agenda list | `_draw_agenda()` | `(0, 777, W, H−831)` | `(col_left, 0, col_right, H−54)` |
| Footer | `_draw_footer()` | `(0, H−54, W, 54)` | `(0, H−54, W, 54)` |

where `col_left = int(W × 0.50)` and `col_right = W − col_left`.

> **Weather component**: the `WeatherData` structure (condition icon, text description, current temperature, daily max/min) is produced by `OpenMeteoProvider.get()` — called inside `PillowEinkRenderer.render()` if the provider was injected. Without a provider (or if `weather.enabled: false`), `WeatherData` remains empty and the banner shows date only.

---

## Graphic Component Architecture — Explicit Bounds

Each `_draw_*` component of `PillowEinkRenderer` receives its drawing bounds as an explicit `rect: Rect` parameter. It does not read global layout constants internally.

### `Rect` type

```python
# renderer/tokens.py
Rect = tuple[int, int, int, int]  # (x, y, width, height)
```

### Fundamental rule

`render()` is the **only** point in the entire codebase where the `Rect` **partition** is calculated (subdivision of `W × H` across banner/calendar/agenda/footer zones). The `_draw_*` methods **may** read `self._layout` and sub-component constants (e.g. `BANNER_MAIN_HEIGHT`, `BANNER_HOURLY_HEIGHT`) to position internal elements within their zone, but must not recalculate the global partition.

### Home component signatures

```python
def _draw_weather(
    self, draw: ImageDraw, img: Image.Image, rect: Rect,
    weather: WeatherData, palette: dict
) -> None: ...

def _draw_hourly_row(
    self, draw: ImageDraw, img: Image.Image, rect: Rect,
    weather: WeatherData, palette: dict
) -> None: ...

def _draw_mini_calendar(
    self, draw: ImageDraw, rect: Rect,
    state: NavigationState, events: list, palette: dict
) -> None: ...

def _draw_agenda(
    self, draw: ImageDraw, img: Image.Image, rect: Rect,
    state: NavigationState, events: list, palette: dict
) -> None: ...

def _draw_footer(
    self, draw: ImageDraw, rect: Rect,
    palette: dict
) -> None: ...
```

### `Rect` calculation in `render()`

```python
def render(self, state: NavigationState, events: list) -> Image.Image:
    W, H = self._size
    palette = get_palette()
    img = Image.new("RGB", (W, H), palette["BG"])
    draw = ImageDraw.Draw(img)

    if self._layout == "portrait":
        weather_rect   = (0,        0,                       W,          BANNER_HEIGHT)
        calendar_rect  = (0,        BANNER_HEIGHT,           W,          CALENDAR_HEIGHT)
        agenda_rect    = (0,        BANNER_HEIGHT + CALENDAR_HEIGHT,
                          W,        H - BANNER_HEIGHT - CALENDAR_HEIGHT - FOOTER_HEIGHT)
        footer_rect    = (0,        H - FOOTER_HEIGHT,       W,          FOOTER_HEIGHT)
    else:  # landscape
        col_left  = int(W * COL_LEFT_RATIO)
        col_right = W - col_left
        weather_rect   = (0,        0,                       col_left,   BANNER_HEIGHT)
        calendar_rect  = (0,        BANNER_HEIGHT,           col_left,
                          H - BANNER_HEIGHT - FOOTER_HEIGHT)
        agenda_rect    = (col_left, 0,                       col_right,  H - FOOTER_HEIGHT)
        footer_rect    = (0,        H - FOOTER_HEIGHT,       W,          FOOTER_HEIGHT)

    self._draw_weather(draw, img, weather_rect, weather_data, palette)
    self._draw_mini_calendar(draw, calendar_rect, state, events, palette)
    self._draw_agenda(draw, img, agenda_rect, state, events, palette)
    self._draw_footer(draw, footer_rect, palette)
    return img
```

### Absolute coordinates in components

Inside each `_draw_*`, absolute canvas coordinates are always derived from the origin of the received `rect`:

```python
x0, y0, w, h = rect
# drawing text at (local_x, local_y) relative to the component:
draw.text((x0 + local_x, y0 + local_y), text, font=font, fill=color)
```

### Benefits

- **Testability**: each component can be exercised on a canvas of arbitrary dimensions, without global display configuration.
- **Separation of concerns**: layout lives only in `render()`; components have no knowledge of the global structure.
- **Extensibility**: adding a new component or layout variant requires only a new `Rect` in `render()` and a new `_draw_*` method.

### Refactoring scope

Concerns **exclusively** `PillowEinkRenderer` (`renderer/pillow_eink_renderer.py`) and the addition of `Rect` + renamed constants in `renderer/tokens.py`. Calendar providers and FastAPI are not involved.

---

## Cross-platform

| Behaviour | Mac (development) | Linux / Raspberry Pi (production) |
|---|---|---|
| Display mode | web-server-only (`panel_available()` → False) | e-ink loop + web server |
| E-ink display | PillowEinkRenderer (native Pillow); panel driver not loaded | PillowEinkRenderer + EinkRenderer; panel driver via SPI |
| Preview | browser at `/` | browser at `/` (same image as the panel) |
| Calendar | CalDAV / ICS / iCal via network or local file | CalDAV / ICS / iCal via network or local file |
| Auto-start | Manual / local script | systemd (`family-planner.service`) |

---

## Deploy and Autostart Scripts

### `scripts/deploy.sh`
Deploys to the Raspberry Pi via SSH + `rsync`:

```
1. rsync of the entire folder (excluding .git, __pycache__, venv)
2. SSH: pip install -r requirements.txt
3. SSH: systemctl daemon-reload && systemctl restart family-planner
```

Configurable variables: `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_PATH`.

### `scripts/install.sh`
Run once on the device:
- Installs system dependencies (`python3-pip`, SPI/I2C libraries for e-ink)
- Creates the virtualenv
- Installs Python packages from `requirements.txt`
- Copies the systemd file to `/etc/systemd/system/`

### `scripts/setup-autostart.sh`
- Enables and starts the systemd service:
  - `family-planner.service` — Python server + e-ink display management (all in a single process)
- No display server (X11/Wayland) is required — the e-ink loop drives the panel directly via SPI

### `systemd/family-planner.service`
```ini
[Unit]
Description=Family Planner Calendar Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/family-planner
ExecStart=/home/pi/family-planner/venv/bin/python app/main.py --config /home/pi/family-planner/config.yaml
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

> **Note**: the e-ink loop drives the panel directly via SPI, so no display server (X11/Wayland) and no `graphical.target` dependency are needed.

---

## Security

- The configuration file (containing credentials) must have `600` permissions (`chmod 600 config.yaml`); correct permissions are verified at startup by `_check_file_permissions` in `config.py`
- The web server listens on `0.0.0.0` by default; if Basic Auth is not configured (see below) and the bind is not on loopback, an **explicit warning** is emitted in the logs at startup
- **`GET /config`**: CalDAV passwords, secret iCal URLs, and `server.auth_password` are **cleared** in the response via `_safe_config_dict` — never exposed in plaintext
- **`GET /api/config/download`**: returns a sanitised YAML (same logic as `_safe_config_dict`) — no credentials leave the device via HTTP. Passwords must be re-entered manually on backup restore
- **Optional Basic Auth** on `/config` and `/api/config/*` routes: if `server.auth_username` and `server.auth_password` are set in the config, a constant-time comparison protects all configuration routes. Preview-only routes (`/`, `/preview.png`, `/preview-eink.png`) remain always open — they show only the calendar, which contains no credentials
- Credentials never appear in system logs or error messages

---

## Main Dependencies (`requirements.txt`)

```
fastapi
uvicorn[standard]
jinja2
pydantic>=2.0
eval_type_backport         # Python 3.9 type hints compatibility
pyyaml
caldav
requests                   # HTTP for iCal URL provider + Open-Meteo weather API
icalendar
pillow                     # single renderer (PillowEinkRenderer) + post-processing (EinkRenderer)
python-multipart           # POST /config form
python-dateutil            # rrule expansion in IcsProvider (recurrences)
inky                       # Pimoroni Inky Impression driver (lazy import, safe on dev)
# waveshare-epaper (optional — RPi with Waveshare e-ink panel only)
```

---

## Component Diagram

```
┌───────────────────────────────────────────────────────────────────────┐
│                             main.py                                   │
│  args parsing → config load → aggregator → renderer                  │
└──────┬─────────────────────────────────────────────────┬─────────────┘
       │                                                 │
┌──────▼──────┐                                ┌────────▼────────┐
│  FastAPI    │                                │   Aggregator    │
│  GET /      │   NavigationState() created    │   (calendars)   │
│  GET /prev. │   fresh at every render        └────────┬────────┘
│  GET /prev-e│   anchor_date = date.today()     ┌──────┴──────┐
│  GET /config│                                  │             │
│  POST/config│                              ┌───▼──┐  ┌───────▼────┐
└─────────────┘                              │CalDAV│  │  ICS/iCal  │
                                             │Prov. │  │  Provider  │
                          ┌──────────────────┐└─────┘  └────────────┘
                          │  PillowEinkRenderer │
                          │  (panel + preview)  │◀──── OpenMeteoProvider
                          │  native Pillow      │      in-memory cache
                          │  state + events     │      TTL 1h
                          │  + WeatherData      │      (optional)
                          └─────────┬───────────┘
                                    │ PIL.Image
               ┌────────────────────┴─────────────────────┐
               │                                          │
    ┌──────────▼────────┐                    ┌────────────▼───────┐
    │  GET /preview.png │                    │    EinkRenderer    │
    │  (browser, PNG)   │                    │    resize/quantize │
    │                   │                    │    dither          │
    └───────────────────┘                    └────────────┬───────┘
                                                          │ quantised PIL.Image
                                             ┌────────────▼───────┐
                                             │ EinkDisplay /       │
                                             │ InkyDisplay (SPI)   │
                                             └────────────────────┘
```

---

## Artwork and Privacy Mode

### Rationale

The display shows family calendar data in a shared location. To preserve privacy when guests are present or when the device is not in use, button **B** (Inky Impression) instantly replaces the planner screen with a public-domain painting fetched from the **Art Institute of Chicago** (or a local image).

### Flow (e-ink)

```
Button B pressed (GPIO callback — gpiod thread)
    │
    ▼
artwork_mode.set()  ← the e-ink loop suppresses subsequent pushes
    │
    ▼
threading.Thread("artwork-push").start()
    │
    ├─ PillowEinkRenderer.render_artwork()
    │       └─ _fetch_artwork(W, H, query)
    │               └─ POST artic.edu/api/v1/artworks/search
    │               └─ GET IIIF image  (up to _MAX_ATTEMPTS=5 attempts)
    │               └─ ImageOps.fit → PIL.Image RGB (W×H)
    │               └─ _draw_artwork_caption()
    ├─ EinkRenderer.process(img)  ← quantisation + rotation
    └─ EinkDisplay.push() → SPI → panel
```

Pressing **A** → `wake_event.set()` + `artwork_mode.clear()` → the normal loop resumes immediately, overwriting the artwork with the updated planner.

### Shutdown screen

Pressing **D** starts `_perform_shutdown()`:

1. `stop_event.set()` — stops the e-ink loop
2. `renderer.render_artwork()` → `EinkRenderer.process()` → `EinkDisplay.push()` (final static image on the panel)
3. `server.should_exit = True` — terminates Uvicorn
4. `subprocess.run(["sudo", "shutdown", "-h", "now"])` — shuts down the system

If an error occurs during artwork fetch/push, the fallback is a white screen (`BG` palette), to ensure shutdown proceeds regardless.

---

## Screen Rotation

`display.rotation` accepts the values `0`, `90`, `180`, `270` (clockwise degrees). Rotation happens in **`EinkRenderer.process()`**, as the last step of post-processing:

```python
# 1. Resize — for 90°/270° the input dimensions are swapped relative to the
#    panel's native resolution.
W, H = self._size
resize_target = (H, W) if self._rotation in (90, 270) else (W, H)
resized = image.resize(resize_target, Image.Resampling.LANCZOS)

# 2. Palette quantisation (bw / bwr / 4gray / spectra6)
result = self._quantise_*(resized, dither_mode)

# 3. Rotation — PIL uses a counter-clockwise convention; we negate the value
#    to obtain the expected clockwise rotation.
if self._rotation:
    result = result.rotate(-self._rotation, expand=True)
```

**Dimension logic**: if the panel is 800×480 and `rotation=90`, the Pillow renderer produces a 480×800 image (portrait orientation), which is then rotated by -90° → 800×480 physical pixels. `config.display.resolution` returns this **logical canvas** size (before rotation), derived from `eink_model` and `rotation`.

---

## Known Technical Debt

The following items have been evaluated and deliberately deferred. Each entry lists the files involved and the rationale for deferral.

### 4.4 — Split of `pillow_eink_renderer.py`

**Files involved:** `app/renderer/pillow_eink_renderer.py` (~1400 lines)

**Description:** The file can be split into submodules with no behavioural change:

| New module | Extracted content |
|---|---|
| `artwork.py` | `_fetch_artwork`, ARTIC constants, `render_artwork`, `_draw_artwork_caption` |
| `text_layout.py` | `_fit_mixed`, `_measure_mixed`, `_draw_mixed`, `_wrap_rich_lines`, `_ellipsize`, `_measure_span_text` |
| `home_renderer.py` | the orchestrating `PillowEinkRenderer` class (`render`, `_draw_*`) |

**Rationale for deferral:** The refactoring is invasive (many internal imports to fix) and provides no functional benefit. Existing visual tests already cover the behaviour. Deferred to a future version when the file size becomes a concrete maintenance obstacle.

### 4.5 — Deduplicate CalDAV/ICS event parsing

**Files involved:** `app/calendar/caldav_provider.py` (`_component_to_event`, line ~128), `app/calendar/ics_provider.py` (`_expand_component`, line ~110)

**Description:** The two methods share extraction of DTSTART/DTEND/DURATION/attendees/UID/SUMMARY. A common helper could be extracted into `base.py`.

**Rationale for deferral:** The extraction has subtle differences between the two providers (CalDAV handles timezones via `vDatetime`, ICS uses `rrulestr`). A hasty refactoring would risk introducing regressions on timezone edge cases. Deferred until both providers are extended with new features that justify the unification.
