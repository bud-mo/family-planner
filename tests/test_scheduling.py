"""Unit tests for the refresh policy and the quiet-band night frame.

The point of the policy is to repaint the panel as rarely as the content
genuinely allows: each repaint costs 20-30 s of flashing.  These tests pin down
the three mechanisms that deliver that:

  * the display grid — bihourly, midnight-aligned, plus the tick that opens the
    quiet band and the one that rolls the date over (:class:`TestDisplayGrid`);
  * the quiet band — no repaints, and no network polling either
    (:class:`TestQuietBand`, :class:`TestNextWake`);
  * the content signature — it must contain exactly what is drawn, so invisible
    churn never costs a repaint and a visible edit is never missed
    (:class:`TestCalendarSignature`, :class:`TestWeatherSignature`).
"""
from __future__ import annotations

from datetime import datetime, time, timedelta

import pytest
from pydantic import ValidationError

from app.calendar.base import CalendarEvent
from app.config import AppConfig, QuietHoursConfig, RefreshConfig
from app.main import _calendar_signature, _weather_signature
from app.renderer.pillow_eink_renderer import PillowEinkRenderer
from app.renderer.state import NavigationState
from app.renderer.tokens import HourlySlot, WeatherData
from app.scheduling import RefreshPolicy
from app.server.routes.config import _parse_config_form
from app.weather.provider import WeatherProvider, strip_instant_fields

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DAY = datetime(2026, 6, 2)  # martedì — nessun rilievo, serve solo una data fissa


def _policy(**overrides) -> RefreshPolicy:
    """Default policy, optionally overridden field by field."""
    return RefreshPolicy.from_config(RefreshConfig(**overrides))


def _at(hour: int, minute: int = 0) -> datetime:
    return _DAY.replace(hour=hour, minute=minute)


def _event(**overrides) -> CalendarEvent:
    base = {
        "uid": "uid-1",
        "title": "Dentista",
        "start": datetime(2026, 6, 2, 9, 0),
        "end": datetime(2026, 6, 2, 10, 0),
        "all_day": False,
        "location": "Via Roma 1",
        "description": "Portare la ricetta",
        "attendees": ["mamma@example.com"],
        "recurrent": False,
        "color": "#4A90D9",
        "calendar_name": "Famiglia",
    }
    return CalendarEvent(**{**base, **overrides})


def _weather(**overrides) -> WeatherData:
    base = {
        "condition_icon": "sun",
        "description": "Sereno",
        "temp_current": 21.0,
        "temp_max": 27.0,
        "temp_min": 14.0,
        "hourly_forecast": [
            HourlySlot(hour=h, condition_icon="sun", temp=float(h)) for h in (0, 2, 4)
        ],
    }
    return WeatherData(**{**base, **overrides})


# ---------------------------------------------------------------------------
# Display grid
# ---------------------------------------------------------------------------


class TestDisplayGrid:
    def test_daily_tick_sequence(self) -> None:
        """The whole day's repaint schedule, walked tick by tick.

        This is the headline behaviour: eleven repaints a day instead of the
        roughly twenty-five the hourly current-temperature used to force.
        """
        policy = _policy()
        ticks: list[str] = []
        moment = _at(6, 0)
        end = moment + timedelta(days=1)
        while moment < end:
            ticks.append(f"{moment:%H:%M}")
            moment = policy.next_display_tick(moment)

        assert ticks == [
            "06:00", "08:00", "10:00", "12:00", "14:00",
            "16:00", "18:00", "20:00", "22:00",
            "23:00",  # apertura della fascia di quiete
            "00:00",  # rollover della data
        ]

    def test_grid_is_aligned_to_even_hours(self) -> None:
        policy = _policy()
        assert policy.is_display_tick(_at(14, 0))
        assert not policy.is_display_tick(_at(15, 0))
        assert not policy.is_display_tick(_at(14, 15))

    def test_grid_ignores_sub_minute_jitter(self) -> None:
        """A tick is an exact boundary: the loop evaluates the moment it woke *for*,
        not the wall clock, which always lags by some milliseconds."""
        policy = _policy()
        assert not policy.is_display_tick(_at(14, 0).replace(second=3))

    def test_suppressed_grid_ticks_are_skipped(self) -> None:
        """02:00 and 04:00 are on the grid but inside the band: skipped."""
        policy = _policy()
        assert not policy.is_display_tick(_at(2, 0))
        assert not policy.is_display_tick(_at(4, 0))
        assert policy.next_display_tick(_at(0, 0)) == _at(6, 0)

    def test_custom_interval(self) -> None:
        policy = _policy(display_interval_minutes=60, quiet_hours={"enabled": False})
        assert policy.is_display_tick(_at(15, 0))
        assert policy.next_display_tick(_at(15, 30)) == _at(16, 0)


