from __future__ import annotations
import logging
import stat
from datetime import time as _time
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, ValidationError, field_validator, model_validator

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


def _parse_hhmm(value: str, field_name: str) -> _time:
    """Parse ``"HH:MM"`` into a :class:`datetime.time`, raising on bad input."""
    try:
        hour_s, minute_s = value.split(":")
        return _time(hour=int(hour_s), minute=int(minute_s))
    except (AttributeError, ValueError) as exc:
        raise ValueError(
            f"{field_name} must be a time in 'HH:MM' format (got {value!r})"
        ) from exc


class QuietHoursConfig(BaseModel):
    """Fascia notturna in cui i repaint del pannello sono sospesi.

    L'e-ink mantiene l'immagine senza alimentazione, quindi durante la notte
    non ridipingere non costa nulla in leggibilità ed evita il lampeggio.
    ``start`` è incluso e ``end`` escluso; la fascia può attraversare la
    mezzanotte (default ``23:00``–``06:00``).

    ``allowed_ticks`` elenca gli orari a cui il pannello si ridipinge comunque
    durante la notte. La mezzanotte è necessaria per il cambio di data: senza di
    essa il pannello mostrerebbe la data di ieri fino al mattino; il sigillo
    (default ``23:00``) è l'ultimo repaint prima della notte.

    Non sono vincolati a cadere dentro ``[start, end)``: valgono al proprio
    orario, così spostare l'inizio della fascia non fa sparire il sigillo. Sono
    però legati a ``enabled``: a fascia disattivata non c'è notte da sigillare e
    vale la sola griglia display.
    """

    enabled: bool = True
    start: str = "23:00"
    end: str = "06:00"
    allowed_ticks: list[str] = ["23:00", "00:00"]

    @field_validator("start", "end")
    @classmethod
    def _validate_bounds(cls, v: str, info) -> str:  # noqa: ANN001
        _parse_hhmm(v, f"quiet_hours.{info.field_name}")
        return v

    @field_validator("allowed_ticks")
    @classmethod
    def _validate_ticks(cls, v: list[str]) -> list[str]:
        for tick in v:
            _parse_hhmm(tick, "quiet_hours.allowed_ticks")
        return v

    @model_validator(mode="after")
    def _validate_band_bounds(self) -> "QuietHoursConfig":
        """Gli estremi della fascia devono differire.

        Gli orari di ``allowed_ticks`` non sono invece vincolati alla fascia:
        valgono al proprio orario. Il sigillo è *l'ultimo repaint prima della
        notte* e resta tale anche se cade poco prima dell'inizio fascia — legarlo
        ai confini lo farebbe sparire ogni volta che si sposta l'orario di inizio.
        """
        if not self.enabled:
            return self
        if self.start_time == self.end_time:
            raise ValueError(
                "quiet_hours.start and quiet_hours.end must differ "
                "(set enabled: false to disable the quiet band)"
            )
        return self

    @property
    def start_time(self) -> _time:
        return _parse_hhmm(self.start, "quiet_hours.start")

    @property
    def end_time(self) -> _time:
        return _parse_hhmm(self.end, "quiet_hours.end")

    @property
    def allowed_tick_times(self) -> tuple[_time, ...]:
        return tuple(
            _parse_hhmm(t, "quiet_hours.allowed_ticks") for t in self.allowed_ticks
        )


class RefreshConfig(BaseModel):
    """Cadenze di aggiornamento — vedi ``app/scheduling.py`` per la politica.

    ``display_interval_minutes`` è la griglia dei repaint, allineata alla
    mezzanotte: il default di 120 minuti coincide con la finestra di previsione
    bioraria del meteo, così che il pannello si aggiorni esattamente quando il
    contenuto cambia.

    ``calendar_poll_minutes`` governa solo il *fetch* di rete, non il repaint:
    una modifica al calendario provoca un push dedicato (soggetto a
    ``min_push_interval_minutes``), un calendario invariato non ne provoca
    nessuno.
    """

    display_interval_minutes: int = 120
    calendar_poll_minutes: int = 15
    min_push_interval_minutes: int = 20
    quiet_hours: QuietHoursConfig = QuietHoursConfig()

    @field_validator("display_interval_minutes")
    @classmethod
    def _validate_display_interval(cls, v: int) -> int:
        if v < 1 or 1440 % v:
            raise ValueError(
                "display_interval_minutes must be a positive divisor of 1440 "
                f"so the grid stays aligned to midnight (got {v})"
            )
        return v

    @field_validator("calendar_poll_minutes")
    @classmethod
    def _validate_poll_interval(cls, v: int) -> int:
        if v < 1 or 60 % v:
            raise ValueError(
                "calendar_poll_minutes must be a positive divisor of 60 so the "
                f"poll boundaries stay aligned to the hour (got {v})"
            )
        return v

    @field_validator("min_push_interval_minutes")
    @classmethod
    def _validate_cooldown(cls, v: int) -> int:
        if v < 0:
            raise ValueError("min_push_interval_minutes must be >= 0")
        return v


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
    # Minutes between automatic image changes when slideshow mode is active
    # (toggled by button C while in artwork mode). Must be >= 1.
    slideshow_interval_minutes: int = 30

    @field_validator("slideshow_interval_minutes")
    @classmethod
    def _validate_interval(cls, v: int) -> int:
        if v < 1:
            raise ValueError("slideshow_interval_minutes must be >= 1")
        return v


class AppConfig(BaseModel):
    server: ServerConfig = ServerConfig()
    display: DisplayConfig = DisplayConfig()
    calendars: list[CalendarConfig] = []
    weather: WeatherConfig = WeatherConfig()
    artwork: ArtworkConfig = ArtworkConfig()
    refresh: RefreshConfig = RefreshConfig()
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
