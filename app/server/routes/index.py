"""Index and preview routes for Family Planner.

GET /            — HTML preview page with auto-refresh.
GET /preview.png — Render the Home view and return a PNG image on demand.
"""
from __future__ import annotations

import io
import logging

from fastapi import APIRouter
from fastapi.requests import Request
from fastapi.responses import StreamingResponse
from fastapi.templating import Jinja2Templates

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/")
async def index(request: Request):
    """Pagina di anteprima — auto-refresh dell'immagine calendario."""
    templates: Jinja2Templates = request.app.state.templates
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "refresh_interval": request.app.state.config.display.refresh_interval,
        },
    )


@router.get("/preview.png")
async def preview_png(request: Request) -> StreamingResponse:
    """Renderizza la Home view e restituisce un PNG on-demand."""
    from app.calendar.data_builders import events_range_for_state

    state_manager = request.app.state.state_manager
    aggregator = request.app.state.aggregator
    renderer = request.app.state.renderer

    state = state_manager.get()
    start, end = events_range_for_state(state)
    try:
        events = aggregator.get_events(start, end)
    except Exception as exc:
        logger.error("preview_png: event fetch error: %s", exc)
        events = []

    img = renderer.render(state, events)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/png")