# ---------------------------------------------------------------------------
# Quiet band
# ---------------------------------------------------------------------------


class TestQuietBand:
    def test_start_inclusive_end_exclusive(self) -> None:
        """23:00 is already night — it is the first frame that will sit unrefreshed;
        06:00 is already day, and shows the full banner again."""
        policy = _policy()
        assert policy.in_quiet_hours(_at(23, 0))
        assert policy.in_quiet_hours(_at(5, 59))
        assert not policy.in_quiet_hours(_at(6, 0))
        assert not policy.in_quiet_hours(_at(22, 59))

    def test_wraps_over_midnight(self) -> None:
        policy = _policy()
        for hour in (23, 0, 1, 3, 5):
            assert policy.in_quiet_hours(_at(hour, 30)), hour

    def test_band_without_midnight_wrap(self) -> None:
        policy = _policy(
            quiet_hours={"start": "01:00", "end": "05:00", "allowed_ticks": ["02:00"]}
        )
        assert policy.in_quiet_hours(_at(3, 0))
        assert not policy.in_quiet_hours(_at(23, 0))

    def test_push_suppressed_inside_band(self) -> None:
        policy = _policy()
        assert policy.push_allowed(_at(22, 30))
        assert not policy.push_allowed(_at(2, 30))

    def test_disabled_band_never_quiet(self) -> None:
        policy = _policy(quiet_hours={"enabled": False})
        assert not policy.in_quiet_hours(_at(3, 0))
        assert policy.push_allowed(_at(3, 0))
        assert policy.is_display_tick(_at(2, 0))

    def test_seal_tick_fires_before_the_band_opens(self) -> None:
        """The seal is the last repaint *before* the night, so it keeps its own
        time even when the band starts later: moving the band start to 00:30 must
        not silently delete the 23:00 repaint."""
        policy = _policy(
            quiet_hours={
                "start": "00:30",
                "end": "06:00",
                "allowed_ticks": ["23:00", "00:00"],
            }
        )

        assert not policy.in_quiet_hours(_at(23, 0))  # fuori fascia...
        assert policy.is_display_tick(_at(23, 0))     # ...ma il sigillo vale lo stesso
        assert policy.is_display_tick(_at(0, 0))
        assert policy.next_display_tick(_at(22, 0)) == _at(23, 0)

    def test_extra_ticks_are_inert_when_the_band_is_off(self) -> None:
        """With no night to seal, only the display grid applies — the ticks are
        dropped when the policy is built, so they cannot add stray repaints."""
        policy = _policy(
            quiet_hours={"enabled": False, "allowed_ticks": ["23:00", "00:00"]}
        )

        assert policy.allowed_ticks == ()
        assert not policy.is_display_tick(_at(23, 0))

    def test_removing_the_sealing_tick_keeps_the_22_frame(self) -> None:
        """Dropping "23:00" costs one repaint less: the 22:00 frame — the one that
        still shows the temperature — stays up until midnight."""
        policy = _policy(quiet_hours={"allowed_ticks": ["00:00"]})
        assert not policy.is_display_tick(_at(23, 0))
        assert policy.next_display_tick(_at(22, 0)) == _at(0, 0) + timedelta(days=1)


# ---------------------------------------------------------------------------
# Wake scheduling
# ---------------------------------------------------------------------------


class TestNextWake:
    def test_polls_between_ticks_during_the_day(self) -> None:
        policy = _policy()
        assert policy.next_wake(_at(14, 3)) == _at(14, 15)
        assert policy.next_wake(_at(14, 50)) == _at(15, 0)

    def test_no_polling_inside_the_band(self) -> None:
        """From midnight the loop sleeps straight through to 06:00: a calendar
        push is suppressed anyway, so the fetch would be pure waste."""
        policy = _policy()
        assert policy.next_wake(_at(0, 0)) == _at(6, 0)
        assert policy.next_wake(_at(2, 14)) == _at(6, 0)

    def test_wakes_for_the_sealing_tick(self) -> None:
        policy = _policy()
        assert policy.next_wake(_at(22, 50)) == _at(23, 0)
        assert policy.next_wake(_at(23, 10)) == _at(0, 0) + timedelta(days=1)

    def test_tick_and_poll_coincide(self) -> None:
        policy = _policy()
        assert policy.next_wake(_at(21, 50)) == _at(22, 0)


