# Copyright (c) 2026, TheSkyC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

from src.views.search_autocomplete import RecentSearchStore


def test_recent_store_fresh_mode_does_not_load_or_persist(tmp_path: Path):
    recent_path = tmp_path / "recent_searches.json"
    recent_path.write_text(json.dumps(["from-normal-mode"]), encoding="utf-8")

    store = RecentSearchStore(persist=False, storage_path=recent_path)
    assert store.items() == []

    store.add("fresh-only")
    assert store.items() == ["fresh-only"]

    # Existing persisted data must stay untouched in fresh mode.
    persisted = json.loads(recent_path.read_text(encoding="utf-8"))
    assert persisted == ["from-normal-mode"]


def test_recent_store_persists_in_normal_mode(tmp_path: Path):
    recent_path = tmp_path / "recent_searches.json"
    store = RecentSearchStore(persist=True, storage_path=recent_path)

    # Run save synchronously in test to avoid depending on event-loop timing.
    store._save_deferred = store._save  # type: ignore[method-assign]

    store.add("query one")
    store.add("query two")

    persisted = json.loads(recent_path.read_text(encoding="utf-8"))
    assert persisted == ["query two", "query one"]
