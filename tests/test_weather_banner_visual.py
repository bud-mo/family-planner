"""Visual rendering tests for the weather banner (_draw_weather).

Ogni test produce un PNG in ``tests/visual_output/`` per ispezione manuale.
I file sono deterministici (stessi dati) ma vengono riscritti ad ogni
esecuzione — non costituiscono un baseline di regressione pixel-perfect.

Casi coperti:
  1. Banner vuoto — nessun dato meteo (WeatherData())
  2. Solo temperatura corrente, senza icona né max/min
  3. Temperatura corrente + icona condizione, senza max/min
  4. Temperatura corrente + icona + max/min
  5. Banner completo con previsioni biorarie (6 slot)
  6. Banner completo — condizione nuvolosa con pioggia
  7. Banner su canvas stretto (layout landscape colonna sinistra ~400px)
"""
from __future__ import annotations

import types
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from app.renderer.eink_renderer import _SPECTRA6_PALETTE, _build_palette_image
from app.renderer.pillow_eink_renderer import PillowEinkRenderer
from app.renderer.tokens import (
    BANNER_HEIGHT,
    COLOR_BG,
    HourlySlot,
    WeatherData,
    get_palette,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_OUTPUT_DIR: Path = Path(__file__).parent / "visual_output"
_CANVAS_W: int = 800
_CANVAS_W_NARROW: int = 400


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


def _make_canvas(width: int = _CANVAS_W, height: int = BANNER_HEIGHT) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (width, height), COLOR_BG)
    draw = ImageDraw.Draw(img)
    return img, draw


def _hourly_slots() -> list[HourlySlot]:
    """Sei slot biorari di esempio dalle 08:00 alle 18:00."""
    return [
        HourlySlot(hour=8,  condition_icon="sun",             temp=19.0),
        HourlySlot(hour=10, condition_icon="cloud",           temp=21.0),
        HourlySlot(hour=12, condition_icon="sun",             temp=24.0),
        HourlySlot(hour=14, condition_icon="cloud",           temp=25.5),
        HourlySlot(hour=16, condition_icon="cloud-rain",      temp=23.0),
        HourlySlot(hour=18, condition_icon="cloud-drizzle",   temp=20.0),
    ]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", autouse=True)
def ensure_output_dir() -> None:
    _OUTPUT_DIR.mkdir(exist_ok=True)


@pytest.fixture(scope="module")
def renderer() -> PillowEinkRenderer:
    return _make_renderer()


@pytest.fixture()
def palette() -> dict[str, str]:
    return get_palette()


# ---------------------------------------------------------------------------
# Caso 1 — Banner vuoto (nessun dato meteo)
# ---------------------------------------------------------------------------


class TestCaso1EmptyWeather:
    """WeatherData() senza campi — il banner mostra solo la data."""

    def test_produces_png(self, renderer, palette):
        img, draw = _make_canvas()
        renderer._draw_weather(draw, img, (0, 0, _CANVAS_W, BANNER_HEIGHT), WeatherData(), palette)
        out = _OUTPUT_DIR / "weather_caso_1_vuoto.png"
        img.save(out)
        _to_spectra6(img).save(out.with_stem(out.stem + "_spectra6"))
        assert out.exists()

    def test_canvas_not_blank(self, renderer, palette):
        """Deve esserci almeno un pixel non-background (la data è sempre disegnata)."""
        img, draw = _make_canvas()
        renderer._draw_weather(draw, img, (0, 0, _CANVAS_W, BANNER_HEIGHT), WeatherData(), palette)
        bg = Image.new("RGB", (_CANVAS_W, BANNER_HEIGHT), COLOR_BG)
        assert list(img.getdata()) != list(bg.getdata())


# ---------------------------------------------------------------------------
# Caso 2 — Solo temperatura corrente
# ---------------------------------------------------------------------------


class TestCaso2SoloTemperaturaCorrente:
    """Temperatura corrente senza icona né max/min."""

    @pytest.fixture()
    def weather(self) -> WeatherData:
        return WeatherData(temp_current=22.0)

    def test_produces_png(self, renderer, palette, weather):
        img, draw = _make_canvas()
        renderer._draw_weather(draw, img, (0, 0, _CANVAS_W, BANNER_HEIGHT), weather, palette)
        out = _OUTPUT_DIR / "weather_caso_2_solo_temp.png"
        img.save(out)
        _to_spectra6(img).save(out.with_stem(out.stem + "_spectra6"))
        assert out.exists()

    def test_canvas_not_blank(self, renderer, palette, weather):
        img, draw = _make_canvas()
        renderer._draw_weather(draw, img, (0, 0, _CANVAS_W, BANNER_HEIGHT), weather, palette)
        bg = Image.new("RGB", (_CANVAS_W, BANNER_HEIGHT), COLOR_BG)
        assert list(img.getdata()) != list(bg.getdata())