# ---------------------------------------------------------------------------
# Configuration validation
# ---------------------------------------------------------------------------


class TestRefreshConfig:
    def test_defaults(self) -> None:
        cfg = RefreshConfig()
        assert cfg.display_interval_minutes == 120
        assert cfg.calendar_poll_minutes == 15
        assert cfg.min_push_interval_minutes == 20
        assert cfg.quiet_hours.allowed_tick_times == (time(23, 0), time(0, 0))

    def test_display_interval_must_divide_the_day(self) -> None:
        """A non-divisor would let the grid drift across midnight."""
        with pytest.raises(ValidationError):
            RefreshConfig(display_interval_minutes=50)

    def test_poll_interval_must_divide_the_hour(self) -> None:
        with pytest.raises(ValidationError):
            RefreshConfig(calendar_poll_minutes=25)

    def test_allowed_tick_outside_the_band_is_accepted(self) -> None:
        """Extra ticks are not bound to the band: they fire at their own time.

        Binding them would make the seal tick vanish the moment the band start is
        moved past it, which is precisely the repaint the user cares about — the
        last one before the night."""
        cfg = QuietHoursConfig(start="23:00", end="06:00", allowed_ticks=["21:00"])

        assert cfg.allowed_ticks == ["21:00"]

    def test_band_bounds_must_differ(self) -> None:
        with pytest.raises(ValidationError):
            QuietHoursConfig(start="23:00", end="23:00")

    def test_malformed_time_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            QuietHoursConfig(start="11 pm")

    def test_empty_allowed_ticks_is_valid(self) -> None:
        """A fully silent night is a legitimate choice — the date then catches up
        at the reopening tick."""
        policy = _policy(quiet_hours={"allowed_ticks": []})
        assert policy.next_display_tick(_at(22, 0)) == _at(6, 0) + timedelta(days=1)


class _Form(dict):
    """Minimal stand-in for a Starlette form multidict."""

    def getlist(self, key: str) -> list:
        value = self.get(key)
        if isinstance(value, list):
            return value
        return [] if value is None else [value]


class TestConfigFormRoundTrip:
    def test_cadences_survive_a_web_save(self) -> None:
        """The /config form has no controls for the three cadence knobs, so they
        must be carried over from the existing config — otherwise saving anything
        from the browser would silently reset them to their defaults.

        The quiet-hours section IS exposed in the form (unlike the cadences), so
        an empty submission means an unchecked "enabled" checkbox — that part of
        `refresh` is legitimately allowed to change; see the quiet-hours tests
        below for its own contract.
        """
        existing = AppConfig(
            refresh=RefreshConfig(
                display_interval_minutes=180,
                calendar_poll_minutes=30,
                min_push_interval_minutes=45,
            )
        )

        parsed = _parse_config_form(_Form(), existing)
        rebuilt = AppConfig.model_validate(parsed)

        assert rebuilt.refresh.display_interval_minutes == 180
        assert rebuilt.refresh.calendar_poll_minutes == 30
        assert rebuilt.refresh.min_push_interval_minutes == 45


