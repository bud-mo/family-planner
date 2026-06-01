# Family Planner Calendar

A minimalist calendar viewer inspired by *Wall Street Journal* typography, designed to run on a **Raspberry Pi** with an HDMI or e-ink display. Includes a web server for browser preview and remote configuration.

---

## Features

- **Calendar + Weather**: banner with date, weather icon, and temperatures from **Open-Meteo** (no API key required)
- **Calendar sources**: Apple Calendar / iCloud (CalDAV), Google Calendar, generic iCal feeds, local `.ics` files
- **Portrait and landscape layout**: selectable from configuration, adaptable to any resolution
- **Screen rotation**: support for 0°/90°/180°/270° via `display.rotation` — the EinkRenderer post-processor rotates the final image before sending it to the panel
- **Artwork mode (privacy)**: pressing button B (or key `B` on HDMI) shows a random public-domain painting from the **Art Institute of Chicago** instead of the calendar; pressing A restores the planner
- **Shutdown screen**: pressing button D (or key `D` on HDMI) shows a final artwork on the panel before the device shuts down
- **HDMI display**: pygame (SDL2) window with configurable refresh cycle — no browser required
- **Waveshare e-ink display**: palette quantization (BW / BWR / 4-gray / Spectra 6) and optional Floyd-Steinberg dithering
- **FastAPI web server**: browser preview (`GET /`) and remote configuration (`GET/POST /config`)
- **Always up-to-date calendar view**: the Home always shows the current day — no Up/Down navigation or pagination. Physical buttons on Pimoroni Inky Impression are **A = return to planner**, **B = artwork/privacy**, **D = shutdown**; on HDMI/pygame keys `B`/`D` and `q`/`F4` map to artwork, shutdown, and quit

---

## Hardware Requirements

| Component | Minimum | Recommended |
|---|---|---|
| SBC | Raspberry Pi 3B | Raspberry Pi 4 / 5 |
| Memory | 1 GB RAM | 2 GB RAM |
| Storage | 8 GB SD Class 10 | 16 GB SD A1 |
| Display | HDMI 1080p **or** Waveshare e-ink 7.5" V2 | — |
| OS | Raspberry Pi OS Lite (Bookworm 64-bit) | — |

---

## Software Requirements

- Python 3.11+
- Dependencies listed in `requirements.txt`

**On Raspberry Pi**: SDL2 is required for HDMI mode (`libsdl2-dev`). Waveshare libraries are only needed for e-ink mode.

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

weather:
  enabled: true              # false → hides the weather section
  latitude: 45.4654          # GPS coordinates of the location
  longitude: 9.1866
  units: "celsius"           # "celsius" | "fahrenheit"

display:
  type: "hdmi"               # "hdmi" | "eink"
  layout: "landscape"        # "landscape" | "portrait"
  width: 1024
  height: 600
  fullscreen: false          # true → fullscreen; false → sized window (development)
  show_buttons: false        # show navigation buttons (HDMI touchscreen only)
  rotation: 0                # screen rotation: 0 | 90 | 180 | 270
  # E-ink only:
  eink_model: 7in5_V2
  eink_palette: bw           # bw | bwr | 4gray | spectra6
  eink_dither: true
  eink_saturation: 0.5       # color intensity for quantization (0.0–1.0)

artwork:
  query: "landscape painting"  # search query for artwork (Art Institute of Chicago)

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
│   ├── server/              # FastAPI app, routes, Jinja2 templates
│   ├── calendar/            # CalDAV / iCal / ICS providers and aggregator
│   ├── renderer/            # Pillow rendering pipeline (HDMI + e-ink)
│   ├── weather/             # OpenMeteoProvider with 1h TTL in-memory cache
│   └── display/             # pygame (HDMI) and Waveshare (e-ink) display handlers
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
        ├── HDMI ──▶ HdmiDisplay (pygame / SDL2)
        │
        └── E-ink ──▶ EinkRenderer (palette quantization + Floyd-Steinberg dithering)
                            │
                            └── EinkDisplay (SPI Waveshare)
```

The pipeline is shared: `PillowEinkRenderer` generates the same `PIL.Image` for both displays. Only the final post-processing differs. Weather is injected by `OpenMeteoProvider` (1h TTL in-memory cache, keyless Open-Meteo API).

`PillowEinkRenderer.render_artwork()` is a second entry point of the same renderer: it fetches a random public-domain painting from the **Art Institute of Chicago** via IIIF and returns it as a `PIL.Image` of the same format — privacy mode and the shutdown screen use this same pipeline.

---

## License

MIT — see [LICENSE](LICENSE).
