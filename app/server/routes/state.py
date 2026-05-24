"""Navigation state API.

GET  /state  — returns the current NavigationState as JSON.
POST /state  — accepts an action, advances the state, returns the new state.

Actions:
    "prev"  → navigate_up   (move backwards / scroll up)
    "next"  → navigate_down (move forwards / scroll down)
    "in"    → navigate_enter (drill into selection)
    "out"   → navigate_escape (return to previous view)
    "night" → toggle_night_mode
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter
from fastapi.requests import Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.renderer.state import NavigationState, View

logger = logging.getLogger(__name__)

router = APIRouter()

_VIEW_NAMES: dict[View, str] = {
    View.ANNUAL: "annual",
    View.MONTHLY: "monthly",
    View.WEEKLY: "weekly",
    View.DAILY: "daily",
    View.DETAIL: "detail",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _state_to_dict(state: NavigationState) -> dict:
    return {
        "view": _VIEW_NAMES[state.view],
        "selected_date": state.selected_date.isoformat(),
        "selected_event_uid": state.selected_event_uid,
        "detail_scroll_offset": state.detail_scroll_offset,
        "night_mode": state.night_mode,
    }


def _fetch_events_for_state(request: Request, state: NavigationState) -> list:
    """Fetch the event list relevant to the current view for context-aware navigation.

    ``navigate_up`` / ``navigate_down`` / ``navigate_enter`` need the event
    list to select adjacent events in weekly/daily views.  Failures are logged
    and an empty list is returned so navigation degrades gracefully.
    """
    aggregator = request.app.state.aggregator
    sel = state.selected_date
    try:
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
            # WEEKLY / DETAIL: fetch the week that contains selected_date.
            monday = sel - timedelta(days=sel.weekday())
            start = datetime.combine(monday, datetime.min.time())
            end = datetime.combine(monday + timedelta(days=6), datetime.max.time())
        return aggregator.get_events(start, end)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to fetch events for state navigation: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/state")
async def state_get(request: Request) -> JSONResponse:
    """Return the current navigation state as JSON."""
    state: NavigationState = request.app.state.renderer.get_state()
    return JSONResponse(_state_to_dict(state))


@router.post("/state", response_model=None)
async def state_post(request: Request) -> JSONResponse | HTMLResponse:
    """Apply a navigation action and return the updated state.

    Accepts either a JSON body ``{"action": "..."}`` (from API clients) or
    ``application/x-www-form-urlencoded`` data (sent by HTMX buttons in the
    browser).  When the request includes the ``HX-Request: true`` header the
    response is a full-page HTML refresh; otherwise a JSON state dict is
    returned for backward-compatible API usage.
    """
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            body = await request.json()
            action = str(body.get("action", "")).strip()
        except Exception:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    else:
        form = await request.form()
        action = str(form.get("action", "")).strip()

    _VALID_ACTIONS = {"prev", "next", "in", "out", "night"}
    if action not in _VALID_ACTIONS:
        return JSONResponse({"error": f"Unknown action: {action!r}"}, status_code=400)

    renderer = request.app.state.renderer
    state = renderer.get_state()
    events = _fetch_events_for_state(request, state)

    if action == "prev":
        new_state = state.navigate_up(events)
    elif action == "next":
        new_state = state.navigate_down(events)
    elif action == "in":
        new_state = state.navigate_enter(events)
    elif action == "out":
        new_state = state.navigate_escape()
    else:  # "night"
        new_state = state.toggle_night_mode()

    if new_state is not state:
        renderer.update_state(new_state)

    # HTMX requests: return the full updated page so the browser can swap the body.
    if request.headers.get("hx-request") == "true":
        from app.server.routes.index import _render_view
        return await _render_view(request)

    return JSONResponse(_state_to_dict(new_state))
