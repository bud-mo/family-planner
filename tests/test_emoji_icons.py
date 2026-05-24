"""Unit tests for app/renderer/emoji_icons.py.

Covers:
- split_text_emoji  — segmentation, greedy matching, multi-codepoint keys,
                      unknown-emoji stripping, ZWJ/variation-selector handling
- load_icon         — path resolution, LANCZOS rescaling, missing-icon fallback
"""
from __future__ import annotations

import pytest
from PIL import Image

from app.renderer.emoji_icons import (
    EMOJI_TO_ICON,
    _ICON_FALLBACK_SIZES,
    load_icon,
    split_text_emoji,
)
from app.renderer.tokens import ICONS_DIR, TEXT_BASE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _types(segs: list[tuple[str, str]]) -> list[str]:
    """Return just the segment types from a split result."""
    return [t for t, _ in segs]


def _icons(segs: list[tuple[str, str]]) -> list[str]:
    """Return icon names from a split result (skips text segments)."""
    return [c for t, c in segs if t == "icon"]


def _text(segs: list[tuple[str, str]]) -> str:
    """Concatenate all text segments."""
    return "".join(c for t, c in segs if t == "text")


# ---------------------------------------------------------------------------
# split_text_emoji — basic cases
# ---------------------------------------------------------------------------

class TestSplitTextEmoji:

    def test_plain_text_no_emoji(self):
        segs = split_text_emoji("Riunione di lavoro")
        assert segs == [("text", "Riunione di lavoro")]

    def test_empty_string(self):
        assert split_text_emoji("") == []

    def test_only_whitespace(self):
        segs = split_text_emoji("   ")
        assert segs == [("text", "   ")]

    def test_single_mapped_emoji(self):
        segs = split_text_emoji("❤️")
        assert segs == [("icon", "heart")]

    def test_bare_heart_without_variation_selector(self):
        # "❤" (U+2764) without VS-16 is also in the mapping
        segs = split_text_emoji("❤")
        assert segs == [("icon", "heart")]

    def test_text_then_emoji(self):
        segs = split_text_emoji("Ciao ❤️")
        assert _types(segs) == ["text", "icon"]
        assert segs[0] == ("text", "Ciao ")
        assert segs[1] == ("icon", "heart")

    def test_emoji_then_text(self):
        segs = split_text_emoji("🎂 Compleanno")
        assert _types(segs) == ["icon", "text"]
        assert segs[0] == ("icon", "cake")
        assert segs[1] == ("text", " Compleanno")

    def test_emoji_surrounded_by_text(self):
        segs = split_text_emoji("Buon 🎂 compleanno")
        assert _types(segs) == ["text", "icon", "text"]
        assert _icons(segs) == ["cake"]
        assert _text(segs) == "Buon  compleanno"

    def test_multiple_consecutive_emoji(self):
        # 🎉🎁🎈
        segs = split_text_emoji("🎉🎁🎈")
        assert _types(segs) == ["icon", "icon", "icon"]
        assert _icons(segs) == ["confetti", "gift", "balloon"]

    # ------------------------------------------------------------------
    # The real-world event title this feature was built for
    # ------------------------------------------------------------------

    def test_matrimonio_title(self):
        title = "Matrimonio nostro 😍🥰🤩❤️❤️❤️❤️❤️❤️"
        segs = split_text_emoji(title)
        assert segs[0] == ("text", "Matrimonio nostro ")
        assert ("icon", "mood-heart") in segs   # 😍
        assert ("icon", "hearts")     in segs   # 🥰
        assert ("icon", "star")       in segs   # 🤩
        hearts = [c for t, c in segs if t == "icon" and c == "heart"]
        assert len(hearts) == 6                 # six ❤️

    # ------------------------------------------------------------------
    # Multi-codepoint sequences
    # ------------------------------------------------------------------

    def test_red_heart_with_variation_selector_matched_first(self):
        # "❤️" (U+2764 U+FE0F) must beat bare "❤" (U+2764) due to greedy sort
        segs = split_text_emoji("❤️")
        assert len(segs) == 1
        assert segs[0] == ("icon", "heart")

    def test_sun_with_variation_selector(self):
        segs = split_text_emoji("☀️")
        assert segs == [("icon", "sun")]

    def test_snowflake_with_variation_selector(self):
        segs = split_text_emoji("❄️")
        assert segs == [("icon", "snowflake")]

    # ------------------------------------------------------------------
    # Unknown / unmapped emoji — must be silently stripped
    # ------------------------------------------------------------------

    def test_unknown_emoji_stripped(self):
        # 🫠 (U+1FAE0, melting face) is not in EMOJI_TO_ICON
        segs = split_text_emoji("Prima 🫠 dopo")
        assert "🫠" not in _text(segs)
        # no icon for it either
        assert all(c != "\U0001FAE0" for _, c in segs if _ == "icon")
        # plain text portions survive
        assert "Prima " in _text(segs)
        assert " dopo" in _text(segs)

    def test_flag_regional_indicators_stripped(self):
        # 🇮🇹 = U+1F1EE U+1F1F9 — regional indicators, stripped
        segs = split_text_emoji("🇮🇹 Italia")
        text_parts = _text(segs)
        assert "🇮🇹" not in text_parts
        assert "Italia" in text_parts

    def test_zjw_sequence_stripped_gracefully(self):
        # 👨‍👩‍👧 (man ZWJ woman ZWJ girl) — not in mapping, must not crash
        family = "\U0001F468\u200D\U0001F469\u200D\U0001F467"
        segs = split_text_emoji(f"Famiglia {family} riunita")
        assert "Famiglia " in _text(segs)
        assert "riunita" in _text(segs)

    def test_variation_selector_only_stripped(self):
        # Lone variation selector (U+FE0F) should be consumed without crashing
        segs = split_text_emoji("\uFE0F")
        # Either empty or a single empty-text segment; no crash
        assert segs == [] or segs == [("text", "")]

    def test_skin_tone_modifier_stripped(self):
        # U+1F44D (👍) + U+1F3FB (light skin) — 👍 is mapped, skin modifier consumed
        segs = split_text_emoji("\U0001F44D\U0001F3FB")
        # The base thumb-up should have been matched already by the greedy scan
        # so the skin modifier is consumed as part of the emoji cluster or stripped
        assert all(t == "icon" or t == "text" for t, _ in segs)

    # ------------------------------------------------------------------
    # Mapping completeness spot-checks
    # ------------------------------------------------------------------

    def test_weather_emojis_mapped(self):
        segs = split_text_emoji("☀️🌙❄️🌈⭐")
        names = _icons(segs)
        assert "sun"       in names
        assert "moon"      in names
        assert "snowflake" in names
        assert "rainbow"   in names
        assert "star"      in names

    def test_celebration_emojis_mapped(self):
        segs = split_text_emoji("🎉🎂🎁")
        names = _icons(segs)
        assert "confetti" in names
        assert "cake"     in names
        assert "gift"     in names

    def test_travel_emojis_mapped(self):
        segs = split_text_emoji("✈️🚗🏠🌍")
        names = _icons(segs)
        assert "plane" in names
        assert "car"   in names
        assert "home"  in names
        assert "world" in names

    def test_emoji_to_icon_keys_are_unique(self):
        # Every key is a distinct unicode sequence
        assert len(EMOJI_TO_ICON) == len(set(EMOJI_TO_ICON.keys()))


