from __future__ import annotations

import logging
import os
import signal
import threading
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import yaml
from fastapi import APIRouter, Depends, File, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import ValidationError

from app.calendar.caldav_provider import CalDavProvider
from app.calendar.ical_provider import IcalProvider
from app.config import AppConfig, ArtworkConfig, CalendarConfig, WeatherConfig
from app.renderer.components.artwork import (
    ARTWORK_QUERY_DEFAULT,
    resolve_artwork_folder,
)
from app.renderer.eink_renderer import EINK_RESOLUTIONS
from app.server import pictures as picture_service
from app.server.auth import require_config_auth

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_config_dict(config: AppConfig) -> dict:
    """Return a model_dump() dict with all CalDAV passwords and auth_password scrubbed."""
    data = config.model_dump()
    for cal in data.get("calendars", []):
        # Never return the real password — always clear it in GET responses.
        cal["password"] = ""
    # Never expose the web-access password.
    data["server"]["auth_password"] = ""
    return data


def _current_time() -> str:
    return datetime.now().strftime("%H:%M")


def _parse_config_form(form: Any, existing: AppConfig) -> dict:
    """Parse flat multidict form data into a nested config dict.

    Calendar fields are submitted as repeated names (parallel lists):
    cal_name, cal_type, cal_color, cal_url, cal_username, cal_password, cal_path.
    An empty password field preserves the existing password for that calendar index.
    """

    def _str(key: str, default: str = "") -> str:
        val = form.get(key)
        return str(val).strip() if val is not None else default

    def _int(key: str, default: int) -> int:
        try:
            return int(form.get(key, default))
        except (ValueError, TypeError):
            return default

    def _bool(key: str) -> bool:
        val = form.get(key)
        return val is not None and str(val).lower() not in ("", "false", "0", "off")

    def _float(key: str, default: float) -> float:
        try:
            return float(form.get(key, default))
        except (ValueError, TypeError):
            return default

    cal_names = form.getlist("cal_name")
    cal_types = form.getlist("cal_type")
    cal_colors = form.getlist("cal_color")
    cal_urls = form.getlist("cal_url")
    cal_usernames = form.getlist("cal_username")
    cal_passwords = form.getlist("cal_password")
    cal_paths = form.getlist("cal_path")

    def _list_get(lst: list, i: int, default: str = "") -> str:
        return str(lst[i]).strip() if i < len(lst) else default

    calendars = []
    for i, raw_name in enumerate(cal_names):
        name = raw_name.strip()
        if not name:
            continue

        cal_type = _list_get(cal_types, i, "ics")
        color = _list_get(cal_colors, i, "#4A90D9") or "#4A90D9"
        url = _list_get(cal_urls, i) or None
        username = _list_get(cal_usernames, i) or None
        path = _list_get(cal_paths, i) or None

        # Preserve existing password if the submitted field is blank.
        submitted_pw = _list_get(cal_passwords, i)
        if submitted_pw:
            password: str | None = submitted_pw
        else:
            existing_cal = existing.calendars[i] if i < len(existing.calendars) else None
            password = existing_cal.password if existing_cal else None

        calendars.append(
            {
                "name": name,
                "type": cal_type,
                "color": color,
                "url": url,
                "username": username,
                "password": password,
                "path": path,
            }
        )

    existing_quiet = existing.refresh.quiet_hours
    quiet_enabled = _bool("quiet_enabled")
    quiet_start = _str("quiet_start") or existing_quiet.start
    quiet_end = _str("quiet_end") or existing_quiet.end
    quiet_midnight_update = _bool("quiet_midnight_update")

    # Gli orari di repaint notturni non dipendono dai confini della fascia: il
    # sigillo resta al proprio orario anche se l'inizio viene spostato, e la
    # mezzanotte è governata dalla sola casella "cambio data". L'unica voce che
    # il form controlla è "00:00"; le altre (il sigillo) si riportano invariate,
    # perché non sono esposte.
    allowed_ticks = [t for t in existing_quiet.allowed_ticks if t != "00:00"]
    if quiet_midnight_update:
        allowed_ticks.append("00:00")

    return {
        "server": {
            "host": _str("server_host", "0.0.0.0"),
            "port": _int("server_port", 8080),
            "auth_username": _str("server_auth_username") or None,
            "auth_password": _str("server_auth_password") or existing.server.auth_password,
        },
        "display": {
            "layout": _str("display_layout", "landscape"),
            "show_buttons": _bool("display_show_buttons"),
            "eink_model": _str("display_eink_model", "7in5_V2"),
            "eink_palette": _str("display_eink_palette", "bw"),
            "eink_dither": _bool("display_eink_dither"),
            "eink_saturation": _float("display_eink_saturation", existing.display.eink_saturation),
            "rotation": _int("display_rotation", 0),
        },
        "weather": {
            "enabled": _bool("weather_enabled"),
            "latitude": _float("weather_latitude", 45.4654),
            "longitude": _float("weather_longitude", 9.1866),
            "units": _str("weather_units", "celsius"),
        },
        "artwork": {
            "query": _str("artwork_query", "landscape painting") or "landscape painting",
            "source": _str("artwork_source", existing.artwork.source) or "endpoint",
            "folder": existing.artwork.folder,
            "slideshow_interval_minutes": _int(
                "artwork_slideshow_interval", existing.artwork.slideshow_interval_minutes
            ),
        },
        # Le cadenze di aggiornamento (display/calendar/push) non sono esposte
        # nel form: si riportano invariate, altrimenti ogni salvataggio dal web
        # le riazzererebbe ai default silenziosamente.
        "refresh": {
            "display_interval_minutes": existing.refresh.display_interval_minutes,
            "calendar_poll_minutes": existing.refresh.calendar_poll_minutes,
            "min_push_interval_minutes": existing.refresh.min_push_interval_minutes,
            "quiet_hours": {
                "enabled": quiet_enabled,
                "start": quiet_start,
                "end": quiet_end,
                "allowed_ticks": allowed_ticks,
            },
        },
        "calendars": calendars,
        "timezone": _str("timezone", existing.timezone) or existing.timezone,
    }


