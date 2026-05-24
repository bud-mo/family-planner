from __future__ import annotations

import calendar as _cal
import logging
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from app.calendar.base import CalendarEvent
from app.renderer.state import NavigationState, View

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_night_mode(request: Request) -> bool:
    """Return night_mode from current renderer state, defaulting to False."""
    renderer = getattr(request.app.state, "renderer", None)
    if renderer is None:
        return False
    try:
        return renderer.get_state().night_mode
    except Exception:
        return False

_GRID_START_HOUR = 8
_GRID_END_HOUR = 22
_GRID_MINUTES = (_GRID_END_HOUR - _GRID_START_HOUR) * 60  # 840
_GRID_HEIGHT_PX = 700

_DAY_NAMES_IT = ["LUN", "MAR", "MER", "GIO", "VEN", "SAB", "DOM"]
_DAY_NAMES_SHORT_IT = ["L", "M", "M", "G", "V", "S", "D"]
_DAY_NAMES_FULL_IT = [
    "Lunedì", "Martedì", "Mercoledì", "Giovedì",
    "Venerdì", "Sabato", "Domenica",
]
_MONTH_NAMES_IT = [
    "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
    "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre",
]


def _get_display_tz(config: Any):
    """Return a tzinfo for the configured timezone, or None to keep event-native tz."""
    tz_name = getattr(config, "timezone", "local")
    if not tz_name or tz_name == "local":
        return None
    try:
        return ZoneInfo(tz_name)
    except (KeyError, ZoneInfoNotFoundError):
        logger.warning("index: unknown timezone %r, falling back to event-native tz", tz_name)
        return None


def _event_to_grid(event: CalendarEvent, week_start: date, display_tz=None) -> dict | None:
    """Compute CSS top/height (px) for a timed event in the weekly/daily grid."""
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


def _build_month_grid(
    year: int,
    month: int,
    events: list[CalendarEvent],
    today: date,
) -> list[list[dict]]:
    """Build a 2-D calendar grid (weeks × days) for the monthly view.

    Each cell is a dict with: date, day_number, is_today, is_current_month, events.
    The grid always starts on Monday and covers the full weeks that include
    the first and last day of the month.
    """
    # Index events by date for O(1) lookup.
    events_by_date: dict[date, list[CalendarEvent]] = {}
    for evt in events:
        d = evt.start.date()
        events_by_date.setdefault(d, []).append(evt)

    first_day = date(year, month, 1)
    _, num_days = _cal.monthrange(year, month)
    last_day = date(year, month, num_days)

    # Grid starts on Monday of the week containing the 1st.
    grid_start = first_day - timedelta(days=first_day.weekday())
    # Grid ends on Sunday of the week containing the last day.
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


def _build_annual_months(year: int, events: list[CalendarEvent], today: date) -> list[dict]:
    """Build summary data for 12 months used by the annual view.

    Each month has: month_name, month_idx, weeks (same grid structure but
    days carry only has_events + event_colors instead of full event list).
    """
    events_by_date: dict[date, list[CalendarEvent]] = {}
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


def _find_event_by_uid(
    aggregator: Any, uid: str, around: date
) -> CalendarEvent | None:
    """Search for an event by UID in a 3-month window around *around*."""
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
# Main route dispatcher
# ---------------------------------------------------------------------------


_VIEW_PARAM_MAP = {
    "annual": View.ANNUAL,
    "monthly": View.MONTHLY,
    "weekly": View.WEEKLY,
    "daily": View.DAILY,
    "detail": View.DETAIL,
}


@router.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    view: str | None = Query(default=None),
    week: int = Query(default=0),
) -> HTMLResponse:
    """Serve the appropriate calendar view.

    The *view* query parameter selects the template:
    ``annual | monthly | weekly | daily | detail``

    If *view* is omitted the active ``NavigationState`` from the renderer
    is used, falling back to ``weekly`` when no renderer is configured.
    """
    # --- Resolve active view ---
    renderer = getattr(request.app.state, "renderer", None)
    if view is None:
        if renderer is not None:
            view = _VIEW_NAMES_REV[renderer.get_state().view]
        else:
            view = "weekly"

    if view == "monthly":
        return await _monthly_view(request)
    if view == "annual":
        return await _annual_view(request)
    if view == "daily":
        return await _daily_view(request)
    if view == "detail":
        return await _detail_view(request)
    # Default: weekly
    return await _weekly_view(request, week)


_VIEW_NAMES_REV: dict[View, str] = {
    View.ANNUAL: "annual",
    View.MONTHLY: "monthly",
    View.WEEKLY: "weekly",
    View.DAILY: "daily",
    View.DETAIL: "detail",
}