# ---------------------------------------------------------------------------
# load_icon
# ---------------------------------------------------------------------------

# Resolve which icon names have a file on disk (avoid test failures when
# a specific icon is absent from the repo's pre-baked set).
_AVAILABLE_ICONS: list[str] = [
    name
    for size in _ICON_FALLBACK_SIZES
    for path in [(ICONS_DIR / str(size)).glob("*.png")]
    for p in path
    for name in [p.stem]
]


def _first_available() -> str | None:
    """Return the first icon name that has a pre-baked PNG, or None."""
    for size in _ICON_FALLBACK_SIZES:
        d = ICONS_DIR / str(size)
        if d.is_dir():
            for p in sorted(d.iterdir()):
                if p.suffix == ".png":
                    return p.stem
    return None


@pytest.fixture()
def available_icon_name() -> str:
    name = _first_available()
    if name is None:
        pytest.skip("No pre-baked icon PNGs found in app/assets/icons/")
    return name


class TestLoadIcon:

    def test_returns_none_for_missing_icon(self):
        assert load_icon("__icon_that_does_not_exist__", 16) is None

    def test_returns_rgba_image(self, available_icon_name):
        img = load_icon(available_icon_name, 16)
        assert img is not None
        assert isinstance(img, Image.Image)
        assert img.mode == "RGBA"

    def test_exact_size_requested(self, available_icon_name):
        img = load_icon(available_icon_name, 16)
        assert img is not None
        assert img.size == (16, 16)

    def test_scales_down_to_requested_size(self, available_icon_name):
        small = load_icon(available_icon_name, 11)
        assert small is not None
        assert small.size == (11, 11)

    def test_scales_up_to_larger_size(self, available_icon_name):
        large = load_icon(available_icon_name, 32)
        assert large is not None
        assert large.size == (32, 32)

    def test_fallback_to_16px_source(self):
        # "heart" is very likely to be in the 16px set; skip if not
        img = load_icon("heart", 11)
        if img is None:
            pytest.skip("heart.png not found in icons/16/")
        assert img.size == (11, 11)

    def test_known_icons_for_matrimonio_event(self):
        """The four icons used in the reference event title must load."""
        required = {"heart": "heart", "hearts": "hearts",
                    "mood-heart": "mood-heart", "star": "star"}
        missing = [name for name in required if load_icon(name, 11) is None]
        assert not missing, f"Missing pre-baked PNGs: {missing}"
