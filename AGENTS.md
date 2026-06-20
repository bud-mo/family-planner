# Family Planner — Agent Instructions

> **Official repository language: English.** All code, comments, documentation, commit messages, and agent instructions must be written in English.

This file defines always-active instructions for all AI agents working on this repository. It applies to every interaction in the workspace.

---

## Project Identity

**Family Planner** is a Python embedded application for Raspberry Pi that displays a calendar on an e-ink display (Waveshare EPD or Pimoroni Inky Impression). It includes a FastAPI web server for configuration and browser preview. Rendering is based on **Pillow** (`PillowEinkRenderer`): all graphics are generated in native Python without a browser. The image goes through a Pillow post-processor (`EinkRenderer`) and is sent to the panel via SPI; on a non-Pi machine the app runs in web-server-only mode (browser preview). The design follows the typographic aesthetic of the *Wall Street Journal*: no shadows, no rounded corners, no animations.

---

## Stack and Versions

| Component | Technology |
|---|---|
| Python | 3.11+ |
| Web server | FastAPI + Uvicorn |
| HTML templates | Jinja2 (only `/config` and browser preview) |
| Calendar rendering | Native Pillow (`PillowEinkRenderer`) — no browser |
| E-ink post-processing | `EinkRenderer` — resize, palette quantization, Floyd-Steinberg dithering |
| CalDAV | `caldav` + `icalendar` |
| Config | YAML + Pydantic v2 |
| E-ink display | Waveshare EPD / Pimoroni Inky (dynamic import) |
| Target hardware | Raspberry Pi 3B+ / 4 / 5 |
| Target OS | Raspberry Pi OS Lite Bookworm 64-bit |

---

## Code Conventions

### Python

- Style: strict **PEP 8**; formatting with `black` (line length 100)
- Type hints required on all public functions
- Docstrings only on non-obvious public classes and methods (Google style)
- Use `pathlib.Path` instead of `os.path` for all file paths
- Use standard `logging` (not `print`) for runtime diagnostics
- Explicit exception handling: do not use naked `except Exception` — catch specific types
- Configuration always validated through **Pydantic v2** models in `app/config.py`

### Security

- Credentials (CalDAV passwords, secret iCal URLs) must never appear in logs, API output, or error messages
- **`GET /config`** clears all passwords via `_safe_config_dict` (including `server.auth_password`) — no credentials are returned in plaintext
- **`GET /api/config/download`** returns sanitized YAML — no secrets leave the device via HTTP
- The `/config`, `/api/config/*`, `/api/pictures*`, and `/api/test-*` routes are protected by **optional Basic Auth**: if `server.auth_username` and `server.auth_password` are set, a constant-time comparison (`secrets.compare_digest`) blocks unauthenticated access. Preview routes (`/`, `/preview.png`, `/preview-eink.png`) remain always open
- **Picture-folder routes enforce folder containment and image-only content**: every `/api/pictures*` operation resolves the named file through `safe_picture_path` (in `app/server/pictures.py`), which rejects `..`, separators, absolute paths, dotfiles, and symlink escapes; uploads are validated as real images via Pillow. Never serve raw folder files — list rows and previews use PIL-downscaled thumbnails
- The YAML config file must always have `600` permissions on the device (checked/corrected by `_check_file_permissions` in `config.py`)
- Use Apple App-Specific Passwords for iCloud — never the Apple ID password directly
- No hardcoded secrets in source code

### Imports and Dependencies

- Waveshare libraries **must** be imported dynamically, guarded by `display.type == "eink"` — the code must run on macOS/Linux without hardware libraries
- Pillow is the primary renderer (`PillowEinkRenderer`) for both displays; `EinkRenderer` is only e-ink post-processing
- Jinja2 HTML templates are used **only** for the `/config` page and browser preview (`GET /`) — not for calendar rendering
- HTMX is included as a local asset in `base.html` — it is not a pip package and must not be added to `requirements.txt`

---

## Architecture — Invariant Rules