# ---------------------------------------------------------------------------
# Caso 3 — Temperatura + icona condizione
# ---------------------------------------------------------------------------


class TestCaso3TempConIcona:
    """Temperatura corrente con icona condizione, senza max/min."""

    @pytest.fixture()
    def weather(self) -> WeatherData:
        return WeatherData(
            condition_icon="sun",
            description="Sereno",
            temp_current=24.0,
        )

    def test_produces_png(self, renderer, palette, weather):
        img, draw = _make_canvas()
        renderer._draw_weather(draw, img, (0, 0, _CANVAS_W, BANNER_HEIGHT), weather, palette)
        out = _OUTPUT_DIR / "weather_caso_3_temp_icona.png"
        img.save(out)
        _to_spectra6(img).save(out.with_stem(out.stem + "_spectra6"))
        assert out.exists()

    def test_canvas_not_blank(self, renderer, palette, weather):
        img, draw = _make_canvas()
        renderer._draw_weather(draw, img, (0, 0, _CANVAS_W, BANNER_HEIGHT), weather, palette)
        bg = Image.new("RGB", (_CANVAS_W, BANNER_HEIGHT), COLOR_BG)
        assert list(img.getdata()) != list(bg.getdata())


# ---------------------------------------------------------------------------
# Caso 4 — Temperatura + icona + max/min
# ---------------------------------------------------------------------------


class TestCaso4TempIconaMaxMin:
    """Temperatura corrente con icona e massima/minima giornaliera."""

    @pytest.fixture()
    def weather(self) -> WeatherData:
        return WeatherData(
            condition_icon="sun",
            description="Soleggiato",
            temp_current=26.0,
            temp_max=28.0,
            temp_min=14.0,
        )

    def test_produces_png(self, renderer, palette, weather):
        img, draw = _make_canvas()
        renderer._draw_weather(draw, img, (0, 0, _CANVAS_W, BANNER_HEIGHT), weather, palette)
        out = _OUTPUT_DIR / "weather_caso_4_temp_icona_maxmin.png"
        img.save(out)
        _to_spectra6(img).save(out.with_stem(out.stem + "_spectra6"))
        assert out.exists()

    def test_canvas_not_blank(self, renderer, palette, weather):
        img, draw = _make_canvas()
        renderer._draw_weather(draw, img, (0, 0, _CANVAS_W, BANNER_HEIGHT), weather, palette)
        bg = Image.new("RGB", (_CANVAS_W, BANNER_HEIGHT), COLOR_BG)
        assert list(img.getdata()) != list(bg.getdata())


# ---------------------------------------------------------------------------
# Caso 5 — Banner completo: sole con previsioni biorarie
# ---------------------------------------------------------------------------


class TestCaso5BannerCompletoSole:
    """Tutti i campi popolati — condizione serena con 6 slot biorari."""

    @pytest.fixture()
    def weather(self) -> WeatherData:
        return WeatherData(
            condition_icon="sun",
            description="Sereno",
            temp_current=24.0,
            temp_max=28.0,
            temp_min=13.0,
            hourly_forecast=_hourly_slots(),
        )

    def test_produces_png(self, renderer, palette, weather):
        img, draw = _make_canvas()
        renderer._draw_weather(draw, img, (0, 0, _CANVAS_W, BANNER_HEIGHT), weather, palette)
        out = _OUTPUT_DIR / "weather_caso_5_completo_sole.png"
        img.save(out)
        _to_spectra6(img).save(out.with_stem(out.stem + "_spectra6"))
        assert out.exists()

    def test_canvas_not_blank(self, renderer, palette, weather):
        img, draw = _make_canvas()
        renderer._draw_weather(draw, img, (0, 0, _CANVAS_W, BANNER_HEIGHT), weather, palette)
        bg = Image.new("RGB", (_CANVAS_W, BANNER_HEIGHT), COLOR_BG)
        assert list(img.getdata()) != list(bg.getdata())

    def test_hourly_row_rendered(self, renderer, palette, weather):
        """La fascia bioraria deve produrre pixel differenti dalla fascia principale."""
        img, draw = _make_canvas()
        renderer._draw_weather(draw, img, (0, 0, _CANVAS_W, BANNER_HEIGHT), weather, palette)

        # Confronta i pixel della sola fascia bioraria con un canvas bianco equivalente
        from app.renderer.tokens import BANNER_MAIN_HEIGHT, BANNER_HOURLY_HEIGHT
        hourly_box = img.crop((0, BANNER_MAIN_HEIGHT, _CANVAS_W, BANNER_MAIN_HEIGHT + BANNER_HOURLY_HEIGHT))
        blank = Image.new("RGB", (_CANVAS_W, BANNER_HOURLY_HEIGHT), COLOR_BG)
        assert list(hourly_box.getdata()) != list(blank.getdata())


