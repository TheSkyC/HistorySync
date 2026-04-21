# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

"""Tests for the search subcommand argument parsing in cli.py."""

from __future__ import annotations

import argparse


def _make_search_parser() -> argparse.ArgumentParser:
    """Minimal replica of the search subcommand parser for unit testing."""
    p = argparse.ArgumentParser()
    p.add_argument(
        "query",
        nargs="*",
        default=[],
        help="Search query",
    )
    p.add_argument("--limit", type=int, default=20)
    return p


class TestSearchQueryParsing:
    def test_no_args_yields_empty_query(self):
        """No positional args produce an empty query string."""
        p = _make_search_parser()
        ns = p.parse_args([])
        query_str = " ".join(ns.query or [])
        assert query_str == ""

    def test_single_word_query(self):
        """A single word is collected correctly."""
        p = _make_search_parser()
        ns = p.parse_args(["python"])
        query_str = " ".join(ns.query or [])
        assert query_str == "python"

    def test_multi_word_query_without_quotes(self):
        """Multiple words are joined into one query string (no quoting required)."""
        p = _make_search_parser()
        ns = p.parse_args(["python", "async"])
        query_str = " ".join(ns.query or [])
        assert query_str == "python async"

    def test_shell_expanded_words_are_joined(self):
        """Simulates shell glob expansion producing multiple tokens."""
        p = _make_search_parser()
        # Simulates: hsync search *.py -> expanded by shell to file1.py file2.py
        ns = p.parse_args(["file1.py", "file2.py"])
        query_str = " ".join(ns.query or [])
        assert query_str == "file1.py file2.py"

    def test_structured_token_without_quotes(self):
        """Structured tokens work as separate positional args."""
        p = _make_search_parser()
        ns = p.parse_args(["domain:github.com", "python"])
        query_str = " ".join(ns.query or [])
        assert query_str == "domain:github.com python"
