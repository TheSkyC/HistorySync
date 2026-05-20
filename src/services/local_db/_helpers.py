# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

"""Module-level helpers shared across every ``local_db`` sub-module.

These names are re-exported from :mod:`src.services.local_db` (the package
``__init__``) so that external callers — and the test suite, which monkey-
patches ``src.services.local_db._build_fts_query`` directly — see exactly
the same surface the original single-file module exposed.

Sub-modules MUST access the runtime-patchable helpers (``_build_fts_query``)
via the package namespace::

    import src.services.local_db as _pkg
    ...
    fts = _pkg._build_fts_query(keyword)

so that test monkey-patches at the package level take effect.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import re
import threading

from src.utils.url_utils import (
    extract_display_domain as _extract_display_domain_raw,
)

# ── Cached domain extraction ─────────────────────────────────────────────────
# History rows often have the same origin (scheme + host) with different paths.
# Caching on just the origin prefix (everything before the 3rd '/') gives high
# hit rates while avoiding per-URL dict bloat.
# Example: "https://github.com/user/repo" → key "https://github.com"
_domain_cache: OrderedDict[str, str] = OrderedDict()
_domain_cache_lock = threading.Lock()
_DOMAIN_CACHE_MAX = 8192


def _extract_display_domain(url: str) -> str:
    # Extract the scheme://host prefix as the cache key.
    # str.index raises ValueError for malformed URLs — fall back to full URL.
    try:
        sep = url.index("://")
        end = url.index("/", sep + 3)
        key = url[:end]
    except (ValueError, TypeError):
        key = url or ""
    cached = _domain_cache.get(key)
    if cached is not None:
        return cached
    result = _extract_display_domain_raw(url)
    with _domain_cache_lock:
        if len(_domain_cache) >= _DOMAIN_CACHE_MAX:
            _domain_cache.popitem(last=False)  # FIFO: evict oldest entry, not the entire cache
        _domain_cache[key] = result
    return result


# ── SQL injection defence helpers ─────────────────────────────────────────────

_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ALLOWED_COL_TYPES = frozenset({"INTEGER", "REAL", "TEXT", "BLOB", "NUMERIC"})


def _quote_identifier(name: str) -> str:
    """Return *name* as a safely double-quoted SQLite identifier.

    Raises ``ValueError`` if *name* contains characters that cannot appear
    in a valid SQLite identifier, providing an extra layer of defence against
    unexpected values sourced from ``sqlite_master`` or schema constants.
    """
    if not _SAFE_IDENTIFIER_RE.match(name):
        raise ValueError(f"Unsafe SQL identifier rejected: {name!r}")
    # Double-quote and escape any embedded double-quotes (standard SQL).
    return '"' + name.replace('"', '""') + '"'


def _sanitize_col_type(col_type: str) -> str:
    """Validate that *col_type* is one of the known SQLite affinity keywords."""
    upper = col_type.strip().upper()
    if upper not in _ALLOWED_COL_TYPES:
        raise ValueError(f"Unsafe column type rejected: {col_type!r}")
    return upper


def _sanitize_vacuum_path(path_str: str) -> str:
    """Escape a filesystem path for use inside a ``VACUUM INTO '...'`` literal.

    SQLite path strings are delimited by single quotes; a single quote inside
    the path must be doubled.  We also reject null bytes which SQLite would
    silently truncate.
    """
    if "\x00" in path_str:
        raise ValueError("Null byte in VACUUM INTO path")
    return path_str.replace("'", "''")


# ── DbStats dataclass ────────────────────────────────────────────────────────


@dataclass
class DbStats:
    """Snapshot of database size and content metrics."""

    file_size_bytes: int  # actual file size on disk
    page_count: int  # total SQLite pages allocated
    free_page_count: int  # unused (fragmented) pages
    page_size: int  # bytes per page
    record_count: int  # rows in history table
    domain_count: int  # distinct domains (after normalization)
    fts_size_bytes: int  # estimated size of FTS index

    @property
    def wasted_bytes(self) -> int:
        return self.free_page_count * self.page_size

    @property
    def wasted_pct(self) -> float:
        if self.page_count == 0:
            return 0.0
        return self.free_page_count / self.page_count * 100


# ── FTS query helpers ────────────────────────────────────────────────────────


def _is_fts_special(keyword: str) -> bool:
    """Return True if the keyword contains FTS5 special characters or operators.

    Not called by production code - used by tests/test_fts.py to verify FTS
    special-character detection logic independently.
    """
    return bool(re.search(r'[()"*]|(?<!\w)(AND|OR|NOT)(?!\w)', keyword))


def _escape_like(value: str) -> str:
    """Escape LIKE wildcard characters in *value* for use with ``ESCAPE '\\'``."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _keyword_eligible_for_fts(keyword: str) -> bool:
    """Return True when *keyword* can be handled by the FTS5 trigram index.

    The trigram tokenizer requires every individual token to be at least
    3 characters long.  A keyword fails this check when:
    - it is empty, or
    - any whitespace-separated word is shorter than 3 characters, or
    - the keyword stripped of spaces is shorter than 3 characters.
    """
    if not keyword:
        return False
    if any(len(w) < 3 for w in keyword.split() if w):
        return False
    return len(keyword.replace(" ", "")) >= 3


def _build_fts_query(keyword: str) -> str:
    """Build an FTS5 MATCH expression from a keyword.

    If the keyword already carries a column-filter prefix (``title:`` or
    ``url:``), we must NOT wrap the whole string in phrase-quotes because
    that would make FTS5 treat ``url:`` as literal text instead of a column
    filter, causing zero results.  Strip the prefix, quote only the bare
    term, then re-attach the column prefix.

    Multi-word keywords are split and joined with AND so that each word is
    matched independently (prefix search per word), giving higher recall than
    phrase matching which requires adjacent occurrence.

    Examples:
        ``github``            ->  ``"github"*``
        ``python tutorial``   ->  ``"python"* AND "tutorial"*``
        ``url:github``        ->  ``url:"github"*``
        ``title:python``      ->  ``title:"python"*``
    """
    if not keyword:
        return '""'

    for prefix in ("url:", "title:"):
        if keyword.startswith(prefix):
            bare = keyword[len(prefix) :]
            if not bare:
                return '""'
            tokens = bare.split()
            if len(tokens) == 1:
                return f'{prefix}"{tokens[0].replace(chr(34), chr(34) * 2)}"*'
            return " AND ".join(f'{prefix}"{t.replace(chr(34), chr(34) * 2)}"*' for t in tokens)

    # Split on whitespace; each token gets its own prefix-quoted term
    tokens = keyword.split()
    if len(tokens) == 1:
        escaped = tokens[0].replace('"', '""')
        return f'"{escaped}"*'
    parts = [f'"{t.replace(chr(34), chr(34) * 2)}"*' for t in tokens]
    return " AND ".join(parts)
