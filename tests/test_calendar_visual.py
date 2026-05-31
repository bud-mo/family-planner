"""Visual rendering tests for the mini-calendar component (_draw_mini_calendar).

Ogni test produce un PNG in ``tests/visual_output/`` per ispezione manuale.
I file sono deterministici (stessi dati) ma vengono riscritti ad ogni
esecuzione — non costituiscono un baseline di regressione pixel-perfect.

Casi coperti:
  1. Griglia vuota — nessun evento, solo header DOW e numeri cella
  2. Un evento tutto-il-giorno oggi — cella today con sfondo BG_ALT
  3. Evento con orario e colore custom (#3A86FF)
  4. Overflow di eventi in una cella (6 eventi → 3 visibili + "+3")
  5. Separatore di mese nella griglia (anchor 2026-06-29, confine giugno/luglio)
  6. Schermo largo (1280px) — bordi verticali colorati abilitati (show_border=True)
"""
from __future__ import annotations

import types
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from app.calendar.base import CalendarEvent
from app.renderer.eink_renderer import _SPECTRA6_PALETTE, _build_palette_image
from app.renderer.pillow_eink_renderer import PillowEinkRenderer
from app.renderer.state import NavigationState
from app.renderer.tokens import CALENDAR_HEIGHT, COLOR_BG, get_palette

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_OUTPUT_DIR: Path = Path(__file__).parent / "visual_output"
_CANVAS_W: int = 800
_CANVAS_W_WIDE: int = 1280
_CANVAS_H: int = CALENDAR_HEIGHT  # 560


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_spectra6(img: Image.Image) -> Image.Image:
    """Quantise *img* to the Spectra 6 palette with Floyd-Steinberg dithering.

    No resize — preserves original dimensions for visual inspection.
    """
    palette_img = _build_palette_image(_SPECTRA6_PALETTE)
    return img.convert("RGB").quantize(
        colors=6,
        palette=palette_img,
        dither=Image.Dither.FLOYDSTEINBERG,
    ).convert("RGB")


def _make_renderer(width: int = _CANVAS_W) -> PillowEinkRenderer:
    cfg = types.SimpleNamespace(
        display=types.SimpleNamespace(
            width=width, height=800, layout="portrait", type="hdmi"
        ),
        timezone="local",
    )
    return PillowEinkRenderer(cfg)


def _make_canvas(
    width: int = _CANVAS_W, height: int = _CANVAS_H
) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (width, height), COLOR_BG)
    draw = ImageDraw.Draw(img)
    return img, draw


def _evt(
    *,
    uid: str,
    title: str,
    start_h: int,
    start_m: int,
    end_h: int,
    end_m: int,
    description: str | None = None,
    location: str | None = None,
    all_day: bool = False,
    color: str = "#E27B3E",
    day_offset: int = 0,
    anchor: date | None = None,
) -> CalendarEvent:
    base = (anchor if anchor is not None else date.today()) + timedelta(days=day_offset)
    start_dt = datetime(base.year, base.month, base.day, start_h, start_m, tzinfo=timezone.utc)
    end_dt = datetime(base.year, base.month, base.day, end_h, end_m, tzinfo=timezone.utc)
    return CalendarEvent(
        uid=uid,
        title=title,
        start=start_dt,
        end=end_dt,
        all_day=all_day,
        location=location,
        description=description,
        attendees=[],
        recurrent=False,
        color=color,
        calendar_name="Calendario Test",
    )


def _save(img: Image.Image, name: str) -> Path:
    out = _OUTPUT_DIR / name
    img.save(out)
    _to_spectra6(img).save(out.with_stem(out.stem + "_spectra6"))
    return out


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def renderer() -> PillowEinkRenderer:
    _OUTPUT_DIR.mkdir(exist_ok=True)
    return _make_renderer()


@pytest.fixture(scope="module")
def renderer_wide() -> PillowEinkRenderer:
    _OUTPUT_DIR.mkdir(exist_ok=True)
    return _make_renderer(width=_CANVAS_W_WIDE)


@pytest.fixture()
def palette() -> dict[str, str]:
    return get_palette()


# ---------------------------------------------------------------------------
# Caso 1 — Griglia vuota
# ---------------------------------------------------------------------------


class TestCaso1GrigliaVuota:
    """Nessun evento: solo header DOW e numeri cella."""

    def test_produces_png(self, renderer: PillowEinkRenderer, palette: dict[str, str]) -> None:
        state = NavigationState(anchor_date=date.today())
        events: list[CalendarEvent] = []

        img, draw = _make_canvas()
        renderer._draw_mini_calendar(draw, (0, 0, _CANVAS_W, _CANVAS_H), state, events, palette)

        out = _save(img, "calendario_caso_1_calendario_vuoto.png")
        assert out.exists()


# ---------------------------------------------------------------------------
# Caso 2 — Un evento tutto-il-giorno oggi
# ---------------------------------------------------------------------------


class TestCaso2EventoAllDay:
    """Un evento all-day oggi: cella today deve mostrare sfondo BG_ALT."""

    @pytest.fixture()
    def events(self) -> list[CalendarEvent]:
        return [
            _evt(
                uid="allday-1",
                title="Compleanno Nonna",
                start_h=0,
                start_m=0,
                end_h=23,
                end_m=59,
                all_day=True,
                color="#D62828",
            )
        ]

    def test_produces_png(
        self,
        renderer: PillowEinkRenderer,
        palette: dict[str, str],
        events: list[CalendarEvent],
    ) -> None:
        state = NavigationState(anchor_date=date.today())

        img, draw = _make_canvas()
        renderer._draw_mini_calendar(draw, (0, 0, _CANVAS_W, _CANVAS_H), state, events, palette)

        out = _save(img, "calendario_caso_2_evento_allday.png")
        assert out.exists()


