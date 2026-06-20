"""Unit tests for ``SlideshowController`` — no real time, no GPIO, no network.

The controller's interruptible sleep (``self._cancel.wait(timeout=...)``) is
replaced with a ``_FakeCancel`` whose ``wait`` returns immediately, so a "tick"
is instantaneous and the tests stay deterministic (no ``sleep``-based races).
Termination is gated on the worker thread joining, not on wall-clock timing.
"""
from __future__ import annotations

import threading

from app.display.slideshow import SlideshowController


class _FakeCancel:
    """Stand-in for the controller's ``_cancel`` event with a non-blocking wait."""

    def __init__(self) -> None:
        self._set = False

    def wait(self, timeout: float | None = None) -> bool:
        return self._set

    def set(self) -> None:
        self._set = True

    def clear(self) -> None:
        self._set = False

    def is_set(self) -> bool:
        return self._set


def _make(advance, *, artwork: bool, interval: int = 1) -> SlideshowController:
    artwork_mode = threading.Event()
    if artwork:
        artwork_mode.set()
    ctrl = SlideshowController(
        advance=advance,
        artwork_mode=artwork_mode,
        stop_event=threading.Event(),
        interval_minutes=lambda: interval,
    )
    ctrl._cancel = _FakeCancel()  # instantaneous, deterministic ticks
    ctrl._artwork_mode = artwork_mode  # keep a handle for the tests
    return ctrl


def test_advances_repeatedly_while_active() -> None:
    calls: list[int] = []

    def advance() -> None:
        calls.append(1)
        if len(calls) >= 5:
            ctrl._artwork_mode.clear()  # stop after 5 ticks

    ctrl = _make(advance, artwork=True)
    ctrl.toggle()
    ctrl._thread.join(timeout=2)

    assert not ctrl._thread.is_alive()
    assert len(calls) == 5
    assert ctrl.active is False


def test_toggle_outside_artwork_is_noop() -> None:
    calls: list[int] = []
    ctrl = _make(lambda: calls.append(1), artwork=False)

    ctrl.toggle()

    assert ctrl.active is False
    assert calls == []
    assert ctrl._thread is None


def test_toggle_off_stops_promptly() -> None:
    calls: list[int] = []
    started = threading.Event()
    gate = threading.Event()

    def advance() -> None:
        calls.append(1)
        started.set()
        gate.wait(timeout=2)  # hold the worker so we can toggle deterministically

    ctrl = _make(advance, artwork=True)
    ctrl.toggle()
    assert started.wait(1)  # worker reached the first advance

    ctrl.toggle()  # toggle OFF while the worker is mid-advance
    gate.set()  # let advance return; the loop must now exit
    ctrl._thread.join(timeout=2)

    assert not ctrl._thread.is_alive()
    assert ctrl.active is False
    assert len(calls) == 1  # no further advances after toggle-off


def test_clearing_artwork_mode_mid_run_exits() -> None:
    calls: list[int] = []
    started = threading.Event()
    gate = threading.Event()

    def advance() -> None:
        calls.append(1)
        started.set()
        gate.wait(timeout=2)

    ctrl = _make(advance, artwork=True)
    ctrl.toggle()
    assert started.wait(1)

    ctrl._artwork_mode.clear()  # leave artwork mode mid-advance
    gate.set()
    ctrl._thread.join(timeout=2)

    assert not ctrl._thread.is_alive()
    assert ctrl.active is False
    assert len(calls) == 1


def test_stop_is_idempotent_when_not_running() -> None:
    ctrl = _make(lambda: None, artwork=True)
    ctrl.stop()
    ctrl.stop()
    assert ctrl.active is False


def test_advance_exception_is_swallowed() -> None:
    calls: list[int] = []

    def advance() -> None:
        calls.append(1)
        if len(calls) >= 3:
            ctrl._artwork_mode.clear()
        raise RuntimeError("boom")

    ctrl = _make(advance, artwork=True)
    ctrl.toggle()
    ctrl._thread.join(timeout=2)

    assert not ctrl._thread.is_alive()  # exception never crashes the thread
    assert len(calls) == 3  # loop kept going, then stopped on mode clear
    assert ctrl.active is False