class TestQuietHoursFormMapping:
    """Contract for the "Fascia notturna" section added to /config."""

    def test_enabled_with_midnight_update(self) -> None:
        existing = AppConfig()
        form = _Form(
            quiet_enabled="on",
            quiet_start="21:30",
            quiet_end="06:30",
            quiet_midnight_update="on",
        )

        parsed = _parse_config_form(form, existing)
        rebuilt = AppConfig.model_validate(parsed)

        assert rebuilt.refresh.quiet_hours.enabled is True
        assert rebuilt.refresh.quiet_hours.start == "21:30"
        assert rebuilt.refresh.quiet_hours.end == "06:30"
        assert "00:00" in rebuilt.refresh.quiet_hours.allowed_ticks

    def test_enabled_without_midnight_update_keeps_existing_seal_tick(self) -> None:
        """Unchecking the midnight box must drop only "00:00" — the seal tick
        that opens the band (here "23:00") is a pre-existing entry and, since it
        is still inside the new band, is left untouched."""
        existing = AppConfig(
            refresh=RefreshConfig(
                quiet_hours=QuietHoursConfig(
                    start="23:00", end="06:00", allowed_ticks=["23:00", "00:00"]
                )
            )
        )
        form = _Form(
            quiet_enabled="on",
            quiet_start="23:00",
            quiet_end="06:00",
        )

        parsed = _parse_config_form(form, existing)
        rebuilt = AppConfig.model_validate(parsed)

        assert "00:00" not in rebuilt.refresh.quiet_hours.allowed_ticks
        assert "23:00" in rebuilt.refresh.quiet_hours.allowed_ticks

    def test_moving_the_band_keeps_the_seal_tick(self) -> None:
        """Moving the band must not delete the seal: it is the last repaint before
        the night and keeps its own time, even once it falls outside the new
        bounds.  The rebuilt config must still validate."""
        existing = AppConfig(
            refresh=RefreshConfig(
                quiet_hours=QuietHoursConfig(
                    start="23:00", end="06:00", allowed_ticks=["23:00", "00:00"]
                )
            )
        )
        form = _Form(
            quiet_enabled="on",
            quiet_start="01:00",
            quiet_end="05:00",
            quiet_midnight_update="on",
        )

        parsed = _parse_config_form(form, existing)
        rebuilt = AppConfig.model_validate(parsed)  # must not raise

        assert rebuilt.refresh.quiet_hours.start == "01:00"
        assert rebuilt.refresh.quiet_hours.end == "05:00"
        assert rebuilt.refresh.quiet_hours.allowed_ticks == ["23:00", "00:00"]

    def test_midnight_box_ignores_the_band(self) -> None:
        """The "cambio data" box governs "00:00" on its own terms: ticking it must
        work even when midnight sits outside the band."""
        existing = AppConfig()
        form = _Form(
            quiet_enabled="on",
            quiet_start="00:30",
            quiet_end="06:00",
            quiet_midnight_update="on",
        )

        rebuilt = AppConfig.model_validate(_parse_config_form(form, existing))

        assert "00:00" in rebuilt.refresh.quiet_hours.allowed_ticks
        assert RefreshPolicy.from_config(rebuilt.refresh).is_display_tick(_at(0, 0))

    def test_disabled_band_still_records_the_checkbox_state(self) -> None:
        """With the band off the ticks are inert (the policy drops them), but the
        form still persists what the boxes say, so re-enabling is predictable."""
        existing = AppConfig(
            refresh=RefreshConfig(
                quiet_hours=QuietHoursConfig(
                    start="23:00", end="06:00", allowed_ticks=["23:00", "00:00"]
                )
            )
        )
        form = _Form(quiet_start="01:00", quiet_end="05:00")  # entrambe le caselle assenti

        rebuilt = AppConfig.model_validate(_parse_config_form(form, existing))

        assert rebuilt.refresh.quiet_hours.enabled is False
        assert rebuilt.refresh.quiet_hours.allowed_ticks == ["23:00"]
        assert RefreshPolicy.from_config(rebuilt.refresh).allowed_ticks == ()


# ---------------------------------------------------------------------------
# Night frame
# ---------------------------------------------------------------------------


class TestNightFrameClassification:
    """Which moments render without the instantaneous weather fields."""

    def test_band_and_its_ticks_are_night(self) -> None:
        policy = _policy()

        assert policy.is_night_frame(_at(23, 0))   # sigillo
        assert policy.is_night_frame(_at(0, 0))    # mezzanotte
        assert policy.is_night_frame(_at(2, 30))   # dentro la fascia

    def test_the_22_frame_keeps_its_temperature(self) -> None:
        """The last grid tick before the night is a normal frame: it is replaced
        an hour later, so its reading is not going to rot on the panel."""
        assert not _policy().is_night_frame(_at(22, 0))
        assert not _policy().is_night_frame(_at(6, 0))

    def test_ticks_outside_the_band_are_still_night_frames(self) -> None:
        """The regression this rule exists for: with a band starting at 00:30 the
        midnight frame sits outside the bounds yet stays on the panel until 06:00,
        so it must not advertise a temperature read at midnight."""
        policy = _policy(quiet_hours={"start": "00:30", "end": "06:00"})

        assert not policy.in_quiet_hours(_at(0, 0))   # fuori dai confini...
        assert policy.is_night_frame(_at(0, 0))       # ...ma è comunque notturno
        assert policy.is_night_frame(_at(23, 0))
        assert not policy.is_night_frame(_at(22, 0))

    def test_seconds_do_not_defeat_the_match(self) -> None:
        """Unlike a display tick, this is evaluated against the wall clock, which
        always lags the boundary by a little."""
        assert _policy().is_night_frame(_at(23, 0).replace(second=7))

    def test_nothing_is_night_when_the_band_is_off(self) -> None:
        policy = _policy(quiet_hours={"enabled": False})

        assert not policy.is_night_frame(_at(23, 0))
        assert not policy.is_night_frame(_at(3, 0))


