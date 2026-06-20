"""Unit tests for ``resolve_button_roles`` — the pure rotation→role mapping."""
from __future__ import annotations

import pytest

from app.display.buttons import resolve_button_roles

_STANDARD = {"planner": "A", "artwork": "B", "slideshow": "C", "shutdown": "D"}
_INVERTED = {"planner": "D", "artwork": "C", "slideshow": "B", "shutdown": "A"}


@pytest.mark.parametrize("rotation", [0, 90])
def test_standard_orientation(rotation: int) -> None:
    assert resolve_button_roles(rotation) == _STANDARD


@pytest.mark.parametrize("rotation", [180, 270])
def test_inverted_orientation(rotation: int) -> None:
    assert resolve_button_roles(rotation) == _INVERTED


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_roles_map_to_distinct_buttons(rotation: int) -> None:
    roles = resolve_button_roles(rotation)
    assert len(set(roles.values())) == 4  # no two roles share a button
    assert set(roles.values()) == {"A", "B", "C", "D"}


def test_inversion_preserves_physical_position() -> None:
    # The 180° flip swaps A↔D and B↔C, so each role stays on the same physical
    # button: planner moves A→D, shutdown D→A, artwork B→C, slideshow C→B.
    std = resolve_button_roles(0)
    inv = resolve_button_roles(180)
    swap = {"A": "D", "D": "A", "B": "C", "C": "B"}
    for role, btn in std.items():
        assert inv[role] == swap[btn]
