from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from pathlib import Path

from icalendar import Calendar
from dateutil.rrule import rrulestr

from app.calendar.base import CalendarEvent, CalendarProvider, _to_aware_datetime
from app.config import CalendarConfig

logger = logging.getLogger(__name__)


class IcsProvider(CalendarProvider):
    def __init__(self, config: CalendarConfig) -> None:
        self._config = config
        self._path: Path | None = Path(config.path) if config.path else None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def test_connection(self) -> bool:
        return self._path is not None and self._path.exists()

    def fetch_events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        if self._path is None:
            logger.warning("IcsProvider '%s': no path configured", self._config.name)
            return []

        try:
            raw = self._path.read_bytes()
        except FileNotFoundError:
            logger.error(
                "IcsProvider '%s': file not found: %s", self._config.name, self._path
            )
            return []
        except OSError as exc:
            logger.error(
                "IcsProvider '%s': cannot read %s: %s", self._config.name, self._path, exc
            )
            return []

        return self._parse_ical_bytes(raw, start, end)

    # ------------------------------------------------------------------
    # Shared parsing (reused by IcalProvider via inheritance)
    # ------------------------------------------------------------------

    def _parse_ical_bytes(
        self, raw: bytes, start: datetime, end: datetime
    ) -> list[CalendarEvent]:
        try:
            cal = Calendar.from_ical(raw)
        except ValueError as exc:
            logger.error(
                "IcsProvider '%s': malformed ICS data: %s", self._config.name, exc
            )
            return []

        # Normalise range bounds to aware datetimes for comparison
        if start.tzinfo is None:
            start = start.astimezone()
        if end.tzinfo is None:
            end = end.astimezone()

        events: list[CalendarEvent] = []
        for component in cal.walk("VEVENT"):
            try:
                events.extend(self._expand_component(component, start, end))
            except Exception as exc:
                logger.warning(
                    "IcsProvider '%s': skipping event '%s': %s",
                    self._config.name,
                    component.get("SUMMARY", "<no summary>"),
                    exc,
                )

        return events

    def _expand_component(
        self, component, start: datetime, end: datetime
    ) -> list[CalendarEvent]:
        """Return CalendarEvent instances for this VEVENT within [start, end]."""
        dtstart = component.get("DTSTART")
        if dtstart is None:
            return []

        raw_start = dtstart.dt
        all_day = isinstance(raw_start, date) and not isinstance(raw_start, datetime)
        ev_start = _to_aware_datetime(raw_start)

        dtend = component.get("DTEND") or component.get("DUE")
        if dtend is not None:
            ev_end = _to_aware_datetime(dtend.dt)
        else:
            duration_prop = component.get("DURATION")
            if duration_prop is not None:
                ev_end = ev_start + duration_prop.dt
            else:
                ev_end = ev_start + (timedelta(days=1) if all_day else timedelta(hours=1))

        uid = str(component.get("UID", ""))
        title = str(component.get("SUMMARY", ""))
        description_raw = component.get("DESCRIPTION")
        description = str(description_raw) if description_raw else None
        location_raw = component.get("LOCATION")
        location = str(location_raw) if location_raw else None
        attendees = self._parse_attendees(component)

        rrule_prop = component.get("RRULE")
        if rrule_prop is None:
            # Single occurrence — include only if it overlaps the range
            if ev_end > start and ev_start < end:
                return [
                    self._make_event(
                        uid, title, ev_start, ev_end, all_day,
                        location, description, attendees, recurrent=False,
                    )
                ]
            return []

        # Recurring event — expand occurrences with dateutil
        exdates = self._parse_exdates(component)
        duration = ev_end - ev_start
        rrule_text = f"RRULE:{rrule_prop.to_ical().decode()}"

        try:
            rule = rrulestr(rrule_text, dtstart=ev_start, ignoretz=False)
        except Exception as exc:
            logger.warning(
                "IcsProvider '%s': cannot expand RRULE for '%s': %s",
                self._config.name, title, exc,
            )
            # Fall back to single master occurrence if it overlaps the range
            if ev_end > start and ev_start < end:
                return [
                    self._make_event(
                        uid, title, ev_start, ev_end, all_day,
                        location, description, attendees, recurrent=True,
                    )
                ]
            return []

        result: list[CalendarEvent] = []
        # Search window starts slightly before `start` to catch occurrences whose
        # end falls inside the range but whose start is just before it.
        for occ_start in rule.between(start - duration, end, inc=True):
            occ_end = occ_start + duration
            if occ_end <= start or occ_start >= end:
                continue
            if occ_start in exdates:
                continue
            result.append(
                self._make_event(
                    uid, title, occ_start, occ_end, all_day,
                    location, description, attendees, recurrent=True,
                )
            )
        return result

    def _parse_attendees(self, component) -> list[str]:
        attendees: list[str] = []
        raw = component.get("ATTENDEE")
        if raw is None:
            return attendees
        if not isinstance(raw, list):
            raw = [raw]
        for att in raw:
            cn = att.params.get("CN", "")
            email = str(att).replace("mailto:", "")
            attendees.append(cn if cn else email)
        return attendees

    def _parse_exdates(self, component) -> set[datetime]:
        exdates: set[datetime] = set()
        raw = component.get("EXDATE")
        if raw is None:
            return exdates
        if not isinstance(raw, list):
            raw = [raw]
        for exd_list in raw:
            dts = getattr(exd_list, "dts", [exd_list])
            for dt_obj in dts:
                try:
                    exdates.add(_to_aware_datetime(dt_obj.dt))
                except Exception:
                    pass
        return exdates

    def _make_event(
        self,
        uid: str,
        title: str,
        start: datetime,
        end: datetime,
        all_day: bool,
        location: str | None,
        description: str | None,
        attendees: list[str],
        recurrent: bool,
    ) -> CalendarEvent:
        return CalendarEvent(
            uid=uid,
            title=title,
            start=start,
            end=end,
            all_day=all_day,
            location=location,
            description=description,
            attendees=attendees,
            recurrent=recurrent,
            color=self._config.color,
            calendar_name=self._config.name,
        )
