# Family Planner Calendar

A minimalist calendar viewer inspired by *Wall Street Journal* typography, designed to run on a **Raspberry Pi** with an e-ink display. Includes a web server for browser preview and remote configuration.

---

## Features

- **Calendar + Weather**: banner with date, weather icon, and temperatures from **Open-Meteo** (no API key required)
- **Calendar sources**: Apple Calendar / iCloud (CalDAV), Google Calendar, generic iCal feeds, local `.ics` files
- **Portrait and landscape layout**: selectable from configuration, adaptable to any resolution
- **Screen rotation**: support for 0°/90°/180°/270° via `display.rotation` — the EinkRenderer post-processor rotates the final image before sending it to the panel
- **Artwork mode (privacy)**: pressing button B shows a random public-domain painting from the **Art Institute of Chicago** (or a local image) instead of the calendar; pressing A restores the planner
- **Slideshow**: in artwork mode, button C toggles automatic image rotation at a configurable interval (`artwork.slideshow_interval_minutes`, default 30 min)
- **Shutdown screen**: pressing button D shows a final artwork on the panel before the device shuts down
- **E-ink display**: Waveshare EPD and Pimoroni Inky Impression (Spectra 6) panels — palette quantization (BW / BWR / 4-gray / Spectra 6) and optional Floyd-Steinberg dithering
- **FastAPI web server**: browser preview (`GET /`) and remote configuration (`GET/POST /config`)
- **Artwork management from the web config**: list, upload, rename, and delete images in the local `pictures/` folder, and a Test button to preview an endpoint-query result — all directly from `/config`
- **Minimal repaints**: the panel is refreshed on a bihourly clock grid aligned to the weather's forecast window, plus an immediate push when the calendar actually changes — 11 scheduled repaints a day instead of one per hour, with a silent quiet band overnight (`refresh` section)
- **Always up-to-date calendar view**: the Home always shows the current day — no Up/Down navigation or pagination. Physical buttons on Pimoroni Inky Impression are **A = return to planner**, **B = artwork/privacy**, **C = slideshow toggle**, **D = shutdown** (positions stay fixed across panel rotation)

---

## Hardware Requirements

| Component | Minimum | Recommended |
|---|---|---|
| SBC | Raspberry Pi 3B | Raspberry Pi 4 / 5 |
| Memory | 1 GB RAM | 2 GB RAM |
| Storage | 8 GB SD Class 10 | 16 GB SD A1 |
| Display | Waveshare e-ink 7.5" V2 **or** Pimoroni Inky Impression (Spectra 6) | — |
| OS | Raspberry Pi OS Lite (Bookworm 64-bit) | — |

---

## Software Requirements

- Python 3.11+
- Dependencies listed in `requirements.txt`

**On Raspberry Pi**: the panel driver libraries are imported lazily, so they are only needed at runtime on the device. `inky` (Pimoroni) is listed in `requirements.txt` and installs everywhere but is imported lazily; `waveshare-epaper` (Waveshare) is optional and installed on the target Pi only. On macOS/Linux the app runs in web-server-only mode (browser preview) — no panel hardware required.

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/<org>/family-planner.git
cd family-planner
```

### 2. Create a virtualenv and install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Copy and customize the configuration

```bash
cp config/default.yaml config/config.yaml
```

Edit `config/config.yaml` with your data (CalDAV URL, credentials, display type). Set the correct permissions to protect credentials:

```bash
chmod 600 config/config.yaml
```

> **Security**: for Apple Calendar use an **App-Specific Password** generated at [appleid.apple.com](https://appleid.apple.com). Never use the Apple ID password directly.

---

## Local Start (development and testing)

```bash
source .venv/bin/activate
python app/main.py --config config/config.yaml
```

Open a browser at `http://localhost:8080` to view the calendar or access the configuration interface (`/config`).

For a quick start use the script:

```bash
./scripts/start.sh
```

---

## Deploy to Raspberry Pi

Make sure the SSH key is configured for access to the device, then:

```bash
./scripts/deploy.sh pi@<raspberry-ip>
```

To configure automatic startup as a systemd service:

```bash
./scripts/setup-autostart.sh pi@<raspberry-ip>
```

The service is registered as `family-planner.service` and starts automatically at boot.

---

## Configuration

The YAML file is validated through **Pydantic v2** at startup. A schema error stops the process with a clear diagnostic message.

