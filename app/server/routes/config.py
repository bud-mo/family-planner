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
from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from pydantic import ValidationError

from app.calendar.caldav_provider import CalDavProvider
from app.calendar.ical_provider import IcalProvider
from app.config import AppConfig, ArtworkConfig, CalendarConfig, WeatherConfig

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_config_dict(config: AppConfig) -> dict:
    """Return a model_dump() dict with all CalDAV passwords scrubbed."""
    data = config.model_dump()
    for cal in data.get("calendars", []):
        # Never return the real password — always clear it in GET responses.
        cal["password"] = ""
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

    return {
        "server": {
            "host": _str("server_host", "0.0.0.0"),
            "port": _int("server_port", 8080),
        },
        "display": {
            "type": _str("display_type", "hdmi"),
            "layout": _str("display_layout", "landscape"),
            "width": _int("display_width", 1920),
            "height": _int("display_height", 1080),
            "fullscreen": _bool("display_fullscreen"),
            "refresh_interval": _int("display_refresh_interval", 300),
            "eink_model": _str("display_eink_model", "7in5_V2"),
            "eink_palette": _str("display_eink_palette", "bw"),
            "eink_dither": _bool("display_eink_dither"),
        },
        "weather": {
            "enabled": _bool("weather_enabled"),
            "latitude": _float("weather_latitude", 45.4654),
            "longitude": _float("weather_longitude", 9.1866),
            "units": _str("weather_units", "celsius"),
        },
        "artwork": {
            "query": _str("artwork_query", "landscape painting") or "landscape painting",
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


@router.get("/config", response_class=HTMLResponse)
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
            "saved": saved,
            "error": error,
        },
    )


@router.post("/config", response_model=None)
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


@router.post("/api/test-weather")
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


@router.get("/api/config/download")
async def config_download(request: Request) -> FileResponse:
    """Return the current config YAML file as a download."""
    config_path: Path = request.app.state.config_path
    return FileResponse(
        path=str(config_path),
        media_type="application/octet-stream",
        filename="config.yaml",
    )


@router.post("/api/config/upload", response_model=None)
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


@router.post("/api/test-connection")
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
