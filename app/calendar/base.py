from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime, timezone


def _to_aware_datetime(dt: date | datetime) -> datetime:
    """Normalise a date or datetime to a timezone-aware datetime.

    All-day events (bare ``date``) are converted to midnight UTC.
    Floating datetimes (no tzinfo) are treated as local system time.
    """
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            return dt.astimezone()
        return dt
    # bare date → all-day event, midnight UTC
    return datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)


@dataclass
class CalendarEvent:
    uid: str
    title: str
    start: datetime
    end: datetime
    all_day: bool
    location: str | None
    description: str | None
    attendees: list[str]
    recurrent: bool
    color: str
    calendar_name: str


class CalendarProvider(ABC):
    @abstractmethod
    def fetch_events(self, start: datetime, end: datetime) -> list[CalendarEvent]: ...

    @abstractmethod
    def test_connection(self) -> bool: ...