# ---------------------------------------------------------------------------
# Caso 3 — Evento con orario e colore custom
# ---------------------------------------------------------------------------


class TestCaso3EventoOrarioColore:
    """Evento timed con colore custom: l'orario deve apparire come 'HH:MM Titolo'."""

    @pytest.fixture()
    def events(self) -> list[CalendarEvent]:
        return [
            _evt(
                uid="timed-1",
                title="Stand-up",
                start_h=10,
                start_m=0,
                end_h=10,
                end_m=30,
                color="#3A86FF",
            )
        ]

    def test_produces_png(
        self,
        renderer: PillowEinkRenderer,
        palette: dict[str, str],
        events: list[CalendarEvent],
    ) -> None:
        state = NavigationState(anchor_date=date.today())

        img, draw = _make_canvas()
        renderer._draw_mini_calendar(draw, (0, 0, _CANVAS_W, _CANVAS_H), state, events, palette)

        out = _save(img, "calendario_caso_3_evento_orario_colore.png")
        assert out.exists()


# ---------------------------------------------------------------------------
# Caso 4 — Overflow di eventi in una cella
# ---------------------------------------------------------------------------


class TestCaso4OverflowEventi:
    """6 eventi nello stesso giorno: max 4 linee → 3 eventi + '+3'."""

    @pytest.fixture()
    def events(self) -> list[CalendarEvent]:
        return [
            _evt(uid=f"overflow-{i}", title=f"Evento {i}", start_h=8 + i, start_m=0, end_h=9 + i, end_m=0, color="#8338EC")
            for i in range(6)
        ]

    def test_produces_png(
        self,
        renderer: PillowEinkRenderer,
        palette: dict[str, str],
        events: list[CalendarEvent],
    ) -> None:
        state = NavigationState(anchor_date=date.today())

        img, draw = _make_canvas()
        renderer._draw_mini_calendar(draw, (0, 0, _CANVAS_W, _CANVAS_H), state, events, palette)

        out = _save(img, "calendario_caso_4_overflow_eventi.png")
        assert out.exists()


# ---------------------------------------------------------------------------
# Caso 5 — Separatore di mese nella griglia
# ---------------------------------------------------------------------------


class TestCaso5SeparatoreMese:
    """Anchor 2026-06-29 (lunedì): row 0 = ultima settimana giugno, row 1 inizia con 2026-07-06.
    Il renderer deve inserire la label 'LUGLIO 2026' come separatore tra row 0 e row 1.
    """

    _ANCHOR = date(2026, 6, 29)

    @pytest.fixture()
    def events(self) -> list[CalendarEvent]:
        anchor = self._ANCHOR
        return [
            _evt(
                uid="giugno-1",
                title="Festa fine mese",
                start_h=18,
                start_m=0,
                end_h=20,
                end_m=0,
                anchor=anchor,
                day_offset=1,  # 30 giugno
                color="#06D6A0",
            ),
            _evt(
                uid="luglio-1",
                title="Primo luglio",
                start_h=9,
                start_m=0,
                end_h=10,
                end_m=0,
                anchor=anchor,
                day_offset=2,  # 1 luglio
                color="#FFB703",
            ),
        ]

    def test_produces_png(
        self,
        renderer: PillowEinkRenderer,
        palette: dict[str, str],
        events: list[CalendarEvent],
    ) -> None:
        state = NavigationState(anchor_date=self._ANCHOR)

        img, draw = _make_canvas()
        renderer._draw_mini_calendar(draw, (0, 0, _CANVAS_W, _CANVAS_H), state, events, palette)

        out = _save(img, "calendario_caso_5_separatore_mese.png")
        assert out.exists()


# ---------------------------------------------------------------------------
# Caso 6 — Schermo largo con bordi colorati (show_border=True)
# ---------------------------------------------------------------------------


class TestCaso6SchermolargoConBordi:
    """Renderer a 1280px: show_border=True attiva i bordi verticali colorati
    a sinistra di ogni riga evento nella cella.
    """

    @pytest.fixture()
    def events(self) -> list[CalendarEvent]:
        return [
            _evt(
                uid="wide-1",
                title="Riunione di progetto",
                start_h=9,
                start_m=0,
                end_h=10,
                end_m=0,
                color="#E63946",
                day_offset=0,
            ),
            _evt(
                uid="wide-2",
                title="Pranzo con cliente",
                start_h=12,
                start_m=30,
                end_h=14,
                end_m=0,
                color="#457B9D",
                day_offset=1,
            ),
            _evt(
                uid="wide-3",
                title="Palestra",
                start_h=18,
                start_m=0,
                end_h=19,
                end_m=30,
                color="#2A9D8F",
                day_offset=3,
            ),
        ]

    def test_produces_png(
        self,
        renderer_wide: PillowEinkRenderer,
        palette: dict[str, str],
        events: list[CalendarEvent],
    ) -> None:
        state = NavigationState(anchor_date=date.today())

        img, draw = _make_canvas(width=_CANVAS_W_WIDE)
        renderer_wide._draw_mini_calendar(
            draw, (0, 0, _CANVAS_W_WIDE, _CANVAS_H), state, events, palette
        )

        out = _save(img, "calendario_caso_6_schermo_largo_bordi.png")
        assert out.exists()
