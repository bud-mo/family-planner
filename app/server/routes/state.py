"""Navigation state API.

GET  /state  — returns the current NavigationState as JSON.
POST /state  — accepts an action, advances the state, returns the new state.

Actions:
    "prev"  → navigate_prev  (pagina precedente)
    "next"  → navigate_next  (pagina successiva)
    "today" → navigate_today (torna a oggi)
    "night" → toggle_night_mode
"""
from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.requests import Request
from fastapi.responses import JSONResponse

from app.renderer.state import NavigationState

logger = logging.getLogger(__name__)

router = APIRouter()

_VALID_ACTIONS = {"prev", "next", "today", "night"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _state_to_dict(state: NavigationState) -> dict:
    return {
        "anchor_date": state.anchor_date.isoformat(),
        "page_offset": state.page_offset,
        "night_mode": state.night_mode,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/state")
async def state_get(request: Request) -> JSONResponse:
    """Return the current navigation state as JSON."""
    state: NavigationState = request.app.state.state_manager.get()
    return JSONResponse(_state_to_dict(state))


@router.post("/state", response_model=None)
async def state_post(request: Request) -> JSONResponse:
    """Apply a navigation action and return the updated state."""
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

    if action not in _VALID_ACTIONS:
        return JSONResponse({"error": f"Unknown action: {action!r}"}, status_code=400)

    state_manager = request.app.state.state_manager
    state = state_manager.get()

    if action == "prev":
        new_state = state.navigate_prev()
    elif action == "next":
        new_state = state.navigate_next()
    elif action == "today":
        new_state = state.navigate_today()
    else:  # "night"
        new_state = state.toggle_night_mode()

    if new_state is not state:
        state_manager.set(new_state)

    return JSONResponse(_state_to_dict(new_state))