# ---------------------------------------------------------------------------
# Caso 6 — Banner completo: pioggia
# ---------------------------------------------------------------------------


class TestCaso6BannerCompletoPioggia:
    """Tutti i campi popolati — condizione di pioggia con 6 slot biorari."""

    @pytest.fixture()
    def weather(self) -> WeatherData:
        return WeatherData(
            condition_icon="cloud-rain",
            description="Pioggia",
            temp_current=16.0,
            temp_max=18.0,
            temp_min=12.0,
            hourly_forecast=[
                HourlySlot(hour=8,  condition_icon="cloud-rain",    temp=14.0),
                HourlySlot(hour=10, condition_icon="cloud-rain",    temp=15.0),
                HourlySlot(hour=12, condition_icon="cloud-drizzle", temp=16.0),
                HourlySlot(hour=14, condition_icon="cloud",         temp=17.0),
                HourlySlot(hour=16, condition_icon="cloud",         temp=16.5),
                HourlySlot(hour=18, condition_icon="cloud-rain",    temp=15.0),
            ],
        )

    def test_produces_png(self, renderer, palette, weather):
        img, draw = _make_canvas()
        renderer._draw_weather(draw, img, (0, 0, _CANVAS_W, BANNER_HEIGHT), weather, palette)
        out = _OUTPUT_DIR / "weather_caso_6_completo_pioggia.png"
        img.save(out)
        _to_spectra6(img).save(out.with_stem(out.stem + "_spectra6"))
        assert out.exists()

    def test_canvas_not_blank(self, renderer, palette, weather):
        img, draw = _make_canvas()
        renderer._draw_weather(draw, img, (0, 0, _CANVAS_W, BANNER_HEIGHT), weather, palette)
        bg = Image.new("RGB", (_CANVAS_W, BANNER_HEIGHT), COLOR_BG)
        assert list(img.getdata()) != list(bg.getdata())


# ---------------------------------------------------------------------------
# Caso 7 — Canvas stretto (layout landscape, colonna ~400px)
# ---------------------------------------------------------------------------


class TestCaso7CanvasStretto:
    """Banner su canvas stretto: la data deve adattarsi (formato abbreviato)."""

    @pytest.fixture()
    def weather(self) -> WeatherData:
        return WeatherData(
            condition_icon="sun",
            description="Sereno",
            temp_current=22.0,
            temp_max=25.0,
            temp_min=11.0,
            hourly_forecast=_hourly_slots(),
        )

    def test_produces_png(self, renderer, palette, weather):
        img, draw = _make_canvas(width=_CANVAS_W_NARROW)
        renderer._draw_weather(draw, img, (0, 0, _CANVAS_W_NARROW, BANNER_HEIGHT), weather, palette)
        out = _OUTPUT_DIR / "weather_caso_7_canvas_stretto.png"
        img.save(out)
        _to_spectra6(img).save(out.with_stem(out.stem + "_spectra6"))
        assert out.exists()

    def test_canvas_not_blank(self, renderer, palette, weather):
        img, draw = _make_canvas(width=_CANVAS_W_NARROW)
        renderer._draw_weather(draw, img, (0, 0, _CANVAS_W_NARROW, BANNER_HEIGHT), weather, palette)
        bg = Image.new("RGB", (_CANVAS_W_NARROW, BANNER_HEIGHT), COLOR_BG)
        assert list(img.getdata()) != list(bg.getdata())
