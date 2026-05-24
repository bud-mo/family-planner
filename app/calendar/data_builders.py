"""Calendar data-preparation helpers.

Functions and constants shared between the FastAPI routes and
``PillowEinkRenderer``.  This module must not import anything from
``app.server`` or ``fastapi``.

Layout grid constants
---------------------
The three grid constants below define the visible time window for the
weekly/daily grid and are exported so that ``PillowEinkRenderer`` can use
the same values for pixel-position calculations.

    _GRID_START_HOUR  — first rendered hour (inclusive)
    _GRID_END_HOUR    — last rendered hour (inclusive)
    _GRID_HEIGHT_PX   — total pixel height of the time grid
"""
from __future__ import annotations

import calendar as _cal
import logging
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from app.renderer.state import NavigationState, View

if TYPE_CHECKING:
    from app.calendar.base import CalendarEvent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Grid layout constants (exported for PillowEinkRenderer)
# ---------------------------------------------------------------------------

_GRID_START_HOUR: int = 8
_GRID_END_HOUR: int = 22
_GRID_MINUTES: int = (_GRID_END_HOUR - _GRID_START_HOUR) * 60  # 840
_GRID_HEIGHT_PX: int = 700


# ---------------------------------------------------------------------------
# Event-range helper
# ---------------------------------------------------------------------------


def events_range_for_state(state: NavigationState) -> tuple[datetime, datetime]:
    """Return ``(start, end)`` datetime interval relevant to the current view.

    The returned interval is used by callers to query the aggregator with
    ``aggregator.get_events(start, end)``.  No I/O is performed here.
    """
    sel = state.selected_date
    if state.view == View.ANNUAL:
        start = datetime(sel.year, 1, 1)
        end = datetime(sel.year, 12, 31, 23, 59, 59)
    elif state.view == View.MONTHLY:
        start = datetime(sel.year, sel.month, 1)
        if sel.month == 12:
            end = datetime(sel.year + 1, 1, 1) - timedelta(seconds=1)
        else:
            end = datetime(sel.year, sel.month + 1, 1) - timedelta(seconds=1)
    elif state.view == View.DAILY:
        start = datetime.combine(sel, datetime.min.time())
        end = datetime.combine(sel, datetime.max.time())
    else:
        # WEEKLY / DETAIL: the week that contains selected_date.
        monday = sel - timedelta(days=sel.weekday())
        start = datetime.combine(monday, datetime.min.time())
        end = datetime.combine(monday + timedelta(days=6), datetime.max.time())
    return start, end


# ---------------------------------------------------------------------------
# Grid coordinate helper (weekly / daily views)
# ---------------------------------------------------------------------------


def _event_to_grid(event: "CalendarEvent", week_start: date, display_tz=None) -> dict | None:
    """Compute CSS top/height (px) for a timed event in the weekly/daily grid.

    Returns ``None`` if the event falls outside the week window.
    """
    local_start = event.start.astimezone(display_tz) if display_tz else event.start
    local_end = event.end.astimezone(display_tz) if display_tz else event.end

    day_idx = (local_start.date() - week_start).days
    if day_idx < 0 or day_idx > 6:
        return None

    start_min = local_start.hour * 60 + local_start.minute
    end_min = local_end.hour * 60 + local_end.minute
    top = max(0, (start_min - _GRID_START_HOUR * 60)) / _GRID_MINUTES * _GRID_HEIGHT_PX
    height = max(20, (end_min - start_min) / _GRID_MINUTES * _GRID_HEIGHT_PX)

    return {
        "uid": event.uid,
        "title": event.title,
        "start_str": local_start.strftime("%H:%M"),
        "end_str": local_end.strftime("%H:%M"),
        "color": event.color,
        "calendar_name": event.calendar_name,
        "day_index": day_idx,
        "top": round(top),
        "height": round(height),
    }


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
# Annual grid builder
# ---------------------------------------------------------------------------


def _build_annual_months(year: int, events: list["CalendarEvent"], today: date) -> list[dict]:
    """Build summary data for 12 months used by the annual view.

    Each month has: month_name, month_idx, weeks (same grid structure but
    days carry only has_events + event_colors instead of full event list).
    """
    events_by_date: dict[date, list["CalendarEvent"]] = {}
    for evt in events:
        d = evt.start.date()
        events_by_date.setdefault(d, []).append(evt)

    months = []
    for m in range(1, 13):
        first_day = date(year, m, 1)
        _, num_days = _cal.monthrange(year, m)
        last_day = date(year, m, num_days)
        grid_start = first_day - timedelta(days=first_day.weekday())
        grid_end = last_day + timedelta(days=6 - last_day.weekday())

        weeks: list[list[dict]] = []
        cur = grid_start
        while cur <= grid_end:
            week = []
            for _ in range(7):
                day_events = events_by_date.get(cur, [])
                week.append(
                    {
                        "date": cur,
                        "day_number": cur.day,
                        "is_today": cur == today,
                        "is_current_month": cur.month == m,
                        "has_events": bool(day_events),
                        "event_colors": list({e.color for e in day_events}),
                    }
                )
                cur += timedelta(days=1)
            weeks.append(week)

        months.append(
            {
                "month_name": _MONTH_NAMES_IT[m - 1],
                "month_idx": m,
                "weeks": weeks,
            }
        )
    return months


# ---------------------------------------------------------------------------
# Event lookup by UID
# ---------------------------------------------------------------------------


def _find_event_by_uid(
    aggregator: Any, uid: str, around: date
) -> "CalendarEvent | None":
    """Search for an event by UID in a ±45-day window around *around*."""
    start = datetime(around.year, around.month, 1) - timedelta(days=45)
    end = start + timedelta(days=90)
    try:
        events = aggregator.get_events(start, end)
        for e in events:
            if e.uid == uid:
                return e
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to fetch event by UID: %s", exc)
    return None


# ---------------------------------------------------------------------------
# Locale strings (used by grid builders above)
# ---------------------------------------------------------------------------

_MONTH_NAMES_IT = [
    "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
    "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre",
]