class TestNightFrame:
    def test_instant_fields_are_dropped(self) -> None:
        result = strip_instant_fields(_weather())

        assert result.condition_icon is None
        assert result.description is None
        assert result.temp_current is None
        assert result.temp_max is None
        assert result.temp_min is None

    def test_forecast_survives(self) -> None:
        """The bihourly strip is predictive, so it stays valid overnight: the
        midnight frame still carries useful cells at breakfast."""
        result = strip_instant_fields(_weather())

        assert [s.hour for s in result.hourly_forecast] == [0, 2, 4]
        assert result.hourly_forecast[0].condition_icon == "sun"

    def test_idempotent(self) -> None:
        """The renderer and the e-ink loop both apply it, without coordinating."""
        once = strip_instant_fields(_weather())

        assert strip_instant_fields(once) is once

    def test_empty_weather_is_returned_unchanged(self) -> None:
        empty = WeatherData()

        assert strip_instant_fields(empty) is empty

    def test_banner_matches_a_forecast_only_frame(self) -> None:
        """A night frame must be indistinguishable from one that never had
        instantaneous data: date plus strip, nothing else."""
        weather = _weather()

        projected = strip_instant_fields(weather)
        expected = WeatherData(hourly_forecast=weather.hourly_forecast)

        assert projected == expected


class _FixedWeatherProvider(WeatherProvider):
    """Provider that always returns the same reading, ignoring *force*."""

    def __init__(self, data: WeatherData) -> None:
        self._data = data

    def get(self, force: bool = False) -> WeatherData:
        return self._data


class TestRendererNightProjection:
    """The projection lives in the renderer so the browser preview and the panel
    can never disagree — a preview showing the full banner at 02:00 would be
    misleading exactly when it is used to debug the panel."""

    def _renderer(self) -> PillowEinkRenderer:
        return PillowEinkRenderer(
            AppConfig(), weather_provider=_FixedWeatherProvider(_weather())
        )

    def test_projects_inside_the_band(self) -> None:
        shown = self._renderer().weather_for_display(now=_at(2, 0))

        assert shown.temp_current is None
        assert shown.condition_icon is None
        assert shown.hourly_forecast  # la strip resta

    def test_passes_through_during_the_day(self) -> None:
        shown = self._renderer().weather_for_display(now=_at(14, 0))

        assert shown.temp_current == 21.0
        assert shown.condition_icon == "sun"

    def test_sealing_tick_is_already_night(self) -> None:
        assert self._renderer().weather_for_display(now=_at(23, 0)).temp_current is None

    def test_reopening_tick_is_already_day(self) -> None:
        assert self._renderer().weather_for_display(now=_at(6, 0)).temp_current == 21.0

    def test_projects_on_a_tick_that_sits_outside_the_band(self) -> None:
        """The renderer follows the same night rule as the loop, so the browser
        preview and the panel agree even in this corner."""
        renderer = PillowEinkRenderer(
            AppConfig(refresh=RefreshConfig(quiet_hours=QuietHoursConfig(
                start="00:30", end="06:00"
            ))),
            weather_provider=_FixedWeatherProvider(_weather()),
        )

        assert renderer.weather_for_display(now=_at(0, 0)).temp_current is None
        assert renderer.weather_for_display(now=_at(22, 0)).temp_current == 21.0

    def test_renders_without_a_provider(self) -> None:
        renderer = PillowEinkRenderer(AppConfig())

        assert renderer.weather_for_display(now=_at(2, 0)) == WeatherData()


