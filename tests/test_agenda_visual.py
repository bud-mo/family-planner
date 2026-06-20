"""Visual rendering tests for the agenda component (_draw_agenda).

Each test writes a PNG to ``tests/visual_output/`` for manual inspection.
Files are deterministic (same date, same data) but rewritten on every run,
so they are not a pixel-perfect regression baseline.

Covered scenarios:
    1. Single event with start/end time and title
    2. Single event with start/end time, title, and description
    3. Single all-day event with title
    4. Two events on the same day with time, title, and description
    5. Four events across two days: mixed all-day / timed, with and without description
    6. Two appointments on two different days: first with title only, second with title and description
    7. Two events on two days: first has a location, second does not
    8. Two events on two days: first has description and location, second has title only
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
            resolution=(800, 480), layout="portrait"
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
        calendar_name="Test Calendar",
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
# Case 1 — Single event: time, title
# ---------------------------------------------------------------------------


class TestCase1SingleEventWithTime:
    """A single event in the day with start/end time and title."""

    HEIGHT = 128

    @pytest.fixture()
    def events(self) -> list[CalendarEvent]:
        return [
            _evt(
                uid="c1-e1",
                title="Work meeting",
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
        out = _OUTPUT_DIR / "agenda_case_1_single_with_time.png"
        img.save(out)
        _to_spectra6(img).save(out.with_stem(out.stem + "_spectra6"))
        assert out.exists()

    def test_canvas_not_blank(self, renderer, palette, today_state, events):
        """There should be at least one non-background pixel."""
        img, draw = _make_canvas(self.HEIGHT)
        renderer._draw_agenda(draw, img, (0, 0, _CANVAS_W, self.HEIGHT), today_state, events, palette)
        bg = Image.new("RGB", (_CANVAS_W, self.HEIGHT), COLOR_BG)
        assert list(img.getdata()) != list(bg.getdata())


# ---------------------------------------------------------------------------
# Case 2 — Single event: time, title, description
# ---------------------------------------------------------------------------


class TestCase2SingleEventWithTimeAndDescription:
    """A single event in the day with time, title, and HTML description."""

    HEIGHT = 220

    @pytest.fixture()
    def events(self) -> list[CalendarEvent]:
        return [
            _evt(
                uid="c2-e1",
                title="Client call",
                start_h=11,
                start_m=30,
                end_h=12,
                end_m=0,
                description=(
                    "Preparation notes:\n"
                    "<ul>"
                    "<li>Q3 budget review</li>"
                    "<li>Release timeline</li>"
                    "<li>Next steps</li>"
                    "</ul>"
                ),
                color="#4A90D9",
            )
        ]

    def test_produces_png(self, renderer, palette, today_state, events):
        img, draw = _make_canvas(self.HEIGHT)
        renderer._draw_agenda(draw, img, (0, 0, _CANVAS_W, self.HEIGHT), today_state, events, palette)
        out = _OUTPUT_DIR / "agenda_case_2_single_with_time_and_description.png"
        img.save(out)
        _to_spectra6(img).save(out.with_stem(out.stem + "_spectra6"))
        assert out.exists()

    def test_canvas_not_blank(self, renderer, palette, today_state, events):
        img, draw = _make_canvas(self.HEIGHT)
        renderer._draw_agenda(draw, img, (0, 0, _CANVAS_W, self.HEIGHT), today_state, events, palette)
        bg = Image.new("RGB", (_CANVAS_W, self.HEIGHT), COLOR_BG)
        assert list(img.getdata()) != list(bg.getdata())


# ---------------------------------------------------------------------------
# Case 3 — Single event: all day, title
# ---------------------------------------------------------------------------


class TestCase3AllDayEvent:
    """A single all-day event with title."""

    HEIGHT = 128

    @pytest.fixture()
    def events(self) -> list[CalendarEvent]:
        return [
            _evt(
                uid="c3-e1",
                title="Marco's birthday",
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
        out = _OUTPUT_DIR / "agenda_case_3_all_day.png"
        img.save(out)
        _to_spectra6(img).save(out.with_stem(out.stem + "_spectra6"))
        assert out.exists()

    def test_all_day_label_renders(self, renderer, palette, today_state, events):
        """The 'All day' label should produce pixels on the canvas."""
        img, draw = _make_canvas(self.HEIGHT)
        renderer._draw_agenda(draw, img, (0, 0, _CANVAS_W, self.HEIGHT), today_state, events, palette)
        bg = Image.new("RGB", (_CANVAS_W, self.HEIGHT), COLOR_BG)
        assert list(img.getdata()) != list(bg.getdata())


# ---------------------------------------------------------------------------
# Case 4 — Two events on the same day: time, title, description
# ---------------------------------------------------------------------------


class TestCase4TwoEventsWithDescription:
    """Two events on the same day, both with time, title, and description."""

    HEIGHT = 336

    @pytest.fixture()
    def events(self) -> list[CalendarEvent]:
        return [
            _evt(
                uid="c4-e1",
                title="Morning standup",
                start_h=9,
                start_m=0,
                end_h=9,
                end_m=30,
                description="Daily standup for the development team.\nUpdate on ongoing work.",
                color="#E27B3E",
            ),
            _evt(
                uid="c4-e2",
                title="Sprint review",
                start_h=15,
                start_m=0,
                end_h=16,
                end_m=30,
                description=(
                    "<b>Sprint review</b> - demo of completed features.\n"
                    "<ul>"
                    "<li>Development team</li>"
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
        out = _OUTPUT_DIR / "agenda_case_4_two_events_with_description.png"
        img.save(out)
        _to_spectra6(img).save(out.with_stem(out.stem + "_spectra6"))
        assert out.exists()

    def test_canvas_not_blank(self, renderer, palette, today_state, events):
        img, draw = _make_canvas(self.HEIGHT)
        renderer._draw_agenda(draw, img, (0, 0, _CANVAS_W, self.HEIGHT), today_state, events, palette)
        bg = Image.new("RGB", (_CANVAS_W, self.HEIGHT), COLOR_BG)
        assert list(img.getdata()) != list(bg.getdata())


# ---------------------------------------------------------------------------
# Case 5 — Four events across two days: mixed all-day / timed,
#          with and without description
# ---------------------------------------------------------------------------


class TestCase5FourEventsTwoDays:
    """Four events distributed across two consecutive days.

    Day 1 (today):
      - All day, no description
      - Timed, with description
    Day 2 (tomorrow):
      - Timed, no description
      - All day, with description
    """

    HEIGHT = 412

    @pytest.fixture()
    def events(self) -> list[CalendarEvent]:
        return [
            # Day 1 — all day, no description
            _evt(
                uid="c5-e1",
                title="Republic Day",
                start_h=0,
                start_m=0,
                end_h=23,
                end_m=59,
                all_day=True,
                color="#5BAD6F",
                day_offset=0,
            ),
            # Day 1 — timed, with description
            _evt(
                uid="c5-e2",
                title="Kick-off meeting",
                start_h=10,
                start_m=0,
                end_h=11,
                end_m=30,
                description=(
                    "<b>Meeting goals:</b>\n"
                    "<ul>"
                    "<li>Define project scope</li>"
                    "<li>Assign responsibilities</li>"
                    "</ul>"
                ),
                color="#E27B3E",
                day_offset=0,
            ),
            # Day 2 — timed, no description
            _evt(
                uid="c5-e3",
                title="Morning standup",
                start_h=9,
                start_m=0,
                end_h=9,
                end_m=30,
                color="#4A90D9",
                day_offset=1,
            ),
            # Day 2 — all day, with description
            _evt(
                uid="c5-e4",
                title="Report delivery deadline",
                start_h=0,
                start_m=0,
                end_h=23,
                end_m=59,
                all_day=True,
                description="Send the quarterly report by email before end of day.",
                color="#9B59B6",
                day_offset=1,
            ),
        ]

    def test_produces_png(self, renderer, palette, today_state, events):
        img, draw = _make_canvas(self.HEIGHT)
        renderer._draw_agenda(draw, img, (0, 0, _CANVAS_W, self.HEIGHT), today_state, events, palette)
        out = _OUTPUT_DIR / "agenda_case_5_four_events_two_days.png"
        img.save(out)
        _to_spectra6(img).save(out.with_stem(out.stem + "_spectra6"))
        assert out.exists()

    def test_canvas_not_blank(self, renderer, palette, today_state, events):
        img, draw = _make_canvas(self.HEIGHT)
        renderer._draw_agenda(draw, img, (0, 0, _CANVAS_W, self.HEIGHT), today_state, events, palette)
        bg = Image.new("RGB", (_CANVAS_W, self.HEIGHT), COLOR_BG)
        assert list(img.getdata()) != list(bg.getdata())


# ---------------------------------------------------------------------------
# Case 6 — Two appointments on two different days:
#          first with title only, second with title and description
# ---------------------------------------------------------------------------


class TestCase6TwoEventsTwoDaysTitleVsDescription:
    """Two appointments across consecutive days.

    Day 1 (today): title only (no description).
    Day 2 (tomorrow): title + HTML description.
    """

    HEIGHT = 300

    @pytest.fixture()
    def events(self) -> list[CalendarEvent]:
        return [
            # Day 1 — title only
            _evt(
                uid="c6-e1",
                title="Medical checkup",
                start_h=10,
                start_m=0,
                end_h=10,
                end_m=45,
                color="#E27B3E",
                day_offset=0,
            ),
            # Day 2 — title + description
            _evt(
                uid="c6-e2",
                title="Project meeting",
                start_h=14,
                start_m=30,
                end_h=16,
                end_m=0,
                description=(
                    "<b>Agenda:</b>\n"
                    "<ul>"
                    "<li>Progress update</li>"
                    "<li>Blockers and risks</li>"
                    "<li>Next steps</li>"
                    "</ul>"
                ),
                color="#4A90D9",
                day_offset=1,
            ),
        ]

    def test_produces_png(self, renderer, palette, today_state, events):
        img, draw = _make_canvas(self.HEIGHT)
        renderer._draw_agenda(draw, img, (0, 0, _CANVAS_W, self.HEIGHT), today_state, events, palette)
        out = _OUTPUT_DIR / "agenda_case_6_two_events_two_days_title_vs_description.png"
        img.save(out)
        _to_spectra6(img).save(out.with_stem(out.stem + "_spectra6"))
        assert out.exists()

    def test_canvas_not_blank(self, renderer, palette, today_state, events):
        img, draw = _make_canvas(self.HEIGHT)
        renderer._draw_agenda(draw, img, (0, 0, _CANVAS_W, self.HEIGHT), today_state, events, palette)
        bg = Image.new("RGB", (_CANVAS_W, self.HEIGHT), COLOR_BG)
        assert list(img.getdata()) != list(bg.getdata())


# ---------------------------------------------------------------------------
# Case 7 — Two events on two days: the first has a location
# ---------------------------------------------------------------------------


class TestCase7TwoEventsTwoDaysWithLocation:
    """Two appointments across consecutive days.

    Day 1 (today): time, title, and location.
    Day 2 (tomorrow): time and title (no location).
    """

    HEIGHT = 260

    @pytest.fixture()
    def events(self) -> list[CalendarEvent]:
        return [
            # Day 1 — with location
            _evt(
                uid="c7-e1",
                title="Job interview",
                start_h=10,
                start_m=0,
                end_h=11,
                end_m=0,
                location="42 Via Roma, Milan",
                color="#E27B3E",
                day_offset=0,
            ),
            # Day 2 — without location
            _evt(
                uid="c7-e2",
                title="Morning standup",
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
        out = _OUTPUT_DIR / "agenda_case_7_two_events_two_days_with_location.png"
        img.save(out)
        _to_spectra6(img).save(out.with_stem(out.stem + "_spectra6"))
        assert out.exists()

    def test_canvas_not_blank(self, renderer, palette, today_state, events):
        img, draw = _make_canvas(self.HEIGHT)
        renderer._draw_agenda(draw, img, (0, 0, _CANVAS_W, self.HEIGHT), today_state, events, palette)
        bg = Image.new("RGB", (_CANVAS_W, self.HEIGHT), COLOR_BG)
        assert list(img.getdata()) != list(bg.getdata())


# ---------------------------------------------------------------------------
# Case 8 — Two events on two days: the first has description and location
# ---------------------------------------------------------------------------


class TestCase8TwoEventsTwoDaysLocationAndDescription:
    """Two appointments across consecutive days.

    Day 1 (today): time, title, location, and HTML description.
    Day 2 (tomorrow): time and title (no location, no description).
    """

    HEIGHT = 320

    @pytest.fixture()
    def events(self) -> list[CalendarEvent]:
        return [
            # Day 1 — with location and description
            _evt(
                uid="c8-e1",
                title="Supplier meeting",
                start_h=14,
                start_m=0,
                end_h=15,
                end_m=30,
                location="Meeting Room B, 8 Via Montenapoleone, Milan",
                description=(
                    "<b>Agenda items:</b>\n"
                    "<ul>"
                    "<li>Contract review</li>"
                    "<li>Delivery timelines</li>"
                    "<li>Pricing and discounts</li>"
                    "</ul>"
                ),
                color="#E27B3E",
                day_offset=0,
            ),
            # Day 2 — title only
            _evt(
                uid="c8-e2",
                title="Morning standup",
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
        out = _OUTPUT_DIR / "agenda_case_8_two_events_two_days_location_and_description.png"
        img.save(out)
        _to_spectra6(img).save(out.with_stem(out.stem + "_spectra6"))
        assert out.exists()

    def test_canvas_not_blank(self, renderer, palette, today_state, events):
        img, draw = _make_canvas(self.HEIGHT)
        renderer._draw_agenda(draw, img, (0, 0, _CANVAS_W, self.HEIGHT), today_state, events, palette)
        bg = Image.new("RGB", (_CANVAS_W, self.HEIGHT), COLOR_BG)
        assert list(img.getdata()) != list(bg.getdata())
