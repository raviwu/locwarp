"""Union merge for cloud-synced JSON stores at migration time.

Used by ``cloud_sync.migrate_pair`` when enabling/disabling cloud sync
and the destination already has a file from a prior session on another
device. Strategy:

1. ``merge_stores``: per-item LWW union by ID (newer ``updated_at`` wins;
   tie keeps local), plus tombstone suppression so a deletion on either
   side is honoured rather than resurrected.
2. **Collapse same-name categories**: when two distinct category IDs
   carry the same ``name``, keep the one with the earliest ``created_at``
   and remap items pointing at the dropped duplicate.

Step 2 exists because the first-time migration is bootstrapping a
previously-unfederated pair — same-name categories with different IDs
almost always mean "same logical thing created independently on each
device". After bootstrap, all further sync flows through file-watcher
reconcile (a different code path), so this name-dedup does not affect
ongoing multi-device editing.

Skips merge (leaving remote untouched) when either file is unreadable
or fails schema validation — better than wiping the remote with an empty
fallback.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path

from models.schemas import BookmarkStore, RouteStore
from services.json_safe import safe_load_json, safe_write_json
from services.store_merge import merge_stores

logger = logging.getLogger(__name__)


def _build_category_remap(categories: list) -> tuple[list, dict[str, str]]:
    """Collapse exact-name duplicate categories.

    Returns ``(deduped_categories, remap)`` where ``remap`` maps each dropped
    category ID to its keeper. Keeper is the category with the earliest
    ``created_at`` (lexicographic ISO sort); ties broken by ID for determinism.
    """
    by_name: dict[str, list] = defaultdict(list)
    for cat in categories:
        by_name[cat.name].append(cat)

    keepers: list = []
    remap: dict[str, str] = {}
    for group in by_name.values():
        if len(group) == 1:
            keepers.append(group[0])
            continue
        group.sort(key=lambda c: (getattr(c, "created_at", "") or "", c.id))
        keeper = group[0]
        keepers.append(keeper)
        for dup in group[1:]:
            remap[dup.id] = keeper.id
    return keepers, remap


def _merge_bookmark_payload(local: BookmarkStore, remote: BookmarkStore) -> BookmarkStore:
    # merge_stores does the per-item LWW union + tombstone suppression; the
    # same-name category collapse below is a separate bootstrap concern (two
    # devices independently created "Trips" with different ids).
    merged = merge_stores(local, remote)
    deduped_cats, remap = _build_category_remap(list(merged.categories))
    if remap:
        for bm in merged.bookmarks:
            if bm.category_id in remap:
                bm.category_id = remap[bm.category_id]
        logger.info(
            "sync_merge bookmarks: collapsed %d same-name duplicate categories",
            len(remap),
        )
    return BookmarkStore(
        categories=deduped_cats,
        bookmarks=merged.bookmarks,
        tombstones=merged.tombstones,
    )


def _merge_route_payload(local: RouteStore, remote: RouteStore) -> RouteStore:
    merged = merge_stores(local, remote)
    deduped_cats, remap = _build_category_remap(list(merged.categories))
    if remap:
        for r in merged.routes:
            if r.category_id in remap:
                r.category_id = remap[r.category_id]
        logger.info(
            "sync_merge routes: collapsed %d same-name duplicate categories",
            len(remap),
        )
    return RouteStore(
        categories=deduped_cats,
        routes=merged.routes,
        tombstones=merged.tombstones,
    )


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
