"""Calendar data-preparation helpers.

Functions shared between the FastAPI routes, HdmiDisplay and
``PillowEinkRenderer``.  This module must not import anything from
``app.server`` or ``fastapi``.
"""
from __future__ import annotations

import calendar as _cal
import logging
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from app.renderer.state import NavigationState

if TYPE_CHECKING:
    from app.calendar.base import CalendarEvent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Event-range helper
# ---------------------------------------------------------------------------


def events_range_for_state(state: NavigationState) -> tuple[datetime, datetime]:
    """Return ``(start, end)`` datetime interval for event queries.

    The start is the Monday of the week containing ``anchor_date`` so that
    ``_build_rolling_week_grid`` has events available for all displayed cells.
    The end covers 35 days from ``anchor_date`` to ensure the full 5-week
    rolling grid (max 34 days ahead) and the agenda section are both covered.

    The returned interval is used by callers to query the aggregator with
    ``aggregator.get_events(start, end)``.  No I/O is performed here.
    """
    week_start = state.anchor_date - timedelta(days=state.anchor_date.weekday())
    start = datetime.combine(week_start, datetime.min.time())
    end = datetime.combine(state.anchor_date, datetime.min.time()) + timedelta(days=35)
    return start, end


# ---------------------------------------------------------------------------
# Monthly grid builder
# ---------------------------------------------------------------------------


def _build_month_grid(
    year: int,
    month: int,
    events: list["CalendarEvent"],
    today: date,
) -> list[list[dict]]:
    """Build a 2-D calendar grid (weeks × days) for the monthly view.

    Each cell is a dict with: date, day_number, is_today, is_current_month, events.
    The grid always starts on Monday and covers the full weeks that include
    the first and last day of the month.
    """
    events_by_date: dict[date, list["CalendarEvent"]] = {}
    for evt in events:
        d = evt.start.date()
        events_by_date.setdefault(d, []).append(evt)

    first_day = date(year, month, 1)
    _, num_days = _cal.monthrange(year, month)
    last_day = date(year, month, num_days)

    grid_start = first_day - timedelta(days=first_day.weekday())
    grid_end = last_day + timedelta(days=6 - last_day.weekday())

    weeks: list[list[dict]] = []
    cur = grid_start
    while cur <= grid_end:
        week = []
        for _ in range(7):
            week.append(
                {
                    "date": cur,
                    "day_number": cur.day,
                    "is_today": cur == today,
                    "is_current_month": cur.month == month,
                    "events": events_by_date.get(cur, []),
                }
            )
            cur += timedelta(days=1)
        weeks.append(week)
    return weeks


# ---------------------------------------------------------------------------
# Rolling week grid builder
# ---------------------------------------------------------------------------


def _build_rolling_week_grid(
    anchor_date: date,
    events: list["CalendarEvent"],
    today: date,
    n_weeks: int = 5,
) -> list[list[dict]]:
    """Build a 2-D calendar grid (weeks × days) for the rolling week view.

    Unlike ``_build_month_grid``, this always produces exactly ``n_weeks`` rows
    (default: 5) starting from the Monday of the week that contains
    ``anchor_date``.  All cells are marked ``is_current_month=True`` because
    every displayed day is intentionally in range — the month separator in the
    renderer provides the visual month-change cue.
    """
    events_by_date: dict[date, list["CalendarEvent"]] = {}
    for evt in events:
        d = evt.start.date()
        events_by_date.setdefault(d, []).append(evt)

    grid_start = anchor_date - timedelta(days=anchor_date.weekday())

    weeks: list[list[dict]] = []
    cur = grid_start
    for _ in range(n_weeks):
        week = []
        for _ in range(7):
            week.append(
                {
                    "date": cur,
                    "day_number": cur.day,
                    "is_today": cur == today,
                    "is_current_month": True,
                    "events": events_by_date.get(cur, []),
                }
            )
            cur += timedelta(days=1)
        weeks.append(week)
    return weeks


# ---------------------------------------------------------------------------
# Locale strings
# ---------------------------------------------------------------------------

_MONTH_NAMES_IT = [
    "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
    "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre",
]
