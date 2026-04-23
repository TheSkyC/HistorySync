from __future__ import annotations

import json
from pathlib import Path

from src.utils.logger import get_logger
from src.utils.path_helper import get_config_dir

log = get_logger("service.recent_search_store")

MAX_RECENT_SEARCHES = 20


class RecentSearchStore:
    """Persists recent search queries to a JSON file in the config directory."""

    def __init__(
        self,
        max_items: int = MAX_RECENT_SEARCHES,
        *,
        persist: bool = True,
        storage_path: Path | None = None,
        save_scheduler: callable | None = None,
    ):
        self._max = max_items
        self._persist = persist
        self._path = storage_path if storage_path is not None else get_config_dir() / "recent_searches.json"
        self._save_scheduler = save_scheduler or self._save
        self._items: list[str] = self._load() if self._persist else []

    def _load(self) -> list[str]:
        if not self._persist:
            return []
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text("utf-8"))
                if isinstance(data, list):
                    return [s for s in data if isinstance(s, str)][: self._max]
        except Exception:
            log.warning("Failed to load recent searches", exc_info=True)
        return []

    def _save(self) -> None:
        if not self._persist:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._items, ensure_ascii=False), "utf-8")
        except Exception:
            log.debug("Failed to save recent searches")

    def _save_deferred(self) -> None:
        if not self._persist:
            return
        self._save_scheduler()

    def add(self, query: str) -> None:
        query = query.strip()
        if not query:
            return
        if query in self._items:
            self._items.remove(query)
        self._items.insert(0, query)
        self._items = self._items[: self._max]
        self._save_deferred()

    def items(self) -> list[str]:
        return self._items.copy()

    def remove(self, query: str) -> None:
        if query in self._items:
            self._items.remove(query)
            self._save_deferred()

    def clear(self) -> None:
        self._items.clear()
        self._save_deferred()
