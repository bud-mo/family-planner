from __future__ import annotations

import logging
from datetime import datetime

import requests
import requests.exceptions
from icalendar import Calendar

from app.calendar.base import CalendarEvent, CalendarProvider
from app.calendar.ics_provider import IcsProvider
from app.config import CalendarConfig

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 15


def _normalise_url(url: str) -> str:
    """Replace the webcal:// scheme with https:// so requests can fetch it."""
    if url.startswith("webcal://"):
        return "https://" + url[len("webcal://"):]
    if url.startswith("webcals://"):
        return "https://" + url[len("webcals://"):]
    return url


class IcalProvider(IcsProvider):
    """Calendar provider that fetches an iCalendar feed from an HTTP/HTTPS URL.

    Designed for Google Calendar's secret iCal URLs and any publicly accessible
    .ics feed. No authentication is required — the URL itself acts as a token.
    Uses ``webcal://`` → ``https://`` normalisation transparently.
    """

    def __init__(self, config: CalendarConfig) -> None:
        # Call IcsProvider.__init__ but don't resolve a path — we use URL only.
        super().__init__(config)
        self._url: str | None = (
            _normalise_url(config.url) if config.url else None
        )

    # ------------------------------------------------------------------
    # Public interface (overrides IcsProvider)
    # ------------------------------------------------------------------

    def test_connection(self) -> bool:
        if self._url is None:
            logger.warning("IcalProvider '%s': no URL configured", self._config.name)
            return False
        try:
            response = requests.get(
                self._url,
                timeout=_TIMEOUT_SECONDS,
                headers={"Accept": "text/calendar, */*"},
                allow_redirects=True,
            )
            response.raise_for_status()
            # Light sanity-check: the body should look like an iCalendar feed.
            Calendar.from_ical(response.content)
            return True
        except requests.exceptions.RequestException as exc:
            logger.warning(
                "IcalProvider '%s': network error during connection test: %s",
                self._config.name, exc,
            )
        except ValueError as exc:
            logger.warning(
                "IcalProvider '%s': response is not valid iCal data: %s",
                self._config.name, exc,
            )
        return False

    def fetch_events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        if self._url is None:
            logger.warning("IcalProvider '%s': no URL configured", self._config.name)
            return []

        try:
            response = requests.get(
                self._url,
                timeout=_TIMEOUT_SECONDS,
                headers={"Accept": "text/calendar, */*"},
                allow_redirects=True,
            )
            response.raise_for_status()
        except requests.exceptions.ConnectionError as exc:
            logger.error(
                "IcalProvider '%s': network error fetching feed: %s",
                self._config.name, exc,
            )
            return []
        except requests.exceptions.Timeout:
            logger.error(
                "IcalProvider '%s': request timed out after %ss",
                self._config.name, _TIMEOUT_SECONDS,
            )
            return []
        except requests.exceptions.HTTPError as exc:
            logger.error(
                "IcalProvider '%s': HTTP error fetching feed: %s",
                self._config.name, exc,
            )
            return []

        return self._parse_ical_bytes(response.content, start, end)
