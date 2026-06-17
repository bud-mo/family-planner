"""Unica fonte di verità per tutti i nomi di icone Tabler usati nel progetto.

Aggrega i nomi da:
- app/renderer/emoji_icons.py  (valori di EMOJI_TO_ICON)
- app/weather/open_meteo.py    (valori di WMO_TO_ICON — derivato automaticamente)

Usato da scripts/extract_icons.py per generare app/assets/icons/icons.json,
che a sua volta viene letto da scripts/convert_icons.js con il flag --json.
"""
from __future__ import annotations

from app.renderer.emoji_icons import EMOJI_TO_ICON
from app.weather.open_meteo import _NIGHT_CLEAR_ICON, WMO_TO_ICON

# ---------------------------------------------------------------------------
# Icone meteo — derivate da WMO_TO_ICON in app/weather/open_meteo.py più
# l'icona notturna ("moon") usata al posto del sole per cielo sereno di notte.
# ---------------------------------------------------------------------------
WEATHER_ICONS: frozenset[str] = frozenset(WMO_TO_ICON.values()) | {_NIGHT_CLEAR_ICON}

# ---------------------------------------------------------------------------
# Icone UI — usate direttamente nel renderer (non mappate da emoji)
# ---------------------------------------------------------------------------
UI_ICONS: frozenset[str] = frozenset({
    "caret-up",
})

# ---------------------------------------------------------------------------
# Unione di tutte le icone Tabler usate nel progetto
# ---------------------------------------------------------------------------
ALL_ICONS: frozenset[str] = frozenset(EMOJI_TO_ICON.values()) | WEATHER_ICONS | UI_ICONS

# ---------------------------------------------------------------------------
# Icone per dimensione — unica fonte di verità per la generazione degli asset
#   16px: icone emoji usate nelle righe evento (~12px, caricate da 16px e scalate)
#   24px: icone emoji (fallback generale)
#   40px: solo icone meteo (usate esplicitamente a 40px nel banner meteo)
# ---------------------------------------------------------------------------
ICONS_BY_SIZE: dict[int, frozenset[str]] = {
    16: ALL_ICONS,
    24: ALL_ICONS,
    40: WEATHER_ICONS,
}
