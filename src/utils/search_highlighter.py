# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from dataclasses import dataclass
import re

# Token colors
_COLOR_FIELD = "#3B82F6"  # blue   — key:value filters
_COLOR_EXCLUDE = "#EF4444"  # red    — -keyword
_COLOR_OPERATOR = "#A855F7"  # purple — AND / OR / NOT / ( )
_COLOR_MALFORMED = "#F59E0B"  # amber — key: with no value


@dataclass
class TokenSpan:
    start: int
    end: int
    color: str
    kind: str  # "field" | "exclusion" | "operator" | "malformed"


# Field tokens that accept a value
_FIELD_TOKENS = (
    "domain",
    "after",
    "before",
    "title",
    "url",
    "browser",
    "device",
    "is",
    "has",
    "tag",
)

# Compiled patterns — order matters: more specific first
_PATTERNS: list[tuple[str, str]] = [
    # Complete key:value  (value is non-empty, non-space)
    ("field", r"\b(?:" + "|".join(_FIELD_TOKENS) + r"):([^\s]+)"),
    # key: with no value (malformed — colon at end or followed by space/EOL)
    ("malformed", r"\b(?:" + "|".join(_FIELD_TOKENS) + r"):(?=\s|$)"),
    # Logical operators (standalone words)
    ("operator", r"(?<!\S)(?:AND|OR|NOT)(?!\S)"),
    # Grouping symbols
    ("operator", r"[()]"),
    # Exclusion: -word (not preceded by non-space)
    ("exclusion", r"(?<!\S)-([^\s]+)"),
]

_COMPILED = [(kind, re.compile(pat)) for kind, pat in _PATTERNS]


def get_highlight_spans(text: str) -> list[TokenSpan]:
    """Return colored token spans for *text*.

    Pure Python, no Qt dependency, safe to call on the UI thread.
    Spans may overlap only if the regex patterns overlap (they don't by design).
    """
    if not text:
        return []

    spans: list[TokenSpan] = []
    covered: set[int] = set()  # character positions already claimed

    for kind, pattern in _COMPILED:
        color = {
            "field": _COLOR_FIELD,
            "malformed": _COLOR_MALFORMED,
            "operator": _COLOR_OPERATOR,
            "exclusion": _COLOR_EXCLUDE,
        }[kind]

        for m in pattern.finditer(text):
            start, end = m.start(), m.end()
            # Skip if any character in this span is already highlighted
            if any(i in covered for i in range(start, end)):
                continue
            spans.append(TokenSpan(start=start, end=end, color=color, kind=kind))
            covered.update(range(start, end))

    spans.sort(key=lambda s: s.start)
    return spans
