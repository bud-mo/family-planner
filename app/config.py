from __future__ import annotations
import logging
import stat
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, ValidationError, field_validator

logger = logging.getLogger(__name__)


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8080
    # Basic Auth opzionale sulle rotte /config e /api/config/*.
    # Se entrambi None → rotte aperte (con warning all'avvio se host non è loopback).
    auth_username: str | None = None
    auth_password: str | None = None


class DisplayConfig(BaseModel):
    layout: Literal["portrait", "landscape"] = "landscape"
    show_buttons: bool = False      # browser-preview navigation overlay only
    eink_model: str = "7in5_V2"
    eink_palette: Literal["bw", "bwr", "4gray", "spectra6"] = "bw"
    eink_dither: bool = True
    eink_saturation: float = 0.5
    rotation: Literal[0, 90, 180, 270] = 0

    @field_validator("eink_model")
    @classmethod
    def validate_eink_model(cls, v: str) -> str:
        from app.renderer.eink_renderer import EINK_RESOLUTIONS

        if v not in EINK_RESOLUTIONS:
            raise ValueError(
                f"Unknown eink_model: {v!r}. Supported models: "
                f"{', '.join(sorted(EINK_RESOLUTIONS))}."
            )
        return v

    @property
    def resolution(self) -> tuple[int, int]:
        """Canvas (width, height) derived from the panel model and rotation.

        For a 90°/270° rotation the rendered image must fit the panel in
        transposed orientation, so width and height are swapped.
        """
        from app.renderer.eink_renderer import EINK_RESOLUTIONS

        w, h = EINK_RESOLUTIONS[self.eink_model]
        if self.rotation in (90, 270):
            w, h = h, w
        return w, h


class CalendarConfig(BaseModel):
    name: str
    type: Literal["caldav", "ics", "ical"]
    color: str = "#4A90D9"
    # caldav fields
    url: str | None = None
    username: str | None = None
    password: str | None = None
    # ics fields
    path: str | None = None


class WeatherConfig(BaseModel):
    enabled: bool = False
    latitude: float = 45.4654
    longitude: float = 9.1866
    units: Literal["celsius", "fahrenheit"] = "celsius"


_ARTWORK_QUERY_DEFAULT: str = "landscape painting"


class ArtworkConfig(BaseModel):
    query: str = _ARTWORK_QUERY_DEFAULT
    # "endpoint" → fetch a random painting from the ARTIC API using `query`.
    # "folder"   → show images from the local `pictures/` folder, in alphabetical
    #              order, advancing to the next one on each button press.
    source: Literal["endpoint", "folder"] = "endpoint"
    # Folder scanned in "folder" mode. Relative paths are resolved against the
    # project root.
    folder: str = "pictures"


class AppConfig(BaseModel):
    server: ServerConfig = ServerConfig()
    display: DisplayConfig = DisplayConfig()
    calendars: list[CalendarConfig] = []
    weather: WeatherConfig = WeatherConfig()
    artwork: ArtworkConfig = ArtworkConfig()
    timezone: str = "Europe/Rome"

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        if v == "local":
            return v
        try:
            ZoneInfo(v)
        except (KeyError, ZoneInfoNotFoundError):
            raise ValueError(
                f"Unknown timezone: {v!r}. "
                "Use an IANA name (e.g. 'Europe/Rome') or 'local' for the system timezone."
            )
        return v


def _check_file_permissions(path: Path) -> None:
    """Warn if the config file permissions are too open (not 600)."""
    try:
        file_stat = path.stat()
        mode = file_stat.st_mode & 0o777
        if mode != 0o600:
            try:
                path.chmod(0o600)
                logger.warning(
                    "Config file permissions were %s, corrected to 600: %s",
                    oct(mode),
                    path,
                )
            except OSError as exc:
                logger.warning(
                    "Config file permissions are %s (expected 600), could not correct: %s — %s",
                    oct(mode),
                    path,
                    exc,
                )
    except OSError as exc:
        logger.warning("Could not check permissions for config file %s: %s", path, exc)


def load_config(path: Path) -> AppConfig:
    """Load and validate the application configuration from a YAML file.

    If the file does not exist, it is created with default values and permissions 600.

    Args:
        path: Path to the YAML configuration file.

    Returns:
        Validated AppConfig instance.

    Raises:
        OSError: If the config file does not exist and cannot be created.
        ValueError: If the YAML is malformed.
        pydantic.ValidationError: If the config schema is invalid.
    """
    path = Path(path)

    if not path.exists():
        logger.warning("Configuration file not found at %s — creating with defaults.", path)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            defaults = AppConfig()
            path.write_text(
                yaml.dump(defaults.model_dump(mode="json"), default_flow_style=False, allow_unicode=True),
                encoding="utf-8",
            )
            path.chmod(0o600)
            logger.info("Default configuration written to %s", path)
        except OSError as exc:
            raise OSError(
                f"Configuration file not found and could not be created at {path}: {exc}"
            ) from exc

    _check_file_permissions(path)

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"Malformed YAML in configuration file {path}: {exc}") from exc

    if raw is None:
        raw = {}

    if isinstance(raw, dict) and isinstance(raw.get("display"), dict):
        _legacy = [k for k in ("type", "width", "height", "fullscreen") if k in raw["display"]]
        if _legacy:
            logger.warning(
                "HDMI support was removed in v0.7.0 — the e-ink panel is now the "
                "only output. Ignoring obsolete display field(s) %s in %s; remove "
                "them from the display section.",
                ", ".join(_legacy),
                path,
            )

    try:
        config = AppConfig.model_validate(raw)
    except ValidationError:
        logger.error("Configuration validation failed for file: %s", path)
        raise

    return config
