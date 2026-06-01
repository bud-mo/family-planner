from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.calendar.aggregator import CalendarAggregator
from app.config import AppConfig
from app.renderer.pillow_eink_renderer import PillowEinkRenderer
from app.scheduling import WEB_REFRESH_SECONDS
from app.server.routes.config import router as config_router
from app.server.routes.index import router as index_router


def create_app(
    config: AppConfig,
    aggregator: CalendarAggregator,
    config_path: Path,
    renderer: PillowEinkRenderer,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        config: Validated application configuration.
        aggregator: Calendar event aggregator (shared with display layer).
        config_path: Absolute path to the YAML config file; used by POST /config
            to persist changes and trigger a graceful uvicorn reload.
        renderer: Shared PillowEinkRenderer instance.

    Returns:
        Configured FastAPI application instance ready for ``uvicorn.run()``.
    """
    app = FastAPI(title="Family Planner", docs_url=None, redoc_url=None)

    # Serve local assets (htmx, fonts, icons) at /assets
    assets_dir = Path(__file__).parent.parent / "assets"
    app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
    templates.env.globals["refresh_interval"] = WEB_REFRESH_SECONDS
    templates.env.globals["show_buttons"] = config.display.show_buttons

    app.state.config = config
    app.state.aggregator = aggregator
    app.state.templates = templates
    app.state.config_path = config_path
    app.state.renderer = renderer

    app.include_router(index_router)
    app.include_router(config_router)

    return app
