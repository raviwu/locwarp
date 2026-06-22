"""Generic JSON-file repository (infra layer, clean-arch Phase 4a).

Implements BookmarkRepository / RouteRepository Protocols from domain.ports.
Pure file I/O: load / load_or_empty / save / path.  NO watcher, NO lock.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from domain.store_merge import merge_stores
from services.json_safe import safe_load_json, safe_write_json

logger = logging.getLogger(__name__)


class JsonStore:
    """Generic JSON-file repository over a CRDT store (pure I/O).

    store_cls:     BookmarkStore | RouteStore
    path_provider: () -> Path  (stays in the manager module so the
                   BOOKMARKS_FILE/ROUTES_FILE monkeypatch seam is intact)
    post_load:     optional (store) -> store, applied in load() ONLY (NOT
                   load_or_empty) — RouteStore injects the default category +
                   reparents orphans on a full load, never on a merge snapshot.
    """

    def __init__(self, store_cls, path_provider, post_load=None):
        self._store_cls = store_cls
        self._path_provider = path_provider
        self._post_load = post_load

    def path(self) -> Path:
        return self._path_provider()

    def load(self):
        from services.cloud_sync import materialize_if_placeholder
        materialize_if_placeholder(self.path())
        data = safe_load_json(self.path())
        if data is None:
            logger.info("No store file (or unreadable); using defaults")
            store = self._store_cls()
        else:
            try:
                store = self._store_cls(**data)
            except Exception as exc:
                logger.warning("Store payload failed schema validation: %s", exc)
                store = self._store_cls()
        return self._post_load(store) if self._post_load else store

    def load_or_empty(self):
        """Merge-snapshot read: parse only, NO post_load."""
        raw = safe_load_json(self.path())
        if not isinstance(raw, dict):
            return self._store_cls()
        try:
            return self._store_cls(**raw)
        except Exception:
            return self._store_cls()

    def save(self, store):
        """Read-merge-write: merge store with on-disk copy, write, return merged."""
        path = self.path()
        merged = merge_stores(store, self.load_or_empty())
        safe_write_json(path, json.loads(merged.model_dump_json()))
        return merged
