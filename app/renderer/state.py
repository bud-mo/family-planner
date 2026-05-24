"""Display state for the Family Planner renderer.

``NavigationState`` is an immutable dataclass that carries the reference date
used for rendering the calendar view.  No navigation is supported — the app
always shows the current day.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class NavigationState:
    anchor_date: date = field(default_factory=date.today)
