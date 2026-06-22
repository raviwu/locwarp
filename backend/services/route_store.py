"""Saved-route + category management with JSON file persistence.

Mirrors :mod:`services.bookmarks` so saved routes get the same ergonomics
as bookmarks (categories, search-friendly listing, recolor, rename).

Backward compatibility: legacy ``routes.json`` files have shape
``{"routes": [...]}`` without categories and without ``category_id``
on each route. Both gaps are handled by pydantic defaults: the bare
list still parses, and a single ``"default"`` category is injected on
load so the front-end always has at least one bucket to render.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEventHandler
from watchdog.observers.api import ObservedWatch

from config import ROUTES_FILE, get_routes_path
from domain.ports.route_repository import RouteRepository
from models.schemas import RouteCategory, RouteStore, SavedRoute, Tombstone
from services.file_watcher import schedule as _watcher_schedule, unschedule as _watcher_unschedule
from services.json_safe import safe_load_json, safe_write_json
from services.store_merge import merge_stores

logger = logging.getLogger(__name__)

# Capture the import-time default so tests that monkeypatch
# config.ROUTES_FILE keep working.
_CONFIG_DEFAULT_ROUTES_FILE = ROUTES_FILE


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tombstone(obj_id: str, kind: str) -> Tombstone:
    """Build a deletion record so the delete propagates across cloud-synced
    devices instead of being resurrected by a concurrent writer."""
    return Tombstone(id=obj_id, kind=kind, deleted_at=_now_iso())


def _load_store_or_empty(path: Path) -> RouteStore:
    """Read a RouteStore from disk, tolerating a missing or corrupt file.

    Returns an empty store on any failure so merge_stores can treat it as
    "the other side had nothing" — never raises, never loses our in-memory
    copy in response to a transient read error."""
    raw = safe_load_json(path)
    if not isinstance(raw, dict):
        return RouteStore(categories=[], routes=[], tombstones=[])
    try:
        return RouteStore(**raw)
    except Exception:
        return RouteStore(categories=[], routes=[], tombstones=[])


def _default_category() -> RouteCategory:
    return RouteCategory(
        id="default",
        name="預設",
        color="#6c8cff",
        sort_order=0,
        created_at=_now_iso(),
    )


def _routes_path_default() -> Path:
    """Resolve the routes file path, honouring test monkeypatches.

    Kept as a module-level function so the ROUTES_FILE monkeypatch seam
    (used by test fixtures) is preserved when this is passed as the
    path_provider to JsonStore via bootstrap.factories.
    """
    if ROUTES_FILE is not _CONFIG_DEFAULT_ROUTES_FILE:
        return Path(ROUTES_FILE)
    return get_routes_path()


def _inject_default_category(store: RouteStore) -> RouteStore:
    """Post-load hook: ensure a default category exists and reparent orphans.

    Applied only in load() (full read), NOT in load_or_empty() (merge snapshot).
    This asymmetry is load-bearing: the merge snapshot must return the raw
    parsed store so merging against an empty file does not add phantom categories.
    """
    if not any(c.id == "default" for c in store.categories):
        store.categories.insert(0, _default_category())
    valid_ids = {c.id for c in store.categories}
    for r in store.routes:
        if r.category_id not in valid_ids:
            r.category_id = "default"
    return store


class RouteManager:
    """CRUD manager for saved routes and route categories.

    State is persisted via the injected RouteRepository on every write.
    The watcher state machine and mtime tracking stay on this manager.
    (No _store_lock — route _watcher_tick never writes to disk, so there
    is no Timer-vs-event-loop race; YAGNI per Phase-4a adversarial review.)
    """

    def __init__(self, repo: RouteRepository) -> None:
        self.store = RouteStore(categories=[_default_category()], routes=[])
        self._repo = repo
        self._load()
        self._last_loaded_mtime: float = self._stat_mtime()
        # Handle to the watch on the shared file_watcher Observer; set
        # by start_watcher, cleared by stop_watcher.
        self._watch: ObservedWatch | None = None
        self._watcher_debounce_timer: threading.Timer | None = None
        self._on_external_change: Callable[[], None] | None = None

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _routes_path(self) -> Path:
        return self._repo.path()

    def _load(self) -> None:
        self.store = self._repo.load()

    def _save(self) -> None:
        """Persist via unconditional read-merge-write delegated to the repo.

        Reads the current on-disk file and runs the commutative merge_stores
        against it before writing, so a concurrent write from another device
        (delivered through iCloud since our last load) is folded in rather
        than clobbered. Merging an unchanged file is a no-op (merge is
        idempotent)."""
        self.store = self._repo.save(self.store)
        self._last_loaded_mtime = self._stat_mtime()

    def _stat_mtime(self) -> float:
        try:
            return self._repo.path().stat().st_mtime
        except FileNotFoundError:
            return 0.0

    def start_watcher(self, on_change: Callable[[], None]) -> None:
        """Begin watching the routes file for external modifications.

        *on_change* is invoked (no args) on the watcher thread AFTER
        self.store has been reloaded from disk. Callers are responsible
        for marshalling onto whatever loop/thread they need (e.g. asyncio
        via run_coroutine_threadsafe).
        """
        self.stop_watcher()
        path = self._repo.path()
        parent = path.parent
        if not parent.exists():
            logger.warning("Routes folder does not exist; watcher not started: %s", parent)
            return
        self._on_external_change = on_change
        manager = self

        class _Handler(FileSystemEventHandler):
            def on_modified(self, event):
                if event.is_directory:
                    return
                if Path(event.src_path) != manager._routes_path():
                    return
                manager._schedule_reconcile()

            on_created = on_modified

            def on_moved(self, event):
                if event.is_directory:
                    return
                rp = manager._routes_path()
                if Path(event.src_path) != rp and Path(getattr(event, "dest_path", "")) != rp:
                    return
                manager._schedule_reconcile()

        self._watch = _watcher_schedule(_Handler(), parent)
        logger.info("Route watcher scheduled on %s", parent)

    def stop_watcher(self) -> None:
        if self._watcher_debounce_timer is not None:
            self._watcher_debounce_timer.cancel()
            self._watcher_debounce_timer = None
        if self._watch is not None:
            _watcher_unschedule(self._watch)
            self._watch = None

    def _schedule_reconcile(self) -> None:
        if self._watcher_debounce_timer is not None:
            self._watcher_debounce_timer.cancel()
        self._watcher_debounce_timer = threading.Timer(0.5, self._watcher_tick)
        self._watcher_debounce_timer.daemon = True
        self._watcher_debounce_timer.start()

    def _watcher_tick(self) -> None:
        try:
            path = self._repo.path()
            try:
                current_mtime = path.stat().st_mtime
            except FileNotFoundError:
                return
            if current_mtime <= self._last_loaded_mtime:
                return  # self-echo or already reconciled
            before = self.store.model_dump_json()
            # Merge the external write into our in-memory store instead of
            # the old whole-file _load() replace — a blind reload dropped any
            # local edit not yet flushed to disk.
            self.store = merge_stores(self.store, self._repo.load_or_empty())
            after = self.store.model_dump_json()
            self._last_loaded_mtime = current_mtime
            if before != after and self._on_external_change is not None:
                try:
                    self._on_external_change()
                except Exception:
                    logger.exception("Route on_external_change callback raised")
        except Exception:
            logger.exception("Route watcher tick failed")

    # ------------------------------------------------------------------
    # Categories
    # ------------------------------------------------------------------

    def list_categories(self) -> list[RouteCategory]:
        return sorted(self.store.categories, key=lambda c: c.sort_order)

    def create_category(self, name: str, color: str = "#6c8cff") -> RouteCategory:
        max_order = max((c.sort_order for c in self.store.categories), default=-1)
        now = _now_iso()
        cat = RouteCategory(
            id=str(uuid.uuid4()),
            name=name,
            color=color,
            sort_order=max_order + 1,
            created_at=now,
            updated_at=now,
        )
        self.store.categories.append(cat)
        self._save()
        return cat

    def update_category(
        self,
        cat_id: str,
        name: str | None = None,
        color: str | None = None,
    ) -> RouteCategory | None:
        cat = self._find_category(cat_id)
        if cat is None:
            return None
        if name is not None:
            cat.name = name
        if color is not None:
            cat.color = color
        cat.updated_at = _now_iso()
        self._save()
        return cat

    def delete_category(self, cat_id: str) -> bool:
        if cat_id == "default":
            logger.warning("Cannot delete the default route category")
            return False
        cat = self._find_category(cat_id)
        if cat is None:
            return False
        now = _now_iso()
        for r in self.store.routes:
            if r.category_id == cat_id:
                r.category_id = "default"
                r.updated_at = now  # reparenting is a modification
        self.store.categories = [c for c in self.store.categories if c.id != cat_id]
        self.store.tombstones.append(_tombstone(cat_id, "category"))
        self._save()
        return True

    def _find_category(self, cat_id: str) -> RouteCategory | None:
        return next((c for c in self.store.categories if c.id == cat_id), None)

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------

    def list_routes(self) -> list[SavedRoute]:
        """Routes ordered by category (sort_order), then by created_at within
        a category, then id as a stable tiebreak.

        merge_stores persists ``self.store.routes`` id-sorted for a
        deterministic, commutative file — meaningless to a human. This read
        path restores a sensible order for the API and UI. Routes whose
        category no longer exists sort last."""
        order = {c.id: c.sort_order for c in self.store.categories}
        return sorted(
            self.store.routes,
            key=lambda r: (
                order.get(r.category_id, float("inf")),
                r.created_at or "",
                r.id,
            ),
        )

    def find_by_name(self, name: str) -> SavedRoute | None:
        """First exact-name match. Used by the overwrite-on-save flow on
        the rare cases the front-end doesn't already know the id."""
        target = name.strip()
        return next((r for r in self.store.routes if r.name == target), None)

    def create_route(self, route: SavedRoute) -> SavedRoute:
        # Validate category; fall back to default when the caller passed
        # something unknown (e.g. a category that's been deleted).
        if self._find_category(route.category_id) is None:
            route.category_id = "default"
        route.id = str(uuid.uuid4())
        now = _now_iso()
        route.created_at = now
        route.updated_at = now
        self.store.routes.append(route)
        self._save()
        return route

    def replace_route(self, route_id: str, incoming: SavedRoute) -> SavedRoute | None:
        """Replace an existing route's mutable fields in-place.

        Keeps id and created_at; updates name, waypoints, profile,
        category_id, and stamps updated_at. This is the backend half of
        the "save and overwrite same-named route" UX.
        """
        existing = self._find_route(route_id)
        if existing is None:
            return None
        if self._find_category(incoming.category_id) is None:
            incoming.category_id = existing.category_id
        existing.name = incoming.name
        existing.waypoints = incoming.waypoints
        existing.profile = incoming.profile
        existing.category_id = incoming.category_id
        existing.updated_at = _now_iso()
        self._save()
        return existing

    def rename_route(self, route_id: str, name: str) -> SavedRoute | None:
        route = self._find_route(route_id)
        if route is None:
            return None
        route.name = name
        route.updated_at = _now_iso()
        self._save()
        return route

    def delete_route(self, route_id: str) -> bool:
        before = len(self.store.routes)
        self.store.routes = [r for r in self.store.routes if r.id != route_id]
        if len(self.store.routes) < before:
            self.store.tombstones.append(_tombstone(route_id, "route"))
            self._save()
            return True
        return False

    def move_routes(self, route_ids: list[str], target_category_id: str) -> int:
        if self._find_category(target_category_id) is None:
            logger.warning("Target route category %s does not exist", target_category_id)
            return 0
        ids_set = set(route_ids)
        moved = 0
        for r in self.store.routes:
            if r.id in ids_set and r.category_id != target_category_id:
                r.category_id = target_category_id
                r.updated_at = _now_iso()
                moved += 1
        if moved:
            self._save()
        return moved

    def _find_route(self, route_id: str) -> SavedRoute | None:
        return next((r for r in self.store.routes if r.id == route_id), None)

    # ------------------------------------------------------------------
    # Import / Export
    # ------------------------------------------------------------------

    def export_json(self) -> str:
        return self.store.model_dump_json(indent=2)

    def import_json(self, data: str) -> int:
        """Merge an exported route bundle into the current store.

        Behaviour:
          - Categories: imported only if their id is new.
          - Routes: imported with their original id when free; on id
            collision a fresh id is minted so the existing route is
            preserved. On name collision inside the same category the
            imported route gets a `(匯入)` suffix so both stay visible.
          - A route pointing at an unknown category_id falls back to default.
        """
        try:
            incoming = RouteStore(**json.loads(data))
        except Exception as exc:
            logger.error("Invalid route JSON: %s", exc)
            return 0

        existing_cat_ids = {c.id for c in self.store.categories}
        for cat in incoming.categories:
            if cat.id and cat.id not in existing_cat_ids:
                self.store.categories.append(cat)
                existing_cat_ids.add(cat.id)

        existing_route_ids = {r.id for r in self.store.routes}
        imported = 0
        for r in incoming.routes:
            if r.category_id not in existing_cat_ids:
                r.category_id = "default"
            if not r.id or r.id in existing_route_ids:
                r.id = str(uuid.uuid4())
            siblings = [
                s for s in self.store.routes
                if s.category_id == r.category_id and s.name == r.name
            ]
            if siblings:
                r.name = f"{r.name} (匯入)"
            if not r.created_at:
                r.created_at = _now_iso()
            self.store.routes.append(r)
            existing_route_ids.add(r.id)
            imported += 1

        if imported:
            self._save()
        logger.info("Imported %d routes", imported)
        return imported
