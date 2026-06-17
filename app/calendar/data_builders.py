"""Calendar data-preparation helpers.

Functions shared between the FastAPI routes, HdmiDisplay and
``PillowEinkRenderer``.  This module must not import anything from
``app.server`` or ``fastapi``.
"""
from __future__ import annotations

import calendar as _cal
import logging
from datetime import date, datetime, time as _time, timedelta, tzinfo as _tzinfo
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.calendar.base import CalendarEvent
    from app.renderer.state import NavigationState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Multi-day expansion helper
# ---------------------------------------------------------------------------


def event_local_dates(
    evt: "CalendarEvent", tz: "_tzinfo | None" = None
) -> list[date]:
    """Return the inclusive list of local dates an event spans.

    A single-day event yields one date; a multi-day event yields one entry per
    calendar day it covers.  All-day events are stored at midnight UTC with an
    *exclusive* end (the day after the last day), so their span is derived from
    the UTC dates directly and ``tz`` is ignored.  Timed events are converted to
    ``tz`` (local time) first; an event ending exactly at midnight does not add
    the following day.
    """
    if evt.all_day:
        start_d = evt.start.date()
        last_d = evt.end.date() - timedelta(days=1)  # DTEND is exclusive
        if last_d < start_d:
            last_d = start_d
    else:
        local_start = evt.start.astimezone(tz) if tz else evt.start
        local_end = evt.end.astimezone(tz) if tz else evt.end
        start_d = local_start.date()
        last_d = local_end.date()
        if local_end.timetz().replace(tzinfo=None) == _time(0, 0) and last_d > start_d:
            last_d -= timedelta(days=1)

    days: list[date] = []
    cur = start_d
    while cur <= last_d:
        days.append(cur)
        cur += timedelta(days=1)
    return days


def _events_by_date(
    events: list["CalendarEvent"], tz: "_tzinfo | None" = None
) -> dict[date, list["CalendarEvent"]]:
    """Group events by every local date they cover (multi-day events repeat)."""
    by_date: dict[date, list["CalendarEvent"]] = {}
    for evt in events:
        for d in event_local_dates(evt, tz):
            by_date.setdefault(d, []).append(evt)
    return by_date


# ---------------------------------------------------------------------------
# Event-range helper
# ---------------------------------------------------------------------------


def events_range_for_state(state: "NavigationState") -> tuple[datetime, datetime]:
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
    tz: "_tzinfo | None" = None,
) -> list[list[dict]]:
    """Build a 2-D calendar grid (weeks × days) for the monthly view.

    Each cell is a dict with: date, day_number, is_today, is_current_month, events.
    The grid always starts on Monday and covers the full weeks that include
    the first and last day of the month.  Multi-day events appear in every cell
    they span.
    """
    events_by_date = _events_by_date(events, tz)

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
    tz: "_tzinfo | None" = None,
) -> list[list[dict]]:
    """Build a 2-D calendar grid (weeks × days) for the rolling week view.

    Unlike ``_build_month_grid``, this always produces exactly ``n_weeks`` rows
    (default: 5) starting from the Monday of the week that contains
    ``anchor_date``.  All cells are marked ``is_current_month=True`` because
    every displayed day is intentionally in range — the month separator in the
    renderer provides the visual month-change cue.  Multi-day events appear in
    every cell they span.
    """
    events_by_date = _events_by_date(events, tz)

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



