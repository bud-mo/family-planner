"""Index and preview routes for Family Planner.

GET /                 — HTML preview page with auto-refresh.
GET /preview.png      — Render the Home view and return a PNG image on demand.
GET /preview-eink.png — Same as above but with e-ink palette quantisation applied.
"""
from __future__ import annotations

import io
import logging

from fastapi import APIRouter
from fastapi.requests import Request
from fastapi.responses import StreamingResponse
from fastapi.templating import Jinja2Templates

from app.renderer.eink_renderer import EinkRenderer
from app.renderer.state import NavigationState

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/")
async def index(request: Request):
    """Pagina di anteprima — auto-refresh dell'immagine calendario."""
    templates: Jinja2Templates = request.app.state.templates
    # ``refresh_interval`` is provided as a Jinja global (WEB_REFRESH_SECONDS).
    return templates.TemplateResponse(
        "index.html",
        {"request": request},
    )


@router.get("/preview.png")
async def preview_png(request: Request) -> StreamingResponse:
    """Renderizza la Home view e restituisce un PNG on-demand."""
    from app.calendar.data_builders import events_range_for_state

    aggregator = request.app.state.aggregator
    renderer = request.app.state.renderer

    state = NavigationState()
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


@router.get("/preview-eink.png")
async def preview_eink_png(request: Request) -> StreamingResponse:
    """Renderizza la Home view con quantizzazione palette e-ink applicata.

    Utile per verificare come apparirà l'immagine sul pannello fisico,
    inclusi dithering Floyd-Steinberg e riduzione alla palette configurata.
    """
    from app.calendar.data_builders import events_range_for_state

    aggregator = request.app.state.aggregator
    renderer = request.app.state.renderer
    config = request.app.state.config

    state = NavigationState()
    start, end = events_range_for_state(state)
    try:
        events = aggregator.get_events(start, end)
    except Exception as exc:
        logger.error("preview_eink_png: event fetch error: %s", exc)
        events = []

    img = renderer.render(state, events)
    eink = EinkRenderer(config.display)
    processed = eink.process(img)

    # EinkRenderer può restituire un'immagine in modalità "P" (palette) per
    # spectra6 — la convertiamo in RGB per garantire un PNG leggibile.
    if processed.mode != "RGB":
        processed = processed.convert("RGB")

    buf = io.BytesIO()
    processed.save(buf, format="PNG")
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/png")
