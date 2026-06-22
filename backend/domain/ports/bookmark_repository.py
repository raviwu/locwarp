"""Persistence port for the bookmark store (clean-arch Phase 4a).

THIN — pure file I/O. The manager keeps the watcher state machine + the
threading.Lock + mtime, and calls these methods for disk ops:
  load()          -> full read (materialize + parse + post_load)
  load_or_empty() -> the merge-snapshot read (parse only, NO post_load) used by
                     _save / _watcher_tick / _reconcile_from_disk
  save(store)     -> read-merge-write: merge_stores(store, on-disk), write,
                     return merged (the iCloud-clobber guard). No lock here —
                     the manager holds _store_lock across the call.
  path()          -> the resolved file Path (cloud_sync_service reach-in).
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

from models.schemas import BookmarkStore


class BookmarkRepository(Protocol):
    def load(self) -> BookmarkStore: ...
    def load_or_empty(self) -> BookmarkStore: ...
    def save(self, store: BookmarkStore) -> BookmarkStore: ...
    def path(self) -> Path: ...
