from __future__ import annotations
import logging
import stat
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8080


class DisplayConfig(BaseModel):
    fullscreen: bool = False
    type: Literal["hdmi", "eink"] = "hdmi"
    width: int = 1920
    height: int = 1080
    width_mm: float | None = None   # physical panel width in mm (enables DPI-aware local window)
    height_mm: float | None = None  # physical panel height in mm
    refresh_interval: int = 300
    eink_model: str = "7in5_V2"
    eink_palette: Literal["bw", "bwr", "4gray"] = "bw"
    eink_dither: bool = True


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


class AppConfig(BaseModel):
    server: ServerConfig = ServerConfig()
    display: DisplayConfig = DisplayConfig()
    calendars: list[CalendarConfig] = []


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

    Args:
        path: Path to the YAML configuration file.

    Returns:
        Validated AppConfig instance.

    Raises:
        FileNotFoundError: If the config file does not exist.
        ValueError: If the YAML is malformed.
        pydantic.ValidationError: If the config schema is invalid.
    """
    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")

    _check_file_permissions(path)

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"Malformed YAML in configuration file {path}: {exc}") from exc

    if raw is None:
        raw = {}

    try:
        config = AppConfig.model_validate(raw)
    except ValidationError:
        logger.error("Configuration validation failed for file: %s", path)
        raise

    return config
