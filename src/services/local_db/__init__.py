# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from ._helpers import (
    _DOMAIN_CACHE_MAX,
    DbStats,
    _build_fts_query,
    _domain_cache,
    _domain_cache_lock,
    _escape_like,
    _extract_display_domain,
    _is_fts_special,
    _keyword_eligible_for_fts,
    _quote_identifier,
    _sanitize_col_type,
    _sanitize_vacuum_path,
)
from .bookmarks import _BookmarksMixin
from .connection import _ConnectionMixin
from .devices import _DevicesMixin
from .fts import _FtsMixin
from .hidden import _HiddenMixin
from .history import _HistoryMixin
from .maintenance import _MaintenanceMixin
from .merge import _MergeMixin
from .schema import _SchemaMixin
from .stats import _StatsMixin


class LocalDatabase(
    _ConnectionMixin,
    _SchemaMixin,
    _FtsMixin,
    _HistoryMixin,
    _HiddenMixin,
    _BookmarksMixin,
    _DevicesMixin,
    _StatsMixin,
    _MaintenanceMixin,
    _MergeMixin,
):
    pass


__all__ = [
    "_DOMAIN_CACHE_MAX",
    "DbStats",
    "LocalDatabase",
    "_build_fts_query",
    "_domain_cache",
    "_domain_cache_lock",
    "_escape_like",
    "_extract_display_domain",
    "_is_fts_special",
    "_keyword_eligible_for_fts",
    "_quote_identifier",
    "_sanitize_col_type",
    "_sanitize_vacuum_path",
]