def _deferred_sighup(delay: float = 0.3) -> None:
    """Send SIGHUP to the current process after a short delay.

    The delay allows the HTTP 303 response to be sent before uvicorn begins
    its graceful reload sequence.
    """
    import time

    def _send() -> None:
        time.sleep(delay)
        os.kill(os.getpid(), signal.SIGHUP)

    threading.Thread(target=_send, daemon=True).start()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/config", response_class=HTMLResponse, dependencies=[Depends(require_config_auth)])
async def config_get(
    request: Request, saved: bool = False, error: str | None = None
) -> HTMLResponse:
    templates = request.app.state.templates
    config: AppConfig = request.app.state.config

    return templates.TemplateResponse(
        "config.html",
        {
            "request": request,
            "view_title": "Configurazione",
            "current_time": _current_time(),
            "config": _safe_config_dict(config),
            "eink_resolutions": EINK_RESOLUTIONS,
            "display_resolution": config.display.resolution,
            "saved": saved,
            "error": error,
        },
    )


@router.post("/config", response_model=None, dependencies=[Depends(require_config_auth)])
async def config_post(request: Request):
    templates = request.app.state.templates
    existing_config: AppConfig = request.app.state.config
    config_path: Path = request.app.state.config_path

    form = await request.form()

    try:
        new_data = _parse_config_form(form, existing_config)
        new_config = AppConfig.model_validate(new_data)
    except (ValidationError, ValueError) as exc:
        logger.warning("Config POST validation failed: %s", exc)
        return templates.TemplateResponse(
            "config.html",
            {
                "request": request,
                "view_title": "Configurazione",
                "current_time": _current_time(),
                "config": _safe_config_dict(existing_config),
                "eink_resolutions": EINK_RESOLUTIONS,
                "display_resolution": existing_config.display.resolution,
                "saved": False,
                "error": str(exc),
            },
            status_code=422,
        )

    # Persist to disk.
    config_path.write_text(
        yaml.dump(new_config.model_dump(), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    # Update in-memory config.
    request.app.state.config = new_config

    # Trigger uvicorn graceful reload (deferred so the 303 response is sent first).
    _deferred_sighup()

    return RedirectResponse(url="/config?saved=1", status_code=303)


@router.post("/api/test-weather", dependencies=[Depends(require_config_auth)])
async def test_weather(request: Request) -> JSONResponse:
    """Test connectivity to Open-Meteo and return current conditions."""
    form = await request.form()
    try:
        lat = float(form.get("latitude", 45.4654))
        lon = float(form.get("longitude", 9.1866))
        units = str(form.get("units", "celsius")).strip()
    except (TypeError, ValueError):
        return JSONResponse({"ok": False, "message": "Coordinate non valide."})

    from app.weather.open_meteo import OpenMeteoProvider

    provider = OpenMeteoProvider(latitude=lat, longitude=lon, units=units)
    data = provider._fetch()
    if data is None:
        return JSONResponse(
            {"ok": False, "message": "Nessuna risposta da Open-Meteo. Verificare la connessione di rete."}
        )
    unit_sym = "\u00b0C" if units == "celsius" else "\u00b0F"
    msg = (
        f"{data.description}, "
        f"{data.temp_current:.0f}{unit_sym} "
        f"(\u2191{data.temp_max:.0f} \u2193{data.temp_min:.0f})"
    )
    return JSONResponse({"ok": True, "message": msg})


@router.get("/api/config/download", dependencies=[Depends(require_config_auth)])
async def config_download(request: Request) -> Response:
    """Return a sanitized config YAML as a download (passwords scrubbed)."""
    config: AppConfig = request.app.state.config
    safe = _safe_config_dict(config)
    body = yaml.dump(safe, allow_unicode=True, sort_keys=False)
    return Response(
        content=body,
        media_type="application/x-yaml",
        headers={"Content-Disposition": 'attachment; filename="config.yaml"'},
    )


@router.post("/api/config/upload", response_model=None, dependencies=[Depends(require_config_auth)])
async def config_upload(request: Request, file: UploadFile = File(...)):
    """Upload a YAML config file, validate it, and apply it."""
    config_path: Path = request.app.state.config_path

    content = await file.read()
    try:
        raw = yaml.safe_load(content)
        if not isinstance(raw, dict):
            raise ValueError("Il file non contiene un documento YAML valido.")
        new_config = AppConfig.model_validate(raw)
    except (ValidationError, ValueError, yaml.YAMLError) as exc:
        short_msg = str(exc).splitlines()[0][:200]
        logger.warning("Config upload validation failed: %s", exc)
        return RedirectResponse(
            url=f"/config?error={quote_plus(short_msg)}", status_code=303
        )

    # Persist to disk.
    config_path.write_text(
        yaml.dump(new_config.model_dump(), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    # Update in-memory config.
    request.app.state.config = new_config

    # Trigger uvicorn graceful reload.
    _deferred_sighup()

    return RedirectResponse(url="/config?saved=1", status_code=303)


@router.post("/api/test-connection", dependencies=[Depends(require_config_auth)])
async def test_connection(request: Request) -> JSONResponse:
    """Test connectivity for caldav or ical calendar providers.

    The submitted password is never logged.
    """
    form = await request.form()
    cal_type = str(form.get("type", "caldav")).strip()
    url = str(form.get("url", "")).strip()
    username = str(form.get("username", "")).strip()
    password = str(form.get("password", "")).strip() or None

    if not url:
        return JSONResponse({"ok": False, "message": "URL obbligatorio."})

    if cal_type == "ical":
        temp_config = CalendarConfig(
            name="_test",
            type="ical",
            url=url,
        )
        provider: CalDavProvider | IcalProvider = IcalProvider(temp_config)
        ok = provider.test_connection()
        message = "Feed iCal raggiungibile." if ok else "Impossibile raggiungere il feed iCal."
        return JSONResponse({"ok": ok, "message": message})

    # Default: caldav
    if not username:
        return JSONResponse(
            {"ok": False, "message": "URL e username sono obbligatori."}
        )

    temp_config = CalendarConfig(
        name="_test",
        type="caldav",
        url=url,
        username=username,
        password=password,
    )
    caldav_provider = CalDavProvider(temp_config)
    ok = caldav_provider.test_connection()
    message = "Connessione riuscita." if ok else "Connessione al server CalDAV fallita."
    return JSONResponse({"ok": ok, "message": message})


# ---------------------------------------------------------------------------
# Pictures folder management
#
# These endpoints mutate the local artwork folder on disk only. They never
# rewrite the config YAML and never trigger a reload (no SIGHUP): the renderer
# rescans the folder on every render, so picture changes are picked up on the
# next artwork frame. Do not "helpfully" add a reload here.
#
# Every operation that names a file goes through picture_service.safe_picture_path
# (via the service functions), which confines the path inside the configured
# folder; PictureError is caught and returned as a short Italian message.
# ---------------------------------------------------------------------------


def _artwork_folder(request: Request) -> Path:
    """Resolve the configured artwork folder to an absolute path."""
    config: AppConfig = request.app.state.config
    return resolve_artwork_folder(config.artwork.folder)


@router.get("/api/pictures", dependencies=[Depends(require_config_auth)])
async def list_pictures(request: Request) -> JSONResponse:
    """List the image files in the configured artwork folder."""
    folder = _artwork_folder(request)
    pics = picture_service.list_pictures(folder)
    return JSONResponse({"ok": True, "folder": str(folder), "pictures": pics})


@router.get("/api/pictures/thumbnail", dependencies=[Depends(require_config_auth)])
async def picture_thumbnail(request: Request, name: str) -> Response:
    """Return a PIL-downscaled JPEG thumbnail for one folder image.

    Never streams the raw (multi-megabyte) file. ``Cache-Control: no-store``
    because names are reused after rename — a cached thumbnail could go stale.
    """
    folder = _artwork_folder(request)
    try:
        path = picture_service.safe_picture_path(folder, name)
        if not path.is_file():
            raise picture_service.PictureError("File inesistente.")
        data = picture_service.thumbnail_bytes(path)
    except picture_service.PictureError as exc:
        logger.warning("picture_thumbnail rejected %r: %s", name, exc)
        return JSONResponse({"ok": False, "message": str(exc)}, status_code=404)
    except Exception:  # noqa: BLE001
        logger.exception("picture_thumbnail failed for %r", name)
        return JSONResponse(
            {"ok": False, "message": "Impossibile generare l'anteprima."},
            status_code=500,
        )
    return Response(
        content=data,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/api/pictures/upload", dependencies=[Depends(require_config_auth)])
async def picture_upload(request: Request, file: UploadFile = File(...)) -> JSONResponse:
    """Upload one image into the artwork folder (validated as a real image)."""
    folder = _artwork_folder(request)
    data = await file.read()
    try:
        name = picture_service.save_upload(folder, file.filename or "", data)
    except picture_service.PictureError as exc:
        logger.warning("picture_upload rejected %r: %s", file.filename, exc)
        return JSONResponse({"ok": False, "message": str(exc)}, status_code=400)
    return JSONResponse({"ok": True, "name": name})


@router.post("/api/pictures/rename", dependencies=[Depends(require_config_auth)])
async def picture_rename(request: Request) -> JSONResponse:
    """Rename a file within the artwork folder."""
    folder = _artwork_folder(request)
    form = await request.form()
    old = str(form.get("old", "")).strip()
    new = str(form.get("new", "")).strip()
    try:
        name = picture_service.rename_picture(folder, old, new)
    except picture_service.PictureError as exc:
        logger.warning("picture_rename rejected %r->%r: %s", old, new, exc)
        return JSONResponse({"ok": False, "message": str(exc)}, status_code=400)
    return JSONResponse({"ok": True, "name": name})


@router.post("/api/pictures/delete", dependencies=[Depends(require_config_auth)])
async def picture_delete(request: Request) -> JSONResponse:
    """Delete a file from the artwork folder."""
    folder = _artwork_folder(request)
    form = await request.form()
    name = str(form.get("name", "")).strip()
    try:
        picture_service.delete_picture(folder, name)
    except picture_service.PictureError as exc:
        logger.warning("picture_delete rejected %r: %s", name, exc)
        return JSONResponse({"ok": False, "message": str(exc)}, status_code=400)
    return JSONResponse({"ok": True})


@router.post("/api/test-artwork", dependencies=[Depends(require_config_auth)])
async def test_artwork(request: Request) -> JSONResponse:
    """Dry-run: fetch one artwork for the submitted query and return a preview.

    Does not touch config or the display. Returns the caption and a small base64
    PNG data URI so the UI can show it inline. The blocking network fetch runs in
    a worker thread so it never blocks the event loop.
    """
    import anyio

    config: AppConfig = request.app.state.config
    form = await request.form()
    query = str(form.get("query", "")).strip() or ARTWORK_QUERY_DEFAULT

    # Preview size: keep the display aspect ratio but cap the width so the fetch
    # stays small/fast — a full-panel image is unnecessary for a thumbnail.
    disp_w, disp_h = config.display.resolution
    preview_w = min(disp_w, 640)
    preview_h = max(1, round(disp_h * preview_w / disp_w))

    from app.renderer.components.artwork import fetch_artwork

    try:
        result = await anyio.to_thread.run_sync(
            lambda: fetch_artwork(preview_w, preview_h, query, eink_enhance=False)
        )
    except Exception:  # noqa: BLE001
        logger.exception("test_artwork: fetch failed for query %r", query)
        return JSONResponse(
            {"ok": False, "message": "Errore durante il recupero dell'artwork."}
        )

    if result is None:
        return JSONResponse(
            {"ok": False, "message": "Nessun artwork trovato per questa query."}
        )

    import base64
    import io

    image, caption = result
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    data_uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    return JSONResponse({"ok": True, "caption": caption, "image": data_uri})
