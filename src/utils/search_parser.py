# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import re


@dataclass
class SearchQuery:
    """Parsed structured search query."""

    keyword: str = ""
    domains: list[str] = field(default_factory=list)
    after: date | None = None
    before: date | None = None
    excludes: list[str] = field(default_factory=list)
    title_only: bool = False
    url_only: bool = False
    browser: str = ""
    use_regex: bool = False


def parse_query(text: str) -> SearchQuery:
    """
    Parse search string with structured tokens like domain:, after:, before:, etc.
    Example: 'domain:github.com after:2023-01-01 -react title:python search term'
    """
    query = SearchQuery()
    if not text:
        return query

    # Regular expressions for tokens
    # Note: tokens must be followed by space or end of string
    token_patterns = {
        "domain": r"\bdomain:([^\s]+)",
        "after": r"\bafter:(\d{4}-\d{2}-\d{2})",
        "before": r"\bbefore:(\d{4}-\d{2}-\d{2})",
        "title": r"\btitle:([^\s]+)",
        "url": r"\burl:([^\s]+)",
        "browser": r"\bbrowser:([^\s]+)",
        "exclude": r"(?<!\S)-([^\s]+)",
    }

    remaining_text = text

    # Extract single-value tokens
    for token, pattern in token_patterns.items():
        if token == "exclude":
            # Exclude can have multiple values
            matches = re.findall(pattern, remaining_text)
            if matches:
                query.excludes.extend(matches)
                remaining_text = re.sub(pattern, "", remaining_text)
            continue

        if token == "domain":
            matches = re.findall(pattern, remaining_text)
            if matches:
                query.domains.extend(matches)
                remaining_text = re.sub(pattern, "", remaining_text)
            continue

        match = re.search(pattern, remaining_text)
        if match:
            val = match.group(1)
            if token == "after":
                try:
                    query.after = date.fromisoformat(val)
                except ValueError:
                    pass
            elif token == "before":
                try:
                    query.before = date.fromisoformat(val)
                except ValueError:
                    pass
            elif token == "title":
                query.title_only = True
                # Replace 'title:value' with just 'value' so the keyword is preserved
                remaining_text = re.sub(pattern, r"\1", remaining_text)
                continue
            elif token == "url":
                query.url_only = True
                # Replace 'url:value' with just 'value' so the keyword is preserved
                remaining_text = re.sub(pattern, r"\1", remaining_text)
                continue
            elif token == "browser":
                query.browser = val.lower()

            # Remove token from text
            remaining_text = re.sub(pattern, "", remaining_text)

    query.keyword = " ".join(remaining_text.split()).strip()
    return query
