from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import datetime

from app.calendar.base import CalendarEvent, CalendarProvider
from app.calendar.caldav_provider import CalDavProvider
from app.calendar.ical_provider import IcalProvider
from app.calendar.ics_provider import IcsProvider
from app.config import CalendarConfig

logger = logging.getLogger(__name__)

# Maximum time to wait for a single calendar provider to respond.
# Must exceed the longest per-provider HTTP timeout (IcalProvider uses 15 s).
_FETCH_TIMEOUT_SECONDS: int = 45


def _make_provider(config: CalendarConfig) -> CalendarProvider:
    if config.type == "ics":
        return IcsProvider(config)
    if config.type == "caldav":
        return CalDavProvider(config)
    if config.type == "ical":
        return IcalProvider(config)
    raise ValueError(f"Unknown calendar type: {config.type!r}")


class CalendarAggregator:
    def __init__(
        self,
        calendar_configs: list[CalendarConfig],
        cache_ttl: int = 300,
    ) -> None:
        self._cache_ttl = cache_ttl
        self._cache: dict[tuple[datetime, datetime], tuple[float, list[CalendarEvent]]] = {}
        self._cache_lock = threading.Lock()
        self._providers: list[CalendarProvider] = []

        for config in calendar_configs:
            try:
                self._providers.append(_make_provider(config))
            except ValueError as exc:
                logger.error(
                    "CalendarAggregator: skipping calendar '%s': %s", config.name, exc
                )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def get_events(
        self, start: datetime, end: datetime, force: bool = False
    ) -> list[CalendarEvent]:
        """Ritorna gli eventi per l'intervallo dato.

        Con *force* True salta il controllo di freschezza in lettura (rifetch
        immediato), ma il risultato viene comunque scritto in cache così che le
        letture successive (web server) lo riusino.
        """
        cache_key = (start, end)
        now = time.monotonic()

        with self._cache_lock:
            # Eviction: rimuovi le entry scadute prima di leggere
            expired = [k for k, (ts, _) in self._cache.items() if now - ts >= self._cache_ttl]
            for k in expired:
                del self._cache[k]
            if not force:
                entry = self._cache.get(cache_key)
                if entry is not None and now - entry[0] < self._cache_ttl:
                    return entry[1]

        events = self._fetch_all(start, end)

        with self._cache_lock:
            self._cache[cache_key] = (time.monotonic(), events)

        return events

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_all(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        if not self._providers:
            return []

        all_events: list[CalendarEvent] = []

        with ThreadPoolExecutor(max_workers=len(self._providers)) as executor:
            futures: dict[Future[list[CalendarEvent]], CalendarProvider] = {
                executor.submit(provider.fetch_events, start, end): provider
                for provider in self._providers
            }
            for future, provider in futures.items():
                try:
                    all_events.extend(future.result(timeout=_FETCH_TIMEOUT_SECONDS))
                except FutureTimeoutError:
                    logger.error(
                        "CalendarAggregator: provider %r timed out after %ds — skipping",
                        type(provider).__name__,
                        _FETCH_TIMEOUT_SECONDS,
                    )
                except Exception as exc:
                    logger.error(
                        "CalendarAggregator: provider %r failed: %s",
                        type(provider).__name__,
                        exc,
                    )

        all_events.sort(key=lambda e: e.start)
        return all_events
