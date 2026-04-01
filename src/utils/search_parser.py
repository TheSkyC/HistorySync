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
    # Bookmark / annotation filters
    bookmarked_only: bool = False
    has_annotation: bool = False
    bookmark_tag: str = ""
    # Device filter (name substring or UUID prefix)
    device: str = ""


def parse_query(text: str) -> SearchQuery:
    """
    Parse search string with structured tokens.
    Supported tokens:
      domain:github.com      - filter by domain
      after:2023-01-01       - date range start
      before:2024-01-01      - date range end
      title:python           - search in title only
      url:github             - search in URL only
      browser:chrome         - filter by browser
      -react                 - exclude term
      is:bookmarked          - only bookmarked records
      has:note               - only records with annotations
      tag:work               - filter bookmarks by tag
    """
    query = SearchQuery()
    if not text:
        return query

    token_patterns = {
        "domain": r"\bdomain:([^\s]+)",
        "after": r"\bafter:(\d{4}-\d{2}-\d{2})",
        "before": r"\bbefore:(\d{4}-\d{2}-\d{2})",
        "title": r"\btitle:([^\s]+)",
        "url": r"\burl:([^\s]+)",
        "browser": r"\bbrowser:([^\s]+)",
        "device": r"\bdevice:([^\s]+)",
        "exclude": r"(?<!\S)-([^\s]+)",
        "is": r"\bis:(bookmarked|starred|favorite)",
        "has": r"\bhas:(note|annotation)",
        "tag": r"\btag:([^\s]+)",
    }

    remaining_text = text

    for token, pattern in token_patterns.items():
        if token == "exclude":
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

        if token == "is":
            if re.search(pattern, remaining_text):
                query.bookmarked_only = True
                remaining_text = re.sub(pattern, "", remaining_text)
            continue

        if token == "has":
            if re.search(pattern, remaining_text):
                query.has_annotation = True
                remaining_text = re.sub(pattern, "", remaining_text)
            continue

        if token == "tag":
            match = re.search(pattern, remaining_text)
            if match:
                query.bookmark_tag = match.group(1).lower()
                query.bookmarked_only = True
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
                remaining_text = re.sub(pattern, r"\1", remaining_text)
                continue
            elif token == "url":
                query.url_only = True
                remaining_text = re.sub(pattern, r"\1", remaining_text)
                continue
            elif token == "browser":
                query.browser = val.lower()
            elif token == "device":
                query.device = val
            remaining_text = re.sub(pattern, "", remaining_text)

    query.keyword = " ".join(remaining_text.split()).strip()
    return query
