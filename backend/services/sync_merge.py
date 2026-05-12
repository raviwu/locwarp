"""Generic ID-based union merge for cloud-synced JSON stores.

Used by both bookmark and route cloud sync. Strategy: union of local +
remote items; for the same ID, local wins. Remote-only items added by
other devices are preserved.

Skips merge (leaving remote untouched) when either file is unreadable
or fails schema validation — better than wiping the remote with an empty
fallback.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from models.schemas import BookmarkStore, RouteStore
from services.json_safe import safe_load_json, safe_write_json

logger = logging.getLogger(__name__)


def _merge_bookmark_payload(local: BookmarkStore, remote: BookmarkStore) -> BookmarkStore:
    cats = {c.id: c for c in remote.categories}
    cats.update({c.id: c for c in local.categories})
    bms = {b.id: b for b in remote.bookmarks}
    bms.update({b.id: b for b in local.bookmarks})
    return BookmarkStore(categories=list(cats.values()), bookmarks=list(bms.values()))


def _merge_route_payload(local: RouteStore, remote: RouteStore) -> RouteStore:
    cats = {c.id: c for c in remote.categories}
    cats.update({c.id: c for c in local.categories})
    routes = {r.id: r for r in remote.routes}
    routes.update({r.id: r for r in local.routes})
    return RouteStore(categories=list(cats.values()), routes=list(routes.values()))


def merge_bookmark_stores(local_path: Path, remote_path: Path) -> None:
    """Union-merge bookmarks at *local_path* into *remote_path* (local wins)."""
    try:
        local_data = safe_load_json(local_path)
        remote_data = safe_load_json(remote_path)
        if not isinstance(local_data, dict) or not isinstance(remote_data, dict):
            return
        local_store = BookmarkStore(**local_data)
        remote_store = BookmarkStore(**remote_data)
    except Exception as exc:
        logger.warning("sync_merge bookmarks: skipping, parse failed: %s", exc)
        return
    merged = _merge_bookmark_payload(local_store, remote_store)
    safe_write_json(remote_path, json.loads(merged.model_dump_json()))
    logger.info(
        "sync_merge bookmarks: %d local + %d remote → %d merged",
        len(local_store.bookmarks), len(remote_store.bookmarks), len(merged.bookmarks),
    )


def merge_route_stores(local_path: Path, remote_path: Path) -> None:
    """Union-merge routes at *local_path* into *remote_path* (local wins)."""
    try:
        local_data = safe_load_json(local_path)
        remote_data = safe_load_json(remote_path)
        if not isinstance(local_data, dict) or not isinstance(remote_data, dict):
            return
        local_store = RouteStore(**local_data)
        remote_store = RouteStore(**remote_data)
    except Exception as exc:
        logger.warning("sync_merge routes: skipping, parse failed: %s", exc)
        return
    merged = _merge_route_payload(local_store, remote_store)
    safe_write_json(remote_path, json.loads(merged.model_dump_json()))
    logger.info(
        "sync_merge routes: %d local + %d remote → %d merged",
        len(local_store.routes), len(remote_store.routes), len(merged.routes),
    )
