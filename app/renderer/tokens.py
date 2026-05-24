"""Design tokens for Family Planner renderer.

All values are sourced from docs/design.md and must not deviate from it.
Units are always pixels — no rem/em/viewport units.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Asset paths
# ---------------------------------------------------------------------------

FONTS_DIR: Path = Path(__file__).parent.parent / "assets" / "fonts"
ICONS_DIR: Path = Path(__file__).parent.parent / "assets" / "icons"

# ---------------------------------------------------------------------------
# Font file names (relative to FONTS_DIR)
# ---------------------------------------------------------------------------

FONT_DISPLAY_REGULAR = "PlayfairDisplay-Regular.ttf"
FONT_DISPLAY_BOLD = "PlayfairDisplay-Bold.ttf"
FONT_BODY_REGULAR = "IBMPlexSans-Regular.ttf"
FONT_BODY_SEMIBOLD = "IBMPlexSans-SemiBold.ttf"
FONT_MONO_REGULAR = "IBMPlexMono-Regular.ttf"

# ---------------------------------------------------------------------------
# Typographic scale (px)
# ---------------------------------------------------------------------------

TEXT_XS: int = 11
TEXT_SM: int = 13
TEXT_BASE: int = 15
TEXT_MD: int = 18
TEXT_LG: int = 24
TEXT_XL: int = 32
TEXT_2XL: int = 48

# ---------------------------------------------------------------------------
# Layout structure (px)
# ---------------------------------------------------------------------------

BANNER_MAIN_HEIGHT: int = 90       # fascia superiore con data e meteo corrente
BANNER_HOURLY_HEIGHT: int = 58    # fascia inferiore con previsioni biorarie
BANNER_HEIGHT: int = BANNER_MAIN_HEIGHT + BANNER_HOURLY_HEIGHT  # altezza totale banner (148px)
CALENDAR_HEIGHT: int = 462    # mini-calendario mensile — 4 righe evento per cella su griglie da 6 settimane (solo portrait)
FOOTER_HEIGHT: int = 40
COL_LEFT_RATIO: float = 0.38  # larghezza colonna sinistra in layout landscape

# Tipo geometria componente
Rect = tuple[int, int, int, int]   # (x, y, width, height)


# ---------------------------------------------------------------------------
# Weather data placeholder
# ---------------------------------------------------------------------------


@dataclass
class HourlySlot:
    """Previsione meteo per una fascia oraria di 2 ore."""

    hour: int                            # ora di inizio fascia (0-23, es. 14 → "14:00")
    condition_icon: str | None = None    # nome icona Tabler
    temp: float | None = None            # temperatura prevista (°C)


@dataclass
class WeatherData:
    """Dati meteo per il banner. Tutti i campi sono None in assenza di un provider."""

    condition_icon: str | None = None    # nome icona Tabler (es. "sun", "cloud-rain")
    description: str | None = None       # descrizione testuale (es. "Sereno", "Pioggia")
    temp_current: float | None = None    # temperatura attuale (°C)
    temp_max: float | None = None        # massima giornaliera (°C)
    temp_min: float | None = None        # minima giornaliera (°C)
    hourly_forecast: list[HourlySlot] = field(default_factory=list)  # previsioni biorarie (6 slot)

# ---------------------------------------------------------------------------
# Day palette
# ---------------------------------------------------------------------------

COLOR_BG: str = "#F8F6F0"
COLOR_BG_ALT: str = "#EEECE6"
COLOR_INK: str = "#111111"
COLOR_INK_MUTED: str = "#666666"
COLOR_INK_FAINT: str = "#AAAAAA"
COLOR_ACCENT: str = "#1A1A1A"
COLOR_HOLIDAY: str = "#444444"
COLOR_RULE: str = "#CCCCAA"
COLOR_RULE_STRONG: str = "#333333"

def get_palette() -> dict[str, str]:
    """Return the day colour palette as a flat dictionary.

    Keys use canonical names without the ``COLOR_`` prefix for brevity,
    e.g. ``"BG"``, ``"INK"``, ``"ACCENT"`` …
    """
    return {
        "BG": COLOR_BG,
        "BG_ALT": COLOR_BG_ALT,
        "INK": COLOR_INK,
        "INK_MUTED": COLOR_INK_MUTED,
        "INK_FAINT": COLOR_INK_FAINT,
        "ACCENT": COLOR_ACCENT,
        "HOLIDAY": COLOR_HOLIDAY,
        "RULE": COLOR_RULE,
        "RULE_STRONG": COLOR_RULE_STRONG,
    }
