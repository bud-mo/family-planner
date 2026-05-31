"""Visual rendering tests for the agenda component (_draw_agenda).

Ogni test produce un PNG in ``tests/visual_output/`` per ispezione manuale.
I file sono deterministi (stessa data, stessi dati) ma vengono riscritti ad
ogni esecuzione — non costituiscono un baseline di regressione pixel-perfect.

Casi coperti:
  1. Singolo evento con orario inizio/fine e titolo
  2. Singolo evento con orario inizio/fine, titolo e descrizione
  3. Singolo evento tutto-il-giorno con titolo
  4. Due eventi nello stesso giorno con orario, titolo e descrizione
  5. Quattro eventi su due giornate: mix tutto-il-giorno / con orario, con e senza descrizione
  6. Due appuntamenti su due giorni diversi: primo solo titolo, secondo titolo e descrizione
  7. Due eventi su due giorni: il primo ha un luogo impostato, il secondo no
  8. Due eventi su due giorni: il primo ha descrizione e luogo, il secondo solo titolo
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
from app.renderer.tokens import COLOR_BG, get_palette

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_OUTPUT_DIR: Path = Path(__file__).parent / "visual_output"
_CANVAS_W: int = 800


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


def _make_renderer() -> PillowEinkRenderer:
    cfg = types.SimpleNamespace(
        display=types.SimpleNamespace(
            width=800, height=480, layout="portrait", type="hdmi"
        ),
        timezone="local",
    )
    return PillowEinkRenderer(cfg)


def _make_canvas(height: int) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (_CANVAS_W, height), COLOR_BG)
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
) -> CalendarEvent:
    today = date.today() + timedelta(days=day_offset)
    start_dt = datetime(today.year, today.month, today.day, start_h, start_m, tzinfo=timezone.utc)
    end_dt = datetime(today.year, today.month, today.day, end_h, end_m, tzinfo=timezone.utc)
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def renderer() -> PillowEinkRenderer:
    _OUTPUT_DIR.mkdir(exist_ok=True)
    return _make_renderer()


@pytest.fixture()
def palette() -> dict[str, str]:
    return get_palette()


@pytest.fixture()
def today_state() -> NavigationState:
    return NavigationState(anchor_date=date.today())


# ---------------------------------------------------------------------------
# Caso 1 — Singolo evento: orario, titolo
# ---------------------------------------------------------------------------


class TestCaso1SingleEventWithTime:
    """Un solo evento nella giornata con orario di inizio/fine e titolo."""

    HEIGHT = 128

    @pytest.fixture()
    def events(self) -> list[CalendarEvent]:
        return [
            _evt(
                uid="c1-e1",
                title="Riunione di lavoro",
                start_h=8,
                start_m=0,
                end_h=8,
                end_m=30,
                color="#E27B3E",
            )
        ]

    def test_produces_png(self, renderer, palette, today_state, events, tmp_path):
        img, draw = _make_canvas(self.HEIGHT)
        renderer._draw_agenda(draw, img, (0, 0, _CANVAS_W, self.HEIGHT), today_state, events, palette)
        out = _OUTPUT_DIR / "caso_1_singolo_con_orario.png"
        img.save(out)
        _to_spectra6(img).save(out.with_stem(out.stem + "_spectra6"))
        assert out.exists()

    def test_canvas_not_blank(self, renderer, palette, today_state, events):
        """Deve esserci almeno un pixel non-background."""
        img, draw = _make_canvas(self.HEIGHT)
        renderer._draw_agenda(draw, img, (0, 0, _CANVAS_W, self.HEIGHT), today_state, events, palette)
        bg = Image.new("RGB", (_CANVAS_W, self.HEIGHT), COLOR_BG)
        assert list(img.getdata()) != list(bg.getdata())


# ---------------------------------------------------------------------------
# Caso 2 — Singolo evento: orario, titolo, descrizione
# ---------------------------------------------------------------------------


class TestCaso2SingleEventWithTimeAndDescription:
    """Un solo evento nella giornata con orario, titolo e descrizione HTML."""

    HEIGHT = 220

    @pytest.fixture()
    def events(self) -> list[CalendarEvent]:
        return [
            _evt(
                uid="c2-e1",
                title="Call con cliente",
                start_h=11,
                start_m=30,
                end_h=12,
                end_m=0,
                description=(
                    "Note di preparazione:\n"
                    "<ul>"
                    "<li>Revisione budget Q3</li>"
                    "<li>Timeline rilascio</li>"
                    "<li>Prossimi step</li>"
                    "</ul>"
                ),
                color="#4A90D9",
            )
        ]

    def test_produces_png(self, renderer, palette, today_state, events):
        img, draw = _make_canvas(self.HEIGHT)
        renderer._draw_agenda(draw, img, (0, 0, _CANVAS_W, self.HEIGHT), today_state, events, palette)
        out = _OUTPUT_DIR / "caso_2_singolo_con_orario_e_descrizione.png"
        img.save(out)
        _to_spectra6(img).save(out.with_stem(out.stem + "_spectra6"))
        assert out.exists()

    def test_canvas_not_blank(self, renderer, palette, today_state, events):
        img, draw = _make_canvas(self.HEIGHT)
        renderer._draw_agenda(draw, img, (0, 0, _CANVAS_W, self.HEIGHT), today_state, events, palette)
        bg = Image.new("RGB", (_CANVAS_W, self.HEIGHT), COLOR_BG)
        assert list(img.getdata()) != list(bg.getdata())


# ---------------------------------------------------------------------------
# Caso 3 — Singolo evento: tutto il giorno, titolo
# ---------------------------------------------------------------------------


class TestCaso3AllDayEvent:
    """Un solo evento tutto-il-giorno con titolo."""

    HEIGHT = 128

    @pytest.fixture()
    def events(self) -> list[CalendarEvent]:
        return [
            _evt(
                uid="c3-e1",
                title="Compleanno di Marco",
                start_h=0,
                start_m=0,
                end_h=23,
                end_m=59,
                all_day=True,
                color="#5BAD6F",
            )
        ]

    def test_produces_png(self, renderer, palette, today_state, events):
        img, draw = _make_canvas(self.HEIGHT)
        renderer._draw_agenda(draw, img, (0, 0, _CANVAS_W, self.HEIGHT), today_state, events, palette)
        out = _OUTPUT_DIR / "caso_3_tutto_il_giorno.png"
        img.save(out)
        _to_spectra6(img).save(out.with_stem(out.stem + "_spectra6"))
        assert out.exists()

    def test_tutto_il_giorno_label_renders(self, renderer, palette, today_state, events):
        """Il testo 'Tutto il giorno' deve produrre pixel nel canvas."""
        img, draw = _make_canvas(self.HEIGHT)
        renderer._draw_agenda(draw, img, (0, 0, _CANVAS_W, self.HEIGHT), today_state, events, palette)
        bg = Image.new("RGB", (_CANVAS_W, self.HEIGHT), COLOR_BG)
        assert list(img.getdata()) != list(bg.getdata())


# ---------------------------------------------------------------------------
# Caso 4 — Due eventi nella stessa giornata: orario, titolo, descrizione
# ---------------------------------------------------------------------------


class TestCaso4TwoEventsWithDescription:
    """Due eventi nello stesso giorno, entrambi con orario, titolo e descrizione."""

    HEIGHT = 336

    @pytest.fixture()
    def events(self) -> list[CalendarEvent]:
        return [
            _evt(
                uid="c4-e1",
                title="Standup mattutino",
                start_h=9,
                start_m=0,
                end_h=9,
                end_m=30,
                description="Daily standup del team di sviluppo.\nAggiornamento attività in corso.",
                color="#E27B3E",
            ),
            _evt(
                uid="c4-e2",
                title="Review Sprint",
                start_h=15,
                start_m=0,
                end_h=16,
                end_m=30,
                description=(
                    "<b>Sprint review</b> — demo delle features completate.\n"
                    "<ul>"
                    "<li>Team dev</li>"
                    "<li>Product Owner</li>"
                    "<li>Stakeholder</li>"
                    "</ul>"
                ),
                color="#4A90D9",
            ),
        ]

    def test_produces_png(self, renderer, palette, today_state, events):
        img, draw = _make_canvas(self.HEIGHT)
        renderer._draw_agenda(draw, img, (0, 0, _CANVAS_W, self.HEIGHT), today_state, events, palette)
        out = _OUTPUT_DIR / "caso_4_due_eventi_con_descrizione.png"
        img.save(out)
        _to_spectra6(img).save(out.with_stem(out.stem + "_spectra6"))
        assert out.exists()

    def test_canvas_not_blank(self, renderer, palette, today_state, events):
        img, draw = _make_canvas(self.HEIGHT)
        renderer._draw_agenda(draw, img, (0, 0, _CANVAS_W, self.HEIGHT), today_state, events, palette)
        bg = Image.new("RGB", (_CANVAS_W, self.HEIGHT), COLOR_BG)
        assert list(img.getdata()) != list(bg.getdata())


# ---------------------------------------------------------------------------
# Caso 5 — Quattro eventi su due giornate: mix tutto-il-giorno / con orario,
#           con e senza descrizione
# ---------------------------------------------------------------------------


class TestCaso5FourEventsTwoDays:
    """Quattro eventi distribuiti su due giorni consecutivi.

    Giorno 1 (oggi):
      - Tutto il giorno, senza descrizione
      - Con orario, con descrizione
    Giorno 2 (domani):
      - Con orario, senza descrizione
      - Tutto il giorno, con descrizione
    """

    HEIGHT = 412

    @pytest.fixture()
    def events(self) -> list[CalendarEvent]:
        return [
            # Giorno 1 — tutto il giorno, senza descrizione
            _evt(
                uid="c5-e1",
                title="Festa della Repubblica",
                start_h=0,
                start_m=0,
                end_h=23,
                end_m=59,
                all_day=True,
                color="#5BAD6F",
                day_offset=0,
            ),
            # Giorno 1 — con orario, con descrizione
            _evt(
                uid="c5-e2",
                title="Riunione di kick-off",
                start_h=10,
                start_m=0,
                end_h=11,
                end_m=30,
                description=(
                    "<b>Obiettivi della riunione:</b>\n"
                    "<ul>"
                    "<li>Definire scope del progetto</li>"
                    "<li>Assegnare responsabilità</li>"
                    "</ul>"
                ),
                color="#E27B3E",
                day_offset=0,
            ),
            # Giorno 2 — con orario, senza descrizione
            _evt(
                uid="c5-e3",
                title="Standup mattutino",
                start_h=9,
                start_m=0,
                end_h=9,
                end_m=30,
                color="#4A90D9",
                day_offset=1,
            ),
            # Giorno 2 — tutto il giorno, con descrizione
            _evt(
                uid="c5-e4",
                title="Scadenza consegna report",
                start_h=0,
                start_m=0,
                end_h=23,
                end_m=59,
                all_day=True,
                description="Inviare il report trimestrale via email entro fine giornata.",
                color="#9B59B6",
                day_offset=1,
            ),
        ]

    def test_produces_png(self, renderer, palette, today_state, events):
        img, draw = _make_canvas(self.HEIGHT)
        renderer._draw_agenda(draw, img, (0, 0, _CANVAS_W, self.HEIGHT), today_state, events, palette)
        out = _OUTPUT_DIR / "caso_5_quattro_eventi_due_giornate.png"
        img.save(out)
        _to_spectra6(img).save(out.with_stem(out.stem + "_spectra6"))
        assert out.exists()

    def test_canvas_not_blank(self, renderer, palette, today_state, events):
        img, draw = _make_canvas(self.HEIGHT)
        renderer._draw_agenda(draw, img, (0, 0, _CANVAS_W, self.HEIGHT), today_state, events, palette)
        bg = Image.new("RGB", (_CANVAS_W, self.HEIGHT), COLOR_BG)
        assert list(img.getdata()) != list(bg.getdata())


# ---------------------------------------------------------------------------
# Caso 6 — Due appuntamenti su due giorni diversi:
#           il primo solo titolo, il secondo titolo e descrizione
# ---------------------------------------------------------------------------


class TestCaso6TwoEventsTwoDaysTitleVsDescription:
    """Due appuntamenti su giorni consecutivi.

    Giorno 1 (oggi):   solo titolo (nessuna descrizione).
    Giorno 2 (domani): titolo + descrizione HTML.
    """

    HEIGHT = 300

    @pytest.fixture()
    def events(self) -> list[CalendarEvent]:
        return [
            # Giorno 1 — solo titolo
            _evt(
                uid="c6-e1",
                title="Visita medica",
                start_h=10,
                start_m=0,
                end_h=10,
                end_m=45,
                color="#E27B3E",
                day_offset=0,
            ),
            # Giorno 2 — titolo + descrizione
            _evt(
                uid="c6-e2",
                title="Riunione di progetto",
                start_h=14,
                start_m=30,
                end_h=16,
                end_m=0,
                description=(
                    "<b>Ordine del giorno:</b>\n"
                    "<ul>"
                    "<li>Avanzamento attività</li>"
                    "<li>Blocchi e rischi</li>"
                    "<li>Prossimi step</li>"
                    "</ul>"
                ),
                color="#4A90D9",
                day_offset=1,
            ),
        ]

    def test_produces_png(self, renderer, palette, today_state, events):
        img, draw = _make_canvas(self.HEIGHT)
        renderer._draw_agenda(draw, img, (0, 0, _CANVAS_W, self.HEIGHT), today_state, events, palette)
        out = _OUTPUT_DIR / "caso_6_due_eventi_due_giorni_titolo_vs_descrizione.png"
        img.save(out)
        _to_spectra6(img).save(out.with_stem(out.stem + "_spectra6"))
        assert out.exists()

    def test_canvas_not_blank(self, renderer, palette, today_state, events):
        img, draw = _make_canvas(self.HEIGHT)
        renderer._draw_agenda(draw, img, (0, 0, _CANVAS_W, self.HEIGHT), today_state, events, palette)
        bg = Image.new("RGB", (_CANVAS_W, self.HEIGHT), COLOR_BG)
        assert list(img.getdata()) != list(bg.getdata())


# ---------------------------------------------------------------------------
# Caso 7 — Due eventi su due giorni: il primo ha un luogo impostato
# ---------------------------------------------------------------------------


class TestCaso7TwoEventsTwoDaysWithLocation:
    """Due appuntamenti su giorni consecutivi.

    Giorno 1 (oggi):   orario, titolo e luogo.
    Giorno 2 (domani): orario e titolo (nessun luogo).
    """

    HEIGHT = 260

    @pytest.fixture()
    def events(self) -> list[CalendarEvent]:
        return [
            # Giorno 1 — con luogo
            _evt(
                uid="c7-e1",
                title="Colloquio di lavoro",
                start_h=10,
                start_m=0,
                end_h=11,
                end_m=0,
                location="Via Roma 42, Milano",
                color="#E27B3E",
                day_offset=0,
            ),
            # Giorno 2 — senza luogo
            _evt(
                uid="c7-e2",
                title="Standup mattutino",
                start_h=9,
                start_m=0,
                end_h=9,
                end_m=30,
                color="#4A90D9",
                day_offset=1,
            ),
        ]

    def test_produces_png(self, renderer, palette, today_state, events):
        img, draw = _make_canvas(self.HEIGHT)
        renderer._draw_agenda(draw, img, (0, 0, _CANVAS_W, self.HEIGHT), today_state, events, palette)
        out = _OUTPUT_DIR / "caso_7_due_eventi_due_giorni_con_luogo.png"
        img.save(out)
        _to_spectra6(img).save(out.with_stem(out.stem + "_spectra6"))
        assert out.exists()

    def test_canvas_not_blank(self, renderer, palette, today_state, events):
        img, draw = _make_canvas(self.HEIGHT)
        renderer._draw_agenda(draw, img, (0, 0, _CANVAS_W, self.HEIGHT), today_state, events, palette)
        bg = Image.new("RGB", (_CANVAS_W, self.HEIGHT), COLOR_BG)
        assert list(img.getdata()) != list(bg.getdata())


# ---------------------------------------------------------------------------
# Caso 8 — Due eventi su due giorni: il primo ha descrizione e luogo
# ---------------------------------------------------------------------------


class TestCaso8TwoEventsTwoDaysLocationAndDescription:
    """Due appuntamenti su giorni consecutivi.

    Giorno 1 (oggi):   orario, titolo, luogo e descrizione HTML.
    Giorno 2 (domani): orario e titolo (nessun luogo, nessuna descrizione).
    """

    HEIGHT = 320

    @pytest.fixture()
    def events(self) -> list[CalendarEvent]:
        return [
            # Giorno 1 — con luogo e descrizione
            _evt(
                uid="c8-e1",
                title="Riunione con fornitore",
                start_h=14,
                start_m=0,
                end_h=15,
                end_m=30,
                location="Sala Riunioni B, Via Montenapoleone 8, Milano",
                description=(
                    "<b>Punti all'ordine del giorno:</b>\n"
                    "<ul>"
                    "<li>Revisione contratto</li>"
                    "<li>Tempi di consegna</li>"
                    "<li>Prezzi e sconti</li>"
                    "</ul>"
                ),
                color="#E27B3E",
                day_offset=0,
            ),
            # Giorno 2 — solo titolo
            _evt(
                uid="c8-e2",
                title="Standup mattutino",
                start_h=9,
                start_m=0,
                end_h=9,
                end_m=30,
                color="#4A90D9",
                day_offset=1,
            ),
        ]

    def test_produces_png(self, renderer, palette, today_state, events):
        img, draw = _make_canvas(self.HEIGHT)
        renderer._draw_agenda(draw, img, (0, 0, _CANVAS_W, self.HEIGHT), today_state, events, palette)
        out = _OUTPUT_DIR / "caso_8_due_eventi_due_giorni_luogo_e_descrizione.png"
        img.save(out)
        _to_spectra6(img).save(out.with_stem(out.stem + "_spectra6"))
        assert out.exists()

    def test_canvas_not_blank(self, renderer, palette, today_state, events):
        img, draw = _make_canvas(self.HEIGHT)
        renderer._draw_agenda(draw, img, (0, 0, _CANVAS_W, self.HEIGHT), today_state, events, palette)
        bg = Image.new("RGB", (_CANVAS_W, self.HEIGHT), COLOR_BG)
        assert list(img.getdata()) != list(bg.getdata())