async def _render_view(request: Request) -> HTMLResponse:
    """Dispatch to the correct view based on the current renderer state.

    Used by POST /state to return an updated full-page HTML response for HTMX.
    """
    renderer = getattr(request.app.state, "renderer", None)
    if renderer is None:
        return await _weekly_view(request, 0)
    state: NavigationState = renderer.get_state()
    view = state.view
    if view == View.ANNUAL:
        return await _annual_view(request)
    if view == View.MONTHLY:
        return await _monthly_view(request)
    if view == View.DAILY:
        return await _daily_view(request)
    if view == View.DETAIL:
        return await _detail_view(request)
    # WEEKLY: compute offset so the view follows the selected date
    today = date.today()
    current_monday = today - timedelta(days=today.weekday())
    sel = state.selected_date
    selected_monday = sel - timedelta(days=sel.weekday())
    week_offset = (selected_monday - current_monday).days // 7
    return await _weekly_view(request, week_offset)


# ---------------------------------------------------------------------------
# Weekly view (existing logic, extracted into helper)
# ---------------------------------------------------------------------------


async def _weekly_view(request: Request, week: int) -> HTMLResponse:
    aggregator = request.app.state.aggregator
    templates = request.app.state.templates
    config = request.app.state.config
    renderer = getattr(request.app.state, "renderer", None)

    today = date.today()
    current_monday = today - timedelta(days=today.weekday())
    week_start = current_monday + timedelta(weeks=week)
    week_end = week_start + timedelta(days=6)

    start_dt = datetime.combine(week_start, datetime.min.time())
    end_dt = datetime.combine(week_end, datetime.max.time())

    try:
        events = aggregator.get_events(start_dt, end_dt)
    except Exception:
        logger.exception("Failed to fetch events for weekly view")
        events = []

    all_day_events = [e for e in events if e.all_day]
    timed_events = [e for e in events if not e.all_day]

    display_tz = _get_display_tz(config)

    days_events: list[list[dict]] = [[] for _ in range(7)]
    for evt in timed_events:
        grid = _event_to_grid(evt, week_start, display_tz)
        if grid is not None:
            days_events[grid["day_index"]].append(grid)

    days_allday: list[list[CalendarEvent]] = [[] for _ in range(7)]
    for evt in all_day_events:
        day_idx = (evt.start.date() - week_start).days
        if 0 <= day_idx <= 6:
            days_allday[day_idx].append(evt)

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
            "night_mode": _get_night_mode(request),
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
            "selected_date": renderer.get_state().selected_date if renderer else today,
            "config": config,
        },
    )


# ---------------------------------------------------------------------------
# Monthly view
# ---------------------------------------------------------------------------


async def _monthly_view(request: Request) -> HTMLResponse:
    aggregator = request.app.state.aggregator
    templates = request.app.state.templates
    renderer = getattr(request.app.state, "renderer", None)

    today = date.today()
    selected = renderer.get_state().selected_date if renderer else today
    year, month = selected.year, selected.month

    # Fetch events for the full month (+/- a few days for grid overflow).
    first_day = date(year, month, 1)
    _, num_days = _cal.monthrange(year, month)
    start_dt = datetime.combine(first_day - timedelta(days=7), datetime.min.time())
    end_dt = datetime.combine(date(year, month, num_days) + timedelta(days=7), datetime.max.time())

    try:
        events = aggregator.get_events(start_dt, end_dt)
    except Exception:
        logger.exception("Failed to fetch events for monthly view")
        events = []

    weeks = _build_month_grid(year, month, events, today)

    # Prev / next month navigation dates.
    if month == 1:
        prev_year, prev_month = year - 1, 12
    else:
        prev_year, prev_month = year, month - 1
    if month == 12:
        next_year, next_month = year + 1, 1
    else:
        next_year, next_month = year, month + 1

    month_name = _MONTH_NAMES_IT[month - 1]
    view_title = f"{month_name} {year}"

    return templates.TemplateResponse(
        "monthly.html",
        {
            "request": request,
            "view_title": view_title,
            "current_time": datetime.now().strftime("%H:%M"),
            "night_mode": _get_night_mode(request),
            "today": today,
            "year": year,
            "month": month,
            "month_name": month_name,
            "weeks": weeks,
            "day_names": _DAY_NAMES_IT,
            "prev_year": prev_year,
            "prev_month": prev_month,
            "next_year": next_year,
            "next_month": next_month,
        },
    )


# ---------------------------------------------------------------------------
# Annual view
# ---------------------------------------------------------------------------