# ---------------------------------------------------------------------------
# Content signature — calendar half
# ---------------------------------------------------------------------------


class TestCalendarSignature:
    def _sig(self, *events: CalendarEvent) -> tuple:
        return _calendar_signature(NavigationState(), list(events))

    def test_invisible_fields_do_not_move_the_signature(self) -> None:
        """Editing the guest list used to repaint the panel to identical pixels."""
        base = self._sig(_event())

        assert self._sig(_event(attendees=["papa@example.com", "zia@example.com"])) == base
        assert self._sig(_event(recurrent=True)) == base
        assert self._sig(_event(calendar_name="Lavoro")) == base

    def test_uid_is_not_part_of_the_signature(self) -> None:
        """Feeds regenerated per request can hand the same appointment back under
        a fresh uid; what looks identical must sign identically."""
        assert self._sig(_event(uid="rigenerato-42")) == self._sig(_event())

    def test_rendered_fields_do_move_the_signature(self) -> None:
        base = self._sig(_event())

        assert self._sig(_event(title="Dentista — spostato")) != base
        assert self._sig(_event(location="Via Milano 9")) != base
        assert self._sig(_event(description="Portare anche il libretto")) != base
        assert self._sig(_event(color="#D94A4A")) != base
        assert self._sig(_event(all_day=True)) != base

    def test_description_change_is_detected(self) -> None:
        """The agenda renders descriptions, but the old signature omitted them:
        an edited note stayed invisible until something else changed."""
        assert self._sig(_event(description="nuovo testo")) != self._sig(_event())

    def test_sub_minute_jitter_is_ignored(self) -> None:
        """Only HH:MM reaches the screen."""
        jittered = _event(start=datetime(2026, 6, 2, 9, 0, 37))

        assert self._sig(jittered) == self._sig(_event())

    def test_minute_change_is_detected(self) -> None:
        assert self._sig(_event(start=datetime(2026, 6, 2, 9, 30))) != self._sig(_event())

    def test_reordering_does_not_move_the_signature(self) -> None:
        """``sort(key=start)`` is not a total order, so same-start events can swap
        places between fetches with no visible difference."""
        a, b = _event(uid="a", title="Alfa"), _event(uid="b", title="Beta")

        assert self._sig(a, b) == self._sig(b, a)

    def test_added_and_removed_events_are_detected(self) -> None:
        one = self._sig(_event())

        assert self._sig(_event(), _event(uid="b", title="Beta")) != one
        assert self._sig() != one

    def test_identical_looking_duplicates_collapse_but_count_is_kept(self) -> None:
        """Two events that render identically sign identically as a pair, and
        losing one of them still shows up."""
        twin = _event(uid="other")

        assert self._sig(_event(), twin) != self._sig(_event())


# ---------------------------------------------------------------------------
# Content signature — weather half
# ---------------------------------------------------------------------------


class TestWeatherSignature:
    def test_description_does_not_move_the_signature(self) -> None:
        """WMO 61/63/65 all draw as ``cloud-rain`` while the text differs, and no
        component draws the text: it was a pure source of invisible repaints."""
        assert _weather_signature(_weather(description="Pioggia intensa")) == \
            _weather_signature(_weather())

    def test_sub_degree_jitter_is_ignored(self) -> None:
        assert _weather_signature(_weather(temp_current=21.4)) == \
            _weather_signature(_weather())

    def test_rounded_degree_change_is_detected(self) -> None:
        assert _weather_signature(_weather(temp_current=22.6)) != \
            _weather_signature(_weather())

    def test_window_shift_is_detected(self) -> None:
        """The bihourly strip advancing is the one weather change that is *meant*
        to drive the display cadence."""
        shifted = _weather(
            hourly_forecast=[
                HourlySlot(hour=h, condition_icon="sun", temp=float(h))
                for h in (2, 4, 6)
            ]
        )

        assert _weather_signature(shifted) != _weather_signature(_weather())

    def test_night_projection_is_stable_against_instant_drift(self) -> None:
        """Whatever the temperature does overnight, the night frame does not move
        — which is exactly why it is safe not to repaint until morning."""
        night = strip_instant_fields(_weather())
        night_later = strip_instant_fields(_weather(temp_current=17.0, condition_icon="cloud"))

        assert _weather_signature(night) == _weather_signature(night_later)
