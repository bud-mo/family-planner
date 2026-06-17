"""Weather banner — date + current conditions row, plus the bihourly strip."""
from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from app.renderer.locale_it import (
    DAY_NAMES_FULL_IT as _DAY_NAMES_FULL_IT,
    MONTH_NAMES_IT as _MONTH_NAMES_IT,
    MONTH_NAMES_SHORT_IT as _MONTH_NAMES_SHORT_IT,
)
from app.renderer.tokens import (
    BANNER_HOURLY_HEIGHT,
    BANNER_MAIN_HEIGHT,
    TEXT_XS,
    WEATHER_ICON_COLORS,
    WeatherData,
)

if TYPE_CHECKING:
    from app.renderer.components.context import RenderContext

Rect = tuple[int, int, int, int]


def draw_weather(ctx: "RenderContext", rect: Rect, weather: WeatherData) -> None:
    x0, y0, w, h = rect
    palette = ctx.palette
    fonts = ctx.fonts
    draw = ctx.draw

    today = date.today()
    date_str = (
        f"{_DAY_NAMES_FULL_IT[today.weekday()]}, "
        f"{today.day} {_MONTH_NAMES_IT[today.month - 1]} {today.year}"
    )
    # In narrow landscape columns, shorten the date to prevent overflow onto weather data
    _max_date_w = int(w * 0.65)
    if draw.textlength(date_str, font=fonts.temp) > _max_date_w:
        date_str = (
            f"{_DAY_NAMES_FULL_IT[today.weekday()]}, "
            f"{today.day} {_MONTH_NAMES_SHORT_IT[today.month - 1]} {today.year}"
        )
        if draw.textlength(date_str, font=fonts.temp) > _max_date_w:
            date_str = (
                f"{_DAY_NAMES_FULL_IT[today.weekday()]}, "
                f"{today.day} {_MONTH_NAMES_SHORT_IT[today.month - 1]}"
            )
    y_mid = y0 + BANNER_MAIN_HEIGHT // 2
    ctx.text(
        (x0 + 12, y_mid),
        date_str,
        font=fonts.temp,
        fill=palette["INK"],
        anchor="lm",
    )

    right_x = x0 + w - 12

    if weather.temp_current is not None:
        # Horizontal layout (right-to-left):
        #   [icon 40px] | [temp 40px] | [↑max / ↓min stacked]
        has_maxmin = weather.temp_max is not None and weather.temp_min is not None

        # Step 1: measure max/min column width (rightmost block)
        maxmin_col_w = 0
        if has_maxmin:
            max_str = f"↑{weather.temp_max:.0f}°"
            min_str = f"↓{weather.temp_min:.0f}°"
            maxmin_col_w = max(
                int(draw.textlength(max_str, font=fonts.label)),
                int(draw.textlength(min_str, font=fonts.label)),
            )

        # Step 2: draw max/min stacked column, right-anchored at right_x
        if has_maxmin:
            _half_lh = (TEXT_XS + 5) // 2  # half visual line-height of font_label
            y_max = y_mid - _half_lh
            y_min = y_mid + _half_lh
            ctx.text(
                (right_x, y_max),
                max_str,
                font=fonts.label,
                fill=palette["INK_MUTED"],
                anchor="rm",
            )
            ctx.text(
                (right_x, y_min),
                min_str,
                font=fonts.label,
                fill=palette["INK_MUTED"],
                anchor="rm",
            )

        # Step 3: draw current temperature, right-anchored left of max/min column
        temp_gap = 8 if has_maxmin else 0
        temp_right_x = right_x - maxmin_col_w - temp_gap
        temp_str = f"{weather.temp_current:.0f}°"
        ctx.text(
            (temp_right_x, y_mid),
            temp_str,
            font=fonts.temp,
            fill=palette["INK"],
            anchor="rm",
        )
        temp_w = int(draw.textlength(temp_str, font=fonts.temp))

        # Step 4: draw condition icon (48px), left of temperature
        if weather.condition_icon is not None:
            icon_color = WEATHER_ICON_COLORS.get(weather.condition_icon, palette["INK"])
            icon_x = temp_right_x - temp_w - 10 - 48
            icon_y = y_mid - 24
            ctx.draw_icon(
                weather.condition_icon, 48, (icon_x, icon_y), icon_color,
                dither=weather.condition_icon == "sun",
            )

    _draw_hourly_row(
        ctx, (x0, y0 + BANNER_MAIN_HEIGHT, w, BANNER_HOURLY_HEIGHT), weather
    )
    ctx.line(
        [(x0, y0 + h - 1), (x0 + w, y0 + h - 1)],
        fill=palette["RULE_STRONG"],
        width=2,
    )


def _draw_hourly_row(ctx: "RenderContext", rect: Rect, weather: WeatherData) -> None:
    """Render the 6-cell bihourly forecast strip inside *rect*."""
    if not weather.hourly_forecast:
        return

    palette = ctx.palette
    fonts = ctx.fonts
    draw = ctx.draw
    x0, y0, w, _h = rect
    cell_w = w // 6

    _PAD_TOP = 4    # padding from cell top edge to time-label anchor
    _PAD_BOTTOM = 27  # padding from last temp pixel to border
    _BORDER_H = 2  # border line thickness at bottom of cell

    # Measure actual text heights using tight font bounding boxes.
    _time_h = (
        fonts.mono_xs.getbbox("00:00")[3]
        - fonts.mono_xs.getbbox("00:00")[1]
    )
    _temp_bbox = fonts.hourly_temp.getbbox("0°", anchor="lb")
    _temp_ascent = -_temp_bbox[1]   # pixels above baseline
    _temp_descent = _temp_bbox[3]   # pixels below baseline

    _time_bottom = y0 + _PAD_TOP + _time_h
    _temp_baseline = y0 + _h - _BORDER_H - _PAD_BOTTOM - _temp_descent
    _temp_top = _temp_baseline - _temp_ascent
    _icon_y = (_time_bottom + _temp_top) // 2 - 24  # vertically centred 48px icon

    for i, slot in enumerate(weather.hourly_forecast[:6]):
        cx = x0 + i * cell_w + cell_w // 2
        cell_x = x0 + i * cell_w

        # Vertical separator (skip leftmost edge)
        if i > 0:
            ctx.line(
                [(cell_x, y0), (cell_x, y0 + _h)],
                fill=palette["RULE"],
                width=1,
            )

        # Time label — centered, top of cell
        ctx.text(
            (cx, y0 + _PAD_TOP),
            f"{slot.hour:02d}:00",
            font=fonts.mono_xs,
            fill=palette["INK_MUTED"],
            anchor="mt",
        )

        # Condition icon (48px) — centred between time text and temperature text
        if slot.condition_icon is not None:
            icon_color = WEATHER_ICON_COLORS.get(slot.condition_icon, palette["INK"])
            ctx.draw_icon(
                slot.condition_icon, 48, (int(cx - 24), int(_icon_y)), icon_color,
                dither=slot.condition_icon == "sun",
            )

        # Temperature — number part centred on cx, degree symbol to the right
        if slot.temp is not None:
            num_str = f"{slot.temp:.0f}"
            num_w = int(draw.textlength(num_str, font=fonts.hourly_temp))
            ctx.text(
                (cx - num_w // 2, _temp_baseline),
                f"{num_str}°",
                font=fonts.hourly_temp,
                fill=palette["INK"],
                anchor="lb",
            )
