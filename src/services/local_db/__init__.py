# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

"""Public package surface for ``LocalDatabase``.

This package replaces the former single-file ``local_db.py`` (3.5 kLOC) with
one module per concern.  The :class:`LocalDatabase` class is composed via
multiple inheritance from a set of mixins; every public method that existed
on the original class is preserved by name and signature, so external imports
``from src.services.local_db import LocalDatabase`` keep working unchanged.

Module-level helpers (``_build_fts_query``, ``_quote_identifier``,
``DbStats`` …) are re-exported from :mod:`._helpers` so that:

* Tests can monkey-patch ``src.services.local_db._build_fts_query`` and the
  patched value is observed by the call sites inside the sub-modules — those
  call sites resolve helpers via ``import src.services.local_db as _pkg``
  followed by ``_pkg._build_fts_query(...)`` at call time.
* Direct imports such as ``from src.services.local_db import _quote_identifier``
  used by ``tests/test_local_db.py`` keep working.
"""

from __future__ import annotations

# ── Module-level helpers (must be defined / re-exported BEFORE sub-modules
#    are imported, because sub-modules look them up via ``_pkg.<name>`` at
#    runtime and in some cases at import time too).
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

# ── Mixins (each handles a single concern) ───────────────────────────────────
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
    """Facade composing the eleven concern-specific mixins.

    Method resolution order is left-to-right: ``_ConnectionMixin`` is searched
    first, then ``_SchemaMixin`` and so on.  Each method defined in the
    original ``local_db.py`` lives in exactly one mixin — there are no MRO
    collisions, so the order is mostly cosmetic, chosen to put the most
    foundational mixins (lifecycle, schema, FTS) before the consumers.
    """

    pass


# Module-level helpers (names beginning with ``_``) are kept public for tests
# and for external code that imports them directly — do not remove without
# auditing call sites.  Sorted to satisfy ``ruff`` RUF022.
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
