# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import date

import pytest

from src.utils.search_parser import parse_query


@pytest.mark.parametrize(
    "text, attr, expected, expected_kw",
    [
        # Domain tokens
        ("domain:github.com test", "domains", ["github.com"], "test"),
        ("domain:a.com domain:b.com", "domains", ["a.com", "b.com"], ""),
        # Date tokens
        ("after:2023-01-01", "after", date(2023, 1, 1), ""),
        ("before:2024-12-31", "before", date(2024, 12, 31), ""),
        ("after:not-a-date", "after", None, "after:not-a-date"),
        # Browser token
        ("browser:Chrome", "browser", "chrome", ""),
        ("browser:firefox", "browser", "firefox", ""),
        # Device token
        ("device:laptop", "device", "laptop", ""),
        # is: tokens
        ("is:bookmarked python", "bookmarked_only", True, "python"),
        ("is:starred", "bookmarked_only", True, ""),
        ("is:favorite", "bookmarked_only", True, ""),
        # has: tokens
        ("has:note", "has_annotation", True, ""),
        ("has:annotation", "has_annotation", True, ""),
        # tag: token
        ("tag:WORK", "bookmark_tag", "work", ""),
        ("tag:work", "bookmarked_only", True, ""),
    ],
)
def test_token_parsing(text, attr, expected, expected_kw):
    """Test individual token parsing."""
    q = parse_query(text)
    assert getattr(q, attr) == expected
    assert q.keyword == expected_kw


def test_empty_string_returns_defaults():
    """Empty string returns SearchQuery with all defaults."""
    q = parse_query("")
    assert q.keyword == ""
    assert q.domains == []
    assert q.after is None
    assert q.before is None
    assert q.excludes == []
    assert q.title_only is False
    assert q.url_only is False
    assert q.browser == ""
    assert q.use_regex is False
    assert q.bookmarked_only is False
    assert q.has_annotation is False
    assert q.bookmark_tag == ""
    assert q.device == ""


def test_plain_keyword():
    """Plain text becomes keyword."""
    q = parse_query("python")
    assert q.keyword == "python"


def test_multi_word_keyword():
    """Multiple words become keyword."""
    q = parse_query("open source")
    assert q.keyword == "open source"


def test_exclude_tokens():
    """Exclude tokens are captured, not in keyword."""
    q = parse_query("-ads -tracking python")
    assert q.excludes == ["ads", "tracking"]
    assert q.keyword == "python"


def test_title_token_sets_flag_and_promotes_keyword():
    """title: sets title_only=True and promotes value to keyword."""
    q = parse_query("title:django")
    assert q.title_only is True
    assert q.keyword == "django"


def test_url_token_sets_flag_and_promotes_keyword():
    """url: sets url_only=True and promotes value to keyword."""
    q = parse_query("url:github")
    assert q.url_only is True
    assert q.keyword == "github"


def test_all_tokens_combined():
    """All tokens in one string."""
    q = parse_query("domain:github.com after:2023-01-01 browser:chrome -ads python")
    assert q.domains == ["github.com"]
    assert q.after == date(2023, 1, 1)
    assert q.browser == "chrome"
    assert q.excludes == ["ads"]
    assert q.keyword == "python"


def test_tag_sets_bookmarked_only():
    """tag: token also sets bookmarked_only=True."""
    q = parse_query("tag:work")
    assert q.bookmark_tag == "work"
    assert q.bookmarked_only is True


def test_multiple_domains():
    """Multiple domain tokens are all captured."""
    q = parse_query("domain:a.com domain:b.com domain:c.com")
    assert q.domains == ["a.com", "b.com", "c.com"]


def test_invalid_date_ignored():
    """Invalid date is ignored, token remains in keyword."""
    q = parse_query("before:99-99-99")
    assert q.before is None
    assert "before:99-99-99" in q.keyword


def test_both_date_tokens():
    """Both after and before can be set."""
    q = parse_query("after:2023-01-01 before:2024-12-31")
    assert q.after == date(2023, 1, 1)
    assert q.before == date(2024, 12, 31)
