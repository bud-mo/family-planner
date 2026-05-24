"""Navigation state for the Family Planner renderer.

``NavigationState`` is an immutable dataclass.  All ``navigate_*`` methods
return a *new* instance — the original state is never mutated.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from enum import Enum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.calendar.base import CalendarEvent


class View(Enum):
    ANNUAL = auto()
    MONTHLY = auto()
    WEEKLY = auto()
    DAILY = auto()
    DETAIL = auto()


@dataclass(frozen=True)
class NavigationState:
    view: View = View.WEEKLY
    selected_date: date = field(default_factory=date.today)
    selected_event_uid: str | None = None
    detail_scroll_offset: int = 0
    night_mode: bool = False

    # ------------------------------------------------------------------
    # Navigation helpers
    # ------------------------------------------------------------------

    def navigate_escape(self) -> NavigationState:
        """Return to the previous view in the hierarchy."""
        transitions = {
            View.DETAIL: View.DAILY,  # detail → back to where we came from
            View.DAILY: View.WEEKLY,
            View.WEEKLY: View.MONTHLY,
            View.MONTHLY: View.ANNUAL,
            View.ANNUAL: View.ANNUAL,   # already at top — no-op
        }
        new_view = transitions[self.view]
        if new_view == self.view:
            return self
        return replace(
            self,
            view=new_view,
            selected_event_uid=None,
            detail_scroll_offset=0,
        )

    def navigate_enter(
        self,
        events: list[CalendarEvent] | None = None,
    ) -> NavigationState:
        """Drill into the currently selected element."""
        if self.view == View.ANNUAL:
            return replace(self, view=View.MONTHLY, selected_event_uid=None)

        if self.view == View.MONTHLY:
            return replace(self, view=View.WEEKLY, selected_event_uid=None)

        if self.view == View.WEEKLY:
            # If an event is selected go to detail; otherwise go to daily.
            if self.selected_event_uid is not None:
                return replace(self, view=View.DETAIL, detail_scroll_offset=0)
            return replace(self, view=View.DAILY, selected_event_uid=None)

        if self.view == View.DAILY:
            if self.selected_event_uid is not None:
                return replace(self, view=View.DETAIL, detail_scroll_offset=0)
            return self

        # DETAIL — enter has no effect
        return self

    def navigate_up(
        self,
        events: list[CalendarEvent] | None = None,
    ) -> NavigationState:
        """Move selection backwards / scroll up."""
        if self.view == View.DETAIL:
            new_offset = max(0, self.detail_scroll_offset - 1)
            return replace(self, detail_scroll_offset=new_offset)

        if self.view == View.ANNUAL:
            prev = self.selected_date.replace(day=1) - timedelta(days=1)
            return replace(self, selected_date=prev.replace(day=1))

        if self.view == View.MONTHLY:
            prev = self.selected_date - timedelta(weeks=1)
            return replace(self, selected_date=prev)

        if self.view == View.WEEKLY:
            prev = self.selected_date - timedelta(days=1)
            return replace(self, selected_date=prev, selected_event_uid=None)

        if self.view == View.DAILY:
            if events:
                day_events = _events_for_date(events, self.selected_date)
                if day_events:
                    return self._select_adjacent_event(day_events, direction=-1)
            return self

        return self

    def navigate_down(
        self,
        events: list[CalendarEvent] | None = None,
    ) -> NavigationState:
        """Move selection forwards / scroll down."""
        if self.view == View.DETAIL:
            return replace(self, detail_scroll_offset=self.detail_scroll_offset + 1)

        if self.view == View.ANNUAL:
            first_of_month = self.selected_date.replace(day=1)
            # Jump to first day of next month
            if first_of_month.month == 12:
                nxt = first_of_month.replace(year=first_of_month.year + 1, month=1)
            else:
                nxt = first_of_month.replace(month=first_of_month.month + 1)
            return replace(self, selected_date=nxt)

        if self.view == View.MONTHLY:
            nxt = self.selected_date + timedelta(weeks=1)
            return replace(self, selected_date=nxt)

        if self.view == View.WEEKLY:
            nxt = self.selected_date + timedelta(days=1)
            return replace(self, selected_date=nxt, selected_event_uid=None)

        if self.view == View.DAILY:
            if events:
                day_events = _events_for_date(events, self.selected_date)
                if day_events:
                    return self._select_adjacent_event(day_events, direction=1)
            return self

        return self

    def toggle_night_mode(self) -> NavigationState:
        """Toggle night mode (HDMI only)."""
        return replace(self, night_mode=not self.night_mode)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _select_adjacent_event(
        self,
        events: list[CalendarEvent],
        direction: int,
    ) -> NavigationState:
        """Select the next or previous event relative to the current selection."""
        if not events:
            return self

        if self.selected_event_uid is None:
            # Select first (down) or last (up) event.
            uid = events[0].uid if direction > 0 else events[-1].uid
            return replace(self, selected_event_uid=uid)

        uids = [e.uid for e in events]
        try:
            idx = uids.index(self.selected_event_uid)
        except ValueError:
            return replace(self, selected_event_uid=events[0].uid)

        new_idx = idx + direction
        if 0 <= new_idx < len(uids):
            return replace(self, selected_event_uid=uids[new_idx])
        # Already at boundary — no change.
        return self


# ---------------------------------------------------------------------------
# Standalone helpers (module-level to avoid coupling with CalendarAggregator)
# ---------------------------------------------------------------------------


def _events_for_date(
    events: list[CalendarEvent],
    target: date,
) -> list[CalendarEvent]:
    """Filter events whose start date matches *target* (local date comparison)."""
    return [e for e in events if e.start.date() == target]