async def _annual_view(request: Request) -> HTMLResponse:
    aggregator = request.app.state.aggregator
    templates = request.app.state.templates
    renderer = getattr(request.app.state, "renderer", None)

    today = date.today()
    year = renderer.get_state().selected_date.year if renderer else today.year

    start_dt = datetime(year, 1, 1)
    end_dt = datetime(year, 12, 31, 23, 59, 59)

    try:
        events = aggregator.get_events(start_dt, end_dt)
    except Exception:
        logger.exception("Failed to fetch events for annual view")
        events = []

    months = _build_annual_months(year, events, today)

    return templates.TemplateResponse(
        "annual.html",
        {
            "request": request,
            "view_title": str(year),
            "current_time": datetime.now().strftime("%H:%M"),
            "night_mode": _get_night_mode(request),
            "today": today,
            "year": year,
            "prev_year": year - 1,
            "next_year": year + 1,
            "months": months,
            "day_names_short": _DAY_NAMES_SHORT_IT,
        },
    )


# ---------------------------------------------------------------------------
# Daily view
# ---------------------------------------------------------------------------


async def _daily_view(request: Request) -> HTMLResponse:
    aggregator = request.app.state.aggregator
    templates = request.app.state.templates
    renderer = getattr(request.app.state, "renderer", None)

    today = date.today()
    selected = renderer.get_state().selected_date if renderer else today

    start_dt = datetime.combine(selected, datetime.min.time())
    end_dt = datetime.combine(selected, datetime.max.time())

    try:
        events = aggregator.get_events(start_dt, end_dt)
    except Exception:
        logger.exception("Failed to fetch events for daily view")
        events = []

    all_day_events = [e for e in events if e.all_day]
    timed_events_raw = sorted(
        (e for e in events if not e.all_day),
        key=lambda e: e.start,
    )

    display_tz = _get_display_tz(request.app.state.config)

    timed_events: list[dict] = []
    for evt in timed_events_raw:
        local_start = evt.start.astimezone(display_tz) if display_tz else evt.start
        local_end = evt.end.astimezone(display_tz) if display_tz else evt.end
        timed_events.append(
            {
                "uid": evt.uid,
                "title": evt.title,
                "start_str": local_start.strftime("%H:%M"),
                "end_str": local_end.strftime("%H:%M"),
                "color": evt.color,
                "calendar_name": evt.calendar_name,
            }
        )

    day_name = _DAY_NAMES_FULL_IT[selected.weekday()]
    month_name = _MONTH_NAMES_IT[selected.month - 1]
    date_str = f"{day_name} {selected.day} {month_name} {selected.year}"
    view_title = f"{selected.day} {month_name}"

    return templates.TemplateResponse(
        "daily.html",
        {
            "request": request,
            "view_title": view_title,
            "current_time": datetime.now().strftime("%H:%M"),
            "night_mode": _get_night_mode(request),
            "today": today,
            "selected_date": selected,
            "date_str": date_str,
            "is_today": selected == today,
            "allday_events": all_day_events,
            "timed_events": timed_events,
        },
    )


# ---------------------------------------------------------------------------
# Detail view
# ---------------------------------------------------------------------------


async def _detail_view(request: Request) -> HTMLResponse:
    aggregator = request.app.state.aggregator
    templates = request.app.state.templates
    renderer = getattr(request.app.state, "renderer", None)

    today = date.today()
    state = renderer.get_state() if renderer else None
    uid = state.selected_event_uid if state else None
    selected = state.selected_date if state else today

    event: CalendarEvent | None = None
    if uid:
        event = _find_event_by_uid(aggregator, uid, selected)

    if event is None:
        # Fall back to the daily view if no event is selected.
        return await _daily_view(request)

    display_tz = _get_display_tz(request.app.state.config)
    ev_start = event.start.astimezone(display_tz) if display_tz else event.start
    ev_end = event.end.astimezone(display_tz) if display_tz else event.end

    month_name = _MONTH_NAMES_IT[ev_start.month - 1]
    if event.all_day:
        datetime_str = f"{ev_start.day} {month_name} {ev_start.year}"
    else:
        datetime_str = (
            f"{ev_start.day} {month_name} {ev_start.year} "
            f"{ev_start.strftime('%H:%M')}\u2013{ev_end.strftime('%H:%M')}"
        )

    return templates.TemplateResponse(
        "detail.html",
        {
            "request": request,
            "view_title": event.title,
            "current_time": datetime.now().strftime("%H:%M"),
            "night_mode": _get_night_mode(request),
            "event": event,
            "datetime_str": datetime_str,
        },
    )
