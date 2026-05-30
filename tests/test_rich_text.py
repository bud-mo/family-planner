"""Unit tests for app.renderer.rich_text.parse_html_description.

Covers HTML tags, plain text, entities, nesting, list prefixes,
max-line truncation and edge cases.
"""
from __future__ import annotations

import pytest

from app.renderer.rich_text import RichSpan, parse_html_description


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _texts(lines) -> list[list[str]]:
    """Extract just the text strings from parsed lines (ignores style)."""
    return [[s.text for s in line] for line in lines]


def _joined(lines) -> list[str]:
    """Join spans per line into a single string."""
    return ["".join(s.text for s in line) for line in lines]


# ---------------------------------------------------------------------------
# 1. Plain text — no HTML tags
# ---------------------------------------------------------------------------


class TestPlainText:

    def test_single_line(self):
        lines = parse_html_description("Hello world")
        assert len(lines) == 1
        assert _joined(lines) == ["Hello world"]
        span = lines[0][0]
        assert not span.bold
        assert not span.italic
        assert not span.underline
        assert not span.is_link

    def test_multi_line_newlines(self):
        lines = parse_html_description("Line one\nLine two\nLine three")
        assert _joined(lines) == ["Line one", "Line two", "Line three"]

    def test_strips_blank_lines(self):
        lines = parse_html_description("A\n\nB\n\nC")
        assert _joined(lines) == ["A", "B", "C"]


# ---------------------------------------------------------------------------
# 2. Inline styles
# ---------------------------------------------------------------------------


class TestInlineStyles:

    def test_bold_b_tag(self):
        lines = parse_html_description("<b>bold text</b>")
        assert len(lines) == 1
        span = lines[0][0]
        assert span.text == "bold text"
        assert span.bold is True
        assert span.italic is False

    def test_bold_strong_tag(self):
        lines = parse_html_description("<strong>strong</strong>")
        assert lines[0][0].bold is True

    def test_italic_i_tag(self):
        lines = parse_html_description("<i>italic text</i>")
        span = lines[0][0]
        assert span.italic is True
        assert span.bold is False

    def test_italic_em_tag(self):
        lines = parse_html_description("<em>emphasis</em>")
        assert lines[0][0].italic is True

    def test_underline(self):
        lines = parse_html_description("<u>underlined</u>")
        span = lines[0][0]
        assert span.underline is True
        assert span.is_link is False

    def test_link(self):
        lines = parse_html_description('<a href="https://example.com">click here</a>')
        span = lines[0][0]
        assert span.text == "click here"
        assert span.is_link is True

    def test_link_no_href(self):
        lines = parse_html_description("<a>bare link</a>")
        assert lines[0][0].is_link is True


# ---------------------------------------------------------------------------
# 3. Block-level line breaks
# ---------------------------------------------------------------------------


class TestLineBreaks:

    def test_br_tag(self):
        lines = parse_html_description("first<br>second")
        assert _joined(lines) == ["first", "second"]

    def test_br_self_closing(self):
        lines = parse_html_description("one<br/>two")
        assert _joined(lines) == ["one", "two"]

    def test_p_tags(self):
        lines = parse_html_description("<p>para one</p><p>para two</p>")
        assert _joined(lines) == ["para one", "para two"]

    def test_div_tags(self):
        lines = parse_html_description("<div>div one</div><div>div two</div>")
        assert _joined(lines) == ["div one", "div two"]


# ---------------------------------------------------------------------------
# 4. Lists
# ---------------------------------------------------------------------------


class TestLists:

    def test_unordered_list(self):
        html = "<ul><li>alpha</li><li>beta</li><li>gamma</li></ul>"
        lines = parse_html_description(html)
        joined = _joined(lines)
        assert joined == ["• alpha", "• beta", "• gamma"]

    def test_ordered_list(self):
        html = "<ol><li>first</li><li>second</li><li>third</li></ol>"
        lines = parse_html_description(html)
        joined = _joined(lines)
        assert joined == ["1. first", "2. second", "3. third"]


# ---------------------------------------------------------------------------
# 5. Nested styles
# ---------------------------------------------------------------------------


class TestNestedStyles:

    def test_bold_italic_nesting(self):
        lines = parse_html_description("<b><i>both</i></b>")
        span = lines[0][0]
        assert span.text == "both"
        assert span.bold is True
        assert span.italic is True

    def test_bold_with_plain_text(self):
        lines = parse_html_description("normal <b>bold</b> normal")
        joined = _joined(lines)
        assert joined == ["normal bold normal"]
        spans = lines[0]
        bold_spans = [s for s in spans if s.bold]
        assert len(bold_spans) == 1
        assert bold_spans[0].text == "bold"

    def test_underline_inside_link(self):
        lines = parse_html_description('<a href="#"><u>styled link</u></a>')
        span = lines[0][0]
        assert span.is_link is True
        assert span.underline is True


# ---------------------------------------------------------------------------
# 6. HTML entities
# ---------------------------------------------------------------------------


class TestEntities:

    def test_amp(self):
        lines = parse_html_description("A &amp; B")
        assert _joined(lines) == ["A & B"]

    def test_lt_gt(self):
        lines = parse_html_description("&lt;tag&gt;")
        assert _joined(lines) == ["<tag>"]

    def test_nbsp(self):
        lines = parse_html_description("a&nbsp;b")
        joined = _joined(lines)[0]
        # &nbsp; is a non-breaking space — just check something is between a and b
        assert joined.startswith("a")
        assert joined.endswith("b")
        assert len(joined) == 3

    def test_numeric_entity(self):
        lines = parse_html_description("&#169;")  # copyright ©
        assert _joined(lines) == ["©"]


# ---------------------------------------------------------------------------
# 7. max_lines truncation
# ---------------------------------------------------------------------------


class TestMaxLines:

    def test_default_max_is_10(self):
        html = "".join(f"<p>line {i}</p>" for i in range(20))
        lines = parse_html_description(html)
        assert len(lines) == 10

    def test_custom_max_lines(self):
        html = "".join(f"<p>line {i}</p>" for i in range(15))
        lines = parse_html_description(html, max_lines=5)
        assert len(lines) == 5

    def test_fewer_lines_than_max(self):
        html = "<p>only two</p><p>lines</p>"
        lines = parse_html_description(html, max_lines=10)
        assert len(lines) == 2


# ---------------------------------------------------------------------------
# 8. Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:

    def test_empty_string(self):
        assert parse_html_description("") == []

    def test_whitespace_only(self):
        assert parse_html_description("   \n  ") == []

    def test_tags_only_no_text(self):
        assert parse_html_description("<b></b><br><p></p>") == []

    def test_unrecognised_tags_stripped(self):
        lines = parse_html_description("<span>visible</span>")
        assert _joined(lines) == ["visible"]

    def test_plain_text_single_line_no_trailing(self):
        lines = parse_html_description("no newline at end")
        assert len(lines) == 1

    def test_span_merging_same_style(self):
        """Consecutive same-style text in the same tag should merge spans."""
        lines = parse_html_description("<b>hello world</b>")
        # Should be a single span, not split into words
        assert len(lines[0]) == 1
        assert lines[0][0].text == "hello world"
