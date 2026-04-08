# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

"""
Tests for FTS5 query construction and automatic LIKE-fallback.

Covers:
  - _build_fts_query output format
  - _is_fts_special detection
  - FTS5 prefix search
  - Automatic fallback when FTS5 raises OperationalError
  - Count consistency between fallback get_records and get_filtered_count
"""

from __future__ import annotations

import pytest

import src.services.local_db as local_db_module
from src.services.local_db import _build_fts_query, _is_fts_special
from tests.conftest import make_record

# ══════════════════════════════════════════════════════════════
# _build_fts_query
# ══════════════════════════════════════════════════════════════


class TestFTSQueryBuilder:
    def test_plain_keyword(self):
        assert _build_fts_query("hello") == '"hello"*'

    def test_multiword_uses_and_semantics(self):
        # Multi-word input is split into per-word prefix terms joined with AND.
        assert _build_fts_query("github actions") == '"github"* AND "actions"*'

    def test_embedded_double_quotes_escaped(self):
        assert _build_fts_query('say "hello"') == '"say"* AND """hello"""*'

    def test_fts_operators_neutralised_by_phrase_quoting(self):
        q = _build_fts_query("AND OR NOT")
        assert q == '"AND"* AND "OR"* AND "NOT"*'

    def test_special_chars_wrapped_in_quotes(self):
        q = _build_fts_query("(test*value)")
        assert '"' in q
        assert q.endswith("*")


# ══════════════════════════════════════════════════════════════
# _is_fts_special
# ══════════════════════════════════════════════════════════════


class TestIsFtsSpecial:
    @pytest.mark.parametrize(
        "keyword",
        ["test AND more", "(foo)", 'say "hello"'],
    )
    def test_detects_special(self, keyword: str):
        assert _is_fts_special(keyword)

    @pytest.mark.parametrize(
        "keyword",
        ["github", "hello world"],
    )
    def test_ignores_plain(self, keyword: str):
        assert not _is_fts_special(keyword)


# ══════════════════════════════════════════════════════════════
# FTS5 search behaviour
# ══════════════════════════════════════════════════════════════


@pytest.fixture()
def fts_db(local_db):
    """LocalDatabase pre-populated with three records for FTS tests."""
    local_db.upsert_records(
        [
            make_record(url="https://github.com", title="GitHub"),
            make_record(url="https://gitlab.com", title="GitLab", visit_time=1_704_067_201),
            make_record(url="https://bitbucket.org", title="Bitbucket", visit_time=1_704_067_202),
        ]
    )
    return local_db


class TestFTSSearch:
    def test_exact_keyword_found(self, fts_db):
        rows = fts_db.get_records(keyword="github")
        assert len(rows) == 1
        assert "github" in rows[0].url

    def test_prefix_match_returns_multiple(self, fts_db):
        rows = fts_db.get_records(keyword="git")
        assert len(rows) == 2

    def test_count_matches_records(self, fts_db):
        cnt = fts_db.get_filtered_count(keyword="git")
        rows = fts_db.get_records(keyword="git", limit=100)
        assert cnt == len(rows)


# ══════════════════════════════════════════════════════════════
# LIKE fallback
# ══════════════════════════════════════════════════════════════


class TestFTSFallback:
    def test_like_fallback_returns_correct_results(self, fts_db):
        """When FTS5 raises OperationalError the LIKE path must still work."""
        original = local_db_module._build_fts_query
        local_db_module._build_fts_query = lambda k: "INVALID FTS SYNTAX !!!"
        try:
            rows = fts_db.get_records(keyword="github")
            assert any("github" in r.url for r in rows)
        finally:
            local_db_module._build_fts_query = original

    def test_fallback_count_matches_record_count(self, fts_db):
        """Paging integrity: count and actual rows must agree in fallback mode."""
        original = local_db_module._build_fts_query
        local_db_module._build_fts_query = lambda k: "INVALID !!!"
        try:
            cnt = fts_db.get_filtered_count(keyword="git")
            rows = fts_db.get_records(keyword="git", limit=100)
            assert cnt == len(rows)
        finally:
            local_db_module._build_fts_query = original
