"""HTML-to-rich-text parser for CalDAV event descriptions.

Converts HTML-formatted descriptions into a list of ``RichLine`` values,
each containing one or more ``RichSpan`` segments with inline style
attributes.  Uses only Python stdlib — no external HTML parsing library.

Supported HTML:
  Block:   <p>, <div>, <br>, <li> (in <ul>/<ol>)
  Inline:  <b>/<strong>, <i>/<em>, <u>, <a href="...">
  Entities: &amp; &lt; &gt; &quot; &apos; &nbsp; and numeric references
  Plain text (no tags) is handled via newline splitting.

Everything else is stripped silently.
"""
from __future__ import annotations

import html as _html
from dataclasses import dataclass, field
from html.parser import HTMLParser


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class RichSpan:
    """A run of text with inline style attributes."""

    text: str
    bold: bool = False
    italic: bool = False
    underline: bool = False
    is_link: bool = False


# A logical line is a list of spans rendered on the same row.
RichLine = list[RichSpan]


# ---------------------------------------------------------------------------
# Internal parser
# ---------------------------------------------------------------------------


class _HtmlDescriptionParser(HTMLParser):
    """SAX-style parser that builds a list of RichLine values."""

    # Tags that force a line break when opened or closed
    _BLOCK_OPEN = frozenset({"p", "div", "ul", "ol", "br"})
    _BLOCK_CLOSE = frozenset({"p", "div", "li"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)

        # Output accumulator
        self._lines: list[RichLine] = []
        # Current line being built
        self._current_line: RichLine = []

        # Inline style stack — each element is a dict of active styles
        self._bold: int = 0          # depth counter for bold
        self._italic: int = 0        # depth counter for italic
        self._underline: int = 0     # depth counter for underline
        self._link: int = 0          # depth counter for links

        # List context
        self._in_ul: bool = False
        self._in_ol: bool = False
        self._ol_counter: int = 0

    # ------------------------------------------------------------------
    # HTMLParser callbacks
    # ------------------------------------------------------------------

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()

        if tag in ("b", "strong"):
            self._bold += 1
        elif tag in ("i", "em"):
            self._italic += 1
        elif tag == "u":
            self._underline += 1
        elif tag == "a":
            self._link += 1
        elif tag == "ul":
            self._in_ul = True
            self._in_ol = False
        elif tag == "ol":
            self._in_ol = True
            self._in_ul = False
            self._ol_counter = 0
        elif tag == "li":
            self._flush_line()
            if self._in_ol:
                self._ol_counter += 1
                self._append_text(f"{self._ol_counter}. ")
            else:
                self._append_text("• ")
        elif tag in self._BLOCK_OPEN:
            # <p>, <div>, <br>
            self._flush_line()

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()

        if tag in ("b", "strong"):
            self._bold = max(0, self._bold - 1)
        elif tag in ("i", "em"):
            self._italic = max(0, self._italic - 1)
        elif tag == "u":
            self._underline = max(0, self._underline - 1)
        elif tag == "a":
            self._link = max(0, self._link - 1)
        elif tag == "ul":
            self._in_ul = False
            self._flush_line()
        elif tag == "ol":
            self._in_ol = False
            self._ol_counter = 0
            self._flush_line()
        elif tag in self._BLOCK_CLOSE:
            self._flush_line()

    def handle_data(self, data: str) -> None:
        # convert_charrefs=True ensures entities are already decoded
        # Normalise newlines within data to line breaks
        parts = data.split("\n")
        for i, part in enumerate(parts):
            if i > 0:
                self._flush_line()
            if part:
                self._append_text(part)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _append_text(self, text: str) -> None:
        if not text:
            return
        span = RichSpan(
            text=text,
            bold=self._bold > 0,
            italic=self._italic > 0,
            underline=self._underline > 0,
            is_link=self._link > 0,
        )
        # Merge with previous span if same style
        if self._current_line and _same_style(self._current_line[-1], span):
            self._current_line[-1] = RichSpan(
                text=self._current_line[-1].text + text,
                bold=span.bold,
                italic=span.italic,
                underline=span.underline,
                is_link=span.is_link,
            )
        else:
            self._current_line.append(span)

    def _flush_line(self) -> None:
        """Commit the current line and start a new one."""
        self._lines.append(self._current_line)
        self._current_line = []

    def result(self) -> list[RichLine]:
        """Return parsed lines (flushes any pending line)."""
        if self._current_line:
            self._flush_line()
        return self._lines


def _same_style(a: RichSpan, b: RichSpan) -> bool:
    return (
        a.bold == b.bold
        and a.italic == b.italic
        and a.underline == b.underline
        and a.is_link == b.is_link
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_html_description(raw: str, max_lines: int = 10) -> list[RichLine]:
    """Parse *raw* (HTML or plain text) into at most *max_lines* rich lines.

    Args:
        raw:       Raw description string from a CalDAV event.  May contain
                   HTML tags, HTML entities, or be plain text.
        max_lines: Maximum number of lines to return.  Defaults to 10.

    Returns:
        A list of ``RichLine`` values.  Each ``RichLine`` is a (possibly
        empty) list of ``RichSpan`` segments.  Empty lines are removed.
        At most *max_lines* lines are returned.
    """
    if not raw or not raw.strip():
        return []

    # Detect whether the string contains any HTML tags at all.
    # If not, fall back to a fast plain-text split on newlines.
    if "<" not in raw:
        lines = _plain_text_lines(raw, max_lines)
        return lines

    parser = _HtmlDescriptionParser()
    try:
        parser.feed(raw)
    except Exception:
        # Malformed HTML — fall back to plain text
        return _plain_text_lines(raw, max_lines)

    all_lines = parser.result()

    # Filter out entirely empty lines (no spans or all-whitespace spans)
    non_empty = [
        line
        for line in all_lines
        if any(span.text.strip() for span in line)
    ]

    return non_empty[:max_lines]


def _plain_text_lines(raw: str, max_lines: int) -> list[RichLine]:
    """Convert plain text (newline-separated) into RichLines, decoding HTML entities."""
    result: list[RichLine] = []
    for line_text in raw.splitlines():
        stripped = _html.unescape(line_text.strip())
        if stripped:
            result.append([RichSpan(text=stripped)])
        if len(result) >= max_lines:
            break
    return result
