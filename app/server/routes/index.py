from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from app.calendar.base import CalendarEvent

logger = logging.getLogger(__name__)

router = APIRouter()

_GRID_START_HOUR = 8
_GRID_END_HOUR = 22
_GRID_MINUTES = (_GRID_END_HOUR - _GRID_START_HOUR) * 60  # 840
_GRID_HEIGHT_PX = 700

_DAY_NAMES_IT = ["LUN", "MAR", "MER", "GIO", "VEN", "SAB", "DOM"]
_MONTH_NAMES_IT = [
    "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
    "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre",
]


def _event_to_grid(event: CalendarEvent, week_start: date) -> dict | None:
    """Compute CSS top/height (px) for a timed event in the weekly grid."""
    day_idx = (event.start.date() - week_start).days
    if day_idx < 0 or day_idx > 6:
        return None

    start_min = event.start.hour * 60 + event.start.minute
    end_min = event.end.hour * 60 + event.end.minute
    top = max(0, (start_min - _GRID_START_HOUR * 60)) / _GRID_MINUTES * _GRID_HEIGHT_PX
    height = max(20, (end_min - start_min) / _GRID_MINUTES * _GRID_HEIGHT_PX)

    return {
        "uid": event.uid,
        "title": event.title,
        "start_str": event.start.strftime("%H:%M"),
        "end_str": event.end.strftime("%H:%M"),
        "color": event.color,
        "calendar_name": event.calendar_name,
        "day_index": day_idx,
        "top": round(top),
        "height": round(height),
    }


@router.get("/", response_class=HTMLResponse)
async def index(request: Request, week: int = Query(default=0)) -> HTMLResponse:
    aggregator = request.app.state.aggregator
    templates = request.app.state.templates
    config = request.app.state.config

    today = date.today()
    current_monday = today - timedelta(days=today.weekday())
    week_start = current_monday + timedelta(weeks=week)
    week_end = week_start + timedelta(days=6)              # Sunday

    start_dt = datetime.combine(week_start, datetime.min.time())
    end_dt = datetime.combine(week_end, datetime.max.time())

    try:
        events = aggregator.get_events(start_dt, end_dt)
    except Exception:
        logger.exception("Failed to fetch events for weekly view")
        events = []

    all_day_events = [e for e in events if e.all_day]
    timed_events = [e for e in events if not e.all_day]

    # Organise timed events by day column (0 = Monday, 6 = Sunday)
    days_events: list[list[dict]] = [[] for _ in range(7)]
    for evt in timed_events:
        grid = _event_to_grid(evt, week_start)
        if grid is not None:
            days_events[grid["day_index"]].append(grid)

    # Organise all-day events by day column
    days_allday: list[list[CalendarEvent]] = [[] for _ in range(7)]
    for evt in all_day_events:
        day_idx = (evt.start.date() - week_start).days
        if 0 <= day_idx <= 6:
            days_allday[day_idx].append(evt)

    # Build day header descriptors
    day_headers = [
        {
            "name": _DAY_NAMES_IT[i],
            "number": (week_start + timedelta(days=i)).day,
            "date": week_start + timedelta(days=i),
            "is_today": (week_start + timedelta(days=i)) == today,
        }
        for i in range(7)
    ]

    week_num = week_start.isocalendar()[1]
    month_name = _MONTH_NAMES_IT[week_end.month - 1]
    view_title = (
        f"Settimana {week_num} · "
        f"{week_start.day}–{week_end.day} {month_name} {week_end.year}"
    )

    return templates.TemplateResponse(
        "calendar.html",
        {
            "request": request,
            "week_offset": week,
            "view_title": view_title,
            "current_time": datetime.now().strftime("%H:%M"),
            "today": today,
            "week_start": week_start,
            "week_end": week_end,
            "day_headers": day_headers,
            "days_events": days_events,
            "days_allday": days_allday,
            "hour_labels": [
                f"{h:02d}:00" for h in range(_GRID_START_HOUR, _GRID_END_HOUR + 1)
            ],
            "grid_height": _GRID_HEIGHT_PX,
            "config": config,
        },
    )
