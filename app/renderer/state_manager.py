"""Thread-safe owner of NavigationState.

``StateManager`` is the single source of truth for ``NavigationState``.
It is instantiated once in ``main.py`` and shared — via ``app.state`` —
between the FastAPI routes and the display loop.

Usage::

    state_manager = StateManager()
    state = state_manager.get()
    state_manager.set(state.navigate_enter())
"""
from __future__ import annotations

import threading

from app.renderer.state import NavigationState


class StateManager:
    """Thread-safe container for the shared ``NavigationState``."""

    def __init__(self) -> None:
        self._state: NavigationState = NavigationState()
        self._lock: threading.Lock = threading.Lock()

    def get(self) -> NavigationState:
        """Return the current navigation state (thread-safe, non-blocking)."""
        with self._lock:
            return self._state

    def set(self, new_state: NavigationState) -> None:
        """Replace the current navigation state (thread-safe).

        Args:
            new_state: The new ``NavigationState`` instance to store.
        """
        with self._lock:
            self._state = new_state
