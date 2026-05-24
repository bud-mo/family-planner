"""Navigation state for the Family Planner renderer.

``NavigationState`` is an immutable dataclass.  All ``navigate_*`` methods
return a *new* instance — the original state is never mutated.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, timedelta

PAGE_DAYS: int = 7  # giorni di avanzamento per navigate_next/navigate_prev


@dataclass(frozen=True)
class NavigationState:
    anchor_date: date = field(default_factory=date.today)
    page_offset: int = 0

    def navigate_next(self) -> NavigationState:
        """Avanza di PAGE_DAYS giorni nella lista appuntamenti."""
        return replace(
            self,
            anchor_date=self.anchor_date + timedelta(days=PAGE_DAYS),
            page_offset=self.page_offset + 1,
        )

    def navigate_prev(self) -> NavigationState:
        """Retrocede di PAGE_DAYS giorni; non va prima di oggi."""
        if self.page_offset <= 0:
            return self
        return replace(
            self,
            anchor_date=self.anchor_date - timedelta(days=PAGE_DAYS),
            page_offset=self.page_offset - 1,
        )

    def navigate_today(self) -> NavigationState:
        """Reimposta anchor_date a oggi e azzera page_offset."""
        return replace(self, anchor_date=date.today(), page_offset=0)