```yaml
server:
  host: "0.0.0.0"
  port: 8080
  # Optional Basic Auth on /config and /api/config/* routes
  # auth_username: null
  # auth_password: null

timezone: "Europe/Rome"      # IANA name (e.g. "Europe/Rome") or "local"

refresh:
  # A panel repaint costs 20-30 s of flashing, so the cadence follows how often
  # the content actually changes. The default grid is bihourly and aligned to
  # midnight, matching the weather's bihourly forecast window — the only thing
  # on screen that moves by itself. Must divide 1440.
  display_interval_minutes: 120
  # Network fetch only, not a repaint: a calendar change earns its own push, an
  # unchanged calendar earns none. Must divide 60.
  calendar_poll_minutes: 15
  # Minimum gap between calendar-driven pushes: collapses a burst of edits made
  # from a phone into a single repaint.
  min_push_interval_minutes: 20
  quiet_hours:
    enabled: true
    start: "23:00"           # included
    end: "06:00"             # excluded
    # Times at which the panel repaints anyway during the night. "00:00" rolls
    # the date over; "23:00" is the seal — the last repaint before the night
    # (drop it for one repaint less a day and the 22:00 frame, the one that still
    # shows the temperature, stays up until midnight). They are NOT required to
    # fall inside start/end: each fires at its own time, so moving the band start
    # never silently deletes the seal. They do require the band to be enabled.
    #
    # Night frames — the band and these ticks, wherever they are configured —
    # omit the current temperature, the condition icon and the daily max/min:
    # they would sit on the panel for hours going stale. The bihourly strip
    # stays — it is a forecast, so it is still useful at breakfast.
    allowed_ticks: ["23:00", "00:00"]
    # La fascia notturna (attivazione, orari, aggiornamento di mezzanotte) è
    # modificabile anche dal pannello web, sezione "Fascia notturna" in /config.
    # Le tre cadenze qui sopra restano solo su file.

weather:
  enabled: false             # true → shows the weather section
  latitude: 45.4654          # GPS coordinates of the location
  longitude: 9.1866
  units: "celsius"           # "celsius" | "fahrenheit"

display:
  layout: "landscape"        # "landscape" | "portrait"
  show_buttons: false        # show on-screen navigation overlay (browser preview only)
  rotation: 0                # screen rotation: 0 | 90 | 180 | 270
  eink_model: 7in5_V2        # panel model — also determines the canvas resolution
  eink_palette: bw           # bw | bwr | 4gray | spectra6
  eink_dither: true
  eink_saturation: 0.5       # color intensity for quantization (0.0–1.0)
  # The canvas width/height are derived automatically from eink_model + rotation.

artwork:
  source: "endpoint"           # "endpoint" → random painting from the ARTIC API (uses `query`)
                               # "folder"   → local images from `folder`, alphabetical
  query: "landscape painting"  # search query for artwork (Art Institute of Chicago)
  folder: "pictures"           # folder scanned in "folder" mode (relative to project root)
  slideshow_interval_minutes: 30  # button C in artwork mode auto-advances at this cadence (min 1)

calendars:
  - name: "Family"
    type: "caldav"
    url: "https://caldav.icloud.com"
    username: "user@icloud.com"
    password: "xxxx-xxxx-xxxx-xxxx"   # Apple ID App-Specific Password
    color: "#4A90D9"

  - name: "Google Calendar"
    type: "ical"
    url: "https://calendar.google.com/calendar/ical/<id>/basic.ics"
    color: "#27AE60"

  - name: "Local"
    type: "ics"
    path: "/home/pi/calendars/local.ics"
    color: "#E74C3C"
```

Configuration can also be modified via the web interface at `http://<host>:8080/config`.

---

## Project Structure

```
family-planner/
├── app/
│   ├── main.py              # Entry point
│   ├── config.py            # Config loading and validation (Pydantic v2)
│   ├── scheduling.py        # RefreshPolicy — when to poll, when to repaint, quiet band
│   ├── server/              # FastAPI app, routes, Jinja2 templates
│   ├── calendar/            # CalDAV / iCal / ICS providers and aggregator
│   ├── renderer/            # Pillow rendering pipeline (e-ink + browser preview)
│   ├── weather/             # OpenMeteoProvider, cached for one bihourly window
│   └── display/             # Waveshare and Pimoroni Inky e-ink display handlers
├── config/
│   └── default.yaml         # Default configuration
├── scripts/                 # Deploy, install, autostart scripts
├── systemd/                 # systemd unit file
├── docs/
│   ├── architecture.md      # Architecture and technical stack
│   ├── design.md            # Design system (typography, palette, layout)
│   └── artworks.md          # Artwork management (Art Institute of Chicago API)
└── requirements.txt
```

---

## Architecture — Rendering Pipeline

```
CalendarAggregator (CalDAV / iCal / ICS)
        │
        ▼
PillowEinkRenderer (native Pillow)
        │
        ├── Browser preview ──▶ GET /preview.png (same PIL.Image, as PNG)
        │
        └── E-ink ──▶ EinkRenderer (palette quantization + Floyd-Steinberg dithering)
                            │
                            └── EinkDisplay / InkyDisplay (SPI)
```

The pipeline is shared: `PillowEinkRenderer` generates the same `PIL.Image` for the panel and the browser preview. Only the final post-processing differs. Weather is injected by `OpenMeteoProvider` (keyless Open-Meteo API, cached for one bihourly window so it expires exactly when the panel is allowed to show new data).

When the frame is pushed matters as much as how it is drawn: `RefreshPolicy` (`app/scheduling.py`) keeps the network poll, the repaint grid and the push decision separate, so an unchanged screen is never repainted and a night frame — which sits on the panel until dawn — omits the readings that would go stale on it. See [docs/architecture.md](docs/architecture.md) and the `refresh` section above.

`PillowEinkRenderer.render_artwork()` is a second entry point of the same renderer: it fetches a random public-domain painting from the **Art Institute of Chicago** via IIIF and returns it as a `PIL.Image` of the same format — privacy mode and the shutdown screen use this same pipeline.

---

## License

MIT — see [LICENSE](LICENSE).