1. **Unified rendering pipeline**: `PillowEinkRenderer` is the single rendering source — `render(state, events)` → `PIL.Image` consumed by the e-ink loop and the browser preview. No browser or Chromium process is started.
2. **EinkRenderer** is post-processing only: it receives an already-composited `PIL.Image` and applies palette quantization + Floyd-Steinberg dithering.
3. **FastAPI serves only preview and configuration**, never calendar rendering via HTML/CSS. Actual routes: `GET /` (minimal HTML page with auto-refresh `<img src="/preview.png">`), `GET /preview.png` (calls `PillowEinkRenderer.render()` on-demand), `GET /preview-eink.png` (preview with e-ink palette quantization), `GET`/`POST /config`, `POST /api/test-weather`, `POST /api/test-connection`, `POST /api/test-artwork` (dry-run query preview), `GET /api/config/download`, `POST /api/config/upload`, and the picture-folder management routes `GET /api/pictures`, `GET /api/pictures/thumbnail`, `POST /api/pictures/upload`, `POST /api/pictures/rename`, `POST /api/pictures/delete` (mutate `pictures/` on disk only — no YAML write, no reload).
4. **Graceful reload**: `POST /config` saves the YAML file and sends SIGHUP to the process (`_reload_config` in `main.py`) — do not terminate the process abruptly. The reload rebuilds config, aggregator, weather provider, `PillowEinkRenderer`, and `EinkRenderer`; the display is **not** restarted.
5. **Single Home view, anchored to today**: the interface is a single screen (weather banner · mini-calendar · agenda · footer). No navigation, pagination, or scroll exists; no `StateManager` or `/state` route exists. `NavigationState` is an immutable dataclass with the single field `anchor_date = date.today()`, recreated on every render.
6. **Physical buttons and keys**: on e-ink Pimoroni Inky Impression all four buttons are used; the mapping depends on `display.rotation` (a 180°/270° flip swaps A↔D and B↔C so each role keeps its physical position): **standard (0°/90°)**: A = return to planner, B = artwork (privacy), C = slideshow toggle, D = shutdown; **inverted (180°/270°)**: A = shutdown, C = artwork (privacy), B = slideshow toggle, D = return to planner. The mapping is the pure function `resolve_button_roles(rotation)` in `app/display/buttons.py`, computed once at startup from `config.display.rotation` (`InkyButtonHandler` → callbacks in `main.py`). All four GPIO lines (A=BCM5, B=BCM6, C=BCM16, D=BCM24) are requested together; on the `inky_impression_13` button C is BCM25 (no conflict). Because BCM16 doubles as SPI CS1, `InkyButtonHandler._listen` requests the full set first and, if that fails, **falls back to A/B/D only** — a CS1 conflict disables the slideshow button alone, never planner/artwork/shutdown. Slideshow (button C) is meaningful only inside artwork mode; toggling it advances images on the `artwork.slideshow_interval_minutes` cadence and auto-stops when leaving artwork mode or shutting down. Physical Inky buttons are the only interaction method. No dependency on Playwright or DOM clicks.
7. **Components with explicit bounds**: each `_draw_*` in `PillowEinkRenderer` receives its own `rect: Rect` as a parameter. The **`Rect` partition calculation** (subdivision of `W × H` across banner/calendar/agenda/footer, for portrait and landscape layouts) happens **only** in `render()`. The `_draw_*` methods may read `self._layout` and sub-component constants (e.g. `BANNER_MAIN_HEIGHT`, `BANNER_HOURLY_HEIGHT`) to position internal elements, but must not recalculate the global partition.

---

## Design System — Constraints for Templates and Renderer

- **Units in the renderer**: use only integer `px` — no `rem`, `em`, or unrounded float values (physical display at fixed resolution)
- **No shadows**: `box-shadow`, `text-shadow`, and `drop-shadow` are forbidden (including on `/config` pages)
- **No border-radius**: `border-radius: 0` everywhere
- **No transitions or animations**: updates are instantaneous
- **Fonts**: Playfair Display (headings) · IBM Plex Sans (body) · IBM Plex Mono (times)
- **Icons**: Tabler Icons SVG outline, `stroke-width: 1.5px`, always `currentColor`
- **Palette**: 9 values defined in `docs/design.md` — do not introduce new colors without updating the doc

---

## Development Workflow

### Local Start

```bash
source .venv/bin/activate
python app/main.py --config config/config.yaml
```

On macOS/Linux (non-Pi) the app runs in web-server-only mode — use the browser preview at `/` for development.

### Deploy to Raspberry Pi

```bash
./scripts/deploy.sh pi@<ip>           # copies files via SSH
./scripts/setup-autostart.sh pi@<ip> # registers the systemd service
```

### Before Every Change

1. Read the source file before editing it
2. Verify that changes to `PillowEinkRenderer` produce visually correct output — take screenshots via `GET /preview.png` (canvas size is derived from `eink_model` + `rotation`)
3. Validate config schema changes against the Pydantic models in `app/config.py`

### After Every Critical Change

If the change touches architecture, data flow, config schema, API routes, design system, or deploy, update **in the same work session**:

- `docs/architecture.md` — if structure, components, flow, or routes change
- `docs/design.md` — if palette, typography, layout, or design system changes
- `config/default.yaml` — if the configuration schema changes
- `AGENTS.md` — if invariant rules, routes, or the interaction model (buttons/keys) change
- `README.md` — if user-facing features, configuration, or startup change

Never close a critical task leaving documentation out of sync with the code. `docs/architecture.md` is the source of truth: if it diverges from the code, align it in the same session rather than creating a copy.

---

## Reference Documentation

| File | Contents |
|---|---|
| `docs/architecture.md` | Stack, project structure, application flow, web routes |
| `docs/design.md` | Typography, palette, layout, screens, interactions |
| `docs/0.X.0-devplan.md` | Per-version development plans (the latest describes current/planned work) |
| `config/default.yaml` | Configuration schema with default values |
| `systemd/family-planner.service` | systemd service unit file |
