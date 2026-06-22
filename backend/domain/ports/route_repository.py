"""Persistence port for the route store (clean-arch Phase 4a).

THIN — pure file I/O, mirroring BookmarkRepository over RouteStore. The manager
keeps the watcher state machine + mtime and calls these for disk ops:
  load()          -> full read (materialize + parse + post_load = default-category
                     injection + orphan reparent)
  load_or_empty() -> the merge-snapshot read (parse only, NO post_load)
  save(store)     -> read-merge-write: merge_stores(store, on-disk), write, return merged
  path()          -> the resolved file Path
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

from models.schemas import RouteStore


class RouteRepository(Protocol):
    def load(self) -> RouteStore: ...
    def load_or_empty(self) -> RouteStore: ...
    def save(self, store: RouteStore) -> RouteStore: ...
    def path(self) -> Path: ...
