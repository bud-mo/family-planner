"""Cadenze di aggiornamento allineate all'orologio.

Singola fonte di verità per *quando* aggiornare dati e display, usata dal
loop e-ink ([app/main.py]) e dall'anteprima web.

Politica:
- Calendario: ogni ``CALENDAR_INTERVAL_MINUTES`` (quarto d'ora) ai confini
  ``xx:00``, ``xx:15``, ``xx:30``, ``xx:45``.
- Meteo: ogni ora al confine ``xx:00`` (vedi :func:`is_weather_tick`).
- Quando le due cadenze coincidono (``xx:00``) i consumatori eseguono un solo
  ciclo di fetch/valutazione/push.

I confini sono calcolati sull'ora locale (``datetime.now()``), coerente con il
fuso del dispositivo.
"""
from __future__ import annotations

from datetime import datetime, timedelta

# Calendario aggiornato ogni quarto d'ora.
CALENDAR_INTERVAL_MINUTES: int = 15

# Auto-reload dell'anteprima nel browser, allineato alla cadenza del calendario.
WEB_REFRESH_SECONDS: int = CALENDAR_INTERVAL_MINUTES * 60


def floor_to_quarter(now: datetime) -> datetime:
    """Ritorna lo slot di quarto d'ora corrente (secondi/microsecondi azzerati).

    Esempio: ``12:07:30`` → ``12:00:00``; ``12:15:00`` → ``12:15:00``.
    """
    minute = (now.minute // CALENDAR_INTERVAL_MINUTES) * CALENDAR_INTERVAL_MINUTES
    return now.replace(minute=minute, second=0, microsecond=0)


def next_calendar_tick(now: datetime) -> datetime:
    """Ritorna il prossimo confine di quarto d'ora strettamente successivo a *now*."""
    return floor_to_quarter(now) + timedelta(minutes=CALENDAR_INTERVAL_MINUTES)


def is_weather_tick(moment: datetime) -> bool:
    """True se *moment* cade su un confine orario (``xx:00``), quando va il meteo."""
    return moment.minute == 0
