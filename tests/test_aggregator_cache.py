"""Unit tests for CalendarAggregator cache eviction (§4.7 / Fase 3.2).

Verifica che la cache non cresca illimitatamente: le entry scadute vengono
rimosse in get_events(), e dopo molte chiamate con chiavi diverse nel tempo
la dimensione rimane contenuta.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.calendar.aggregator import CalendarAggregator


def _dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def _make_aggregator(cache_ttl: int = 5) -> CalendarAggregator:
    """Return an aggregator with no providers and a short TTL."""
    agg = CalendarAggregator([], cache_ttl=cache_ttl)
    return agg


class TestCacheEviction:
    def test_expired_entries_are_removed(self) -> None:
        """Entry scadute vengono rimosse prima di inserire la nuova."""
        agg = _make_aggregator(cache_ttl=1)

        monotonic_values = iter([0.0, 0.0, 10.0, 10.0, 10.0])

        with patch("app.calendar.aggregator.time.monotonic", side_effect=monotonic_values):
            # Prima chiamata — popola la cache con key (d1, d2)
            agg.get_events(_dt(2026, 6, 1), _dt(2026, 6, 30))
            assert len(agg._cache) == 1

            # Seconda chiamata con chiave diversa e tempo avanzato (TTL scaduto)
            agg.get_events(_dt(2026, 7, 1), _dt(2026, 7, 31))
            # La prima entry (ts=0) deve essere evicta, rimane solo la seconda (ts=10)
            assert len(agg._cache) == 1

    def test_valid_entry_not_evicted(self) -> None:
        """Entry non ancora scaduta non viene rimossa."""
        agg = _make_aggregator(cache_ttl=100)

        monotonic_values = iter([0.0, 0.0, 1.0, 1.0, 1.0])

        with patch("app.calendar.aggregator.time.monotonic", side_effect=monotonic_values):
            agg.get_events(_dt(2026, 6, 1), _dt(2026, 6, 30))
            agg.get_events(_dt(2026, 7, 1), _dt(2026, 7, 31))
            # Entrambe le entry sono ancora valide (tempo avanzato di 1s < TTL 100s)
            assert len(agg._cache) == 2

    def test_cache_does_not_grow_unbounded(self) -> None:
        """Dopo N chiamate con chiavi diverse e TTL scaduto la cache rimane piccola."""
        agg = _make_aggregator(cache_ttl=1)

        n_calls = 20
        # Ogni chiamata a get_events usa monotonic 3 volte (eviction check + insert)
        # e _fetch_all non usa monotonic.
        # Sequenza: per ogni chiamata forniamo [now_for_eviction, now_for_cache_hit_check, now_for_insert]
        # Usare time.monotonic reale ma simulare il passaggio di 10s tra ogni chiamata
        base = 0.0
        times: list[float] = []
        for i in range(n_calls):
            t = base + i * 10.0  # ogni chiamata è 10s dopo la precedente (TTL=1s → tutto scaduto)
            # 3 letture per chiamata: eviction, hit-check, insert
            times.extend([t, t, t])

        with patch("app.calendar.aggregator.time.monotonic", side_effect=times):
            for i in range(n_calls):
                start = _dt(2026, 1, 1)
                # chiave diversa per ogni iterazione simulando giorni diversi
                end = _dt(2026, 1, i + 2)
                agg.get_events(start, end)

        # Con TTL=1s e 10s tra ogni chiamata, ogni nuova chiamata evicta la precedente
        # Al termine la cache non dovrebbe contenere più di 1 entry
        assert len(agg._cache) <= 2

    def test_cache_hit_returns_same_events(self) -> None:
        """La cache restituisce gli stessi eventi senza rifetch."""
        agg = _make_aggregator(cache_ttl=100)
        fetch_call_count = 0

        def fake_fetch(start: datetime, end: datetime) -> list:
            nonlocal fetch_call_count
            fetch_call_count += 1
            return []

        agg._fetch_all = fake_fetch  # type: ignore[method-assign]

        key_start, key_end = _dt(2026, 6, 1), _dt(2026, 6, 30)
        agg.get_events(key_start, key_end)
        agg.get_events(key_start, key_end)

        assert fetch_call_count == 1, "Il secondo get_events deve usare la cache"
