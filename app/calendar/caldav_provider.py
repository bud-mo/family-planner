from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

import caldav
import requests.exceptions
from caldav.lib import error as caldav_error
from icalendar import Calendar as iCal

from app.calendar.base import CalendarEvent, CalendarProvider, _to_aware_datetime
from app.config import CalendarConfig

logger = logging.getLogger(__name__)

_REDACTED = "***"
_TIMEOUT_SECONDS = 15


class CalDavProvider(CalendarProvider):
    def __init__(self, config: CalendarConfig) -> None:
        self._config = config

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def test_connection(self) -> bool:
        try:
            self._make_client().principal()
            return True
        except caldav_error.DAVError as exc:
            logger.warning(
                "CalDavProvider '%s': DAV error during connection test: %s",
                self._config.name, exc,
            )
        except requests.exceptions.ConnectionError as exc:
            logger.warning(
                "CalDavProvider '%s': network error during connection test: %s",
                self._config.name, exc,
            )
        except Exception as exc:
            logger.warning(
                "CalDavProvider '%s': unexpected error during connection test: %s",
                self._config.name, exc,
            )
        return False

    def fetch_events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        try:
            principal = self._make_client().principal()
            calendars = principal.calendars()
        except caldav_error.DAVError as exc:
            # Credentials are intentionally not logged.
            logger.error(
                "CalDavProvider '%s': DAV error fetching calendar list "
                "(credentials: [%s]): %s",
                self._config.name, _REDACTED, type(exc).__name__,
            )
            return []
        except requests.exceptions.ConnectionError as exc:
            logger.error(
                "CalDavProvider '%s': network error fetching calendar list: %s",
                self._config.name, exc,
            )
            return []
        except Exception as exc:
            logger.error(
                "CalDavProvider '%s': unexpected error fetching calendar list: %s",
                self._config.name, exc,
            )
            return []

        events: list[CalendarEvent] = []
        for calendar in calendars:
            cal_name = getattr(calendar, "name", None) or str(calendar.url)
            try:
                for obj in self._search_calendar(calendar, start, end):
                    parsed = self._parse_caldav_event(obj)
                    if parsed is not None:
                        events.append(parsed)
            except caldav_error.DAVError as exc:
                logger.warning(
                    "CalDavProvider '%s': DAV error reading calendar '%s': %s",
                    self._config.name, cal_name, exc,
                )
            except Exception as exc:
                logger.warning(
                    "CalDavProvider '%s': unexpected error reading calendar '%s': %s",
                    self._config.name, cal_name, exc,
                )

        return events

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _make_client(self) -> caldav.DAVClient:
        return caldav.DAVClient(
            url=self._config.url,
            username=self._config.username,
            password=self._config.password,
            timeout=_TIMEOUT_SECONDS,
        )

    def _search_calendar(
        self, calendar: caldav.Calendar, start: datetime, end: datetime
    ) -> list[caldav.Event]:
        try:
            return calendar.search(start=start, end=end, event=True, expand=True)
        except TypeError:
            # Older caldav version — expand parameter not supported
            return calendar.search(start=start, end=end, event=True)

    def _parse_caldav_event(self, caldav_event: caldav.Event) -> CalendarEvent | None:
        try:
            cal = iCal.from_ical(caldav_event.data)
            for component in cal.walk("VEVENT"):
                return self._component_to_event(component)
            return None
        except Exception as exc:
            logger.warning(
                "CalDavProvider '%s': parse error: %s", self._config.name, exc
            )
            return None

    def _component_to_event(self, component) -> CalendarEvent | None:
        dtstart = component.get("DTSTART")
        if dtstart is None:
            return None

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

        attendees: list[str] = []
        raw_att = component.get("ATTENDEE")
        if raw_att is not None:
            if not isinstance(raw_att, list):
                raw_att = [raw_att]
            for att in raw_att:
                cn = att.params.get("CN", "")
                email = str(att).replace("mailto:", "")
                attendees.append(cn if cn else email)

        # An event is recurrent if it has an RRULE or is an exception override
        is_recurrent = (
            component.get("RRULE") is not None
            or component.get("RECURRENCE-ID") is not None
        )

        return CalendarEvent(
            uid=uid,
            title=title,
            start=ev_start,
            end=ev_end,
            all_day=all_day,
            location=location,
            description=description,
            attendees=attendees,
            recurrent=is_recurrent,
            color=self._config.color,
            calendar_name=self._config.name,
        )
