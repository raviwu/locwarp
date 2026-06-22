"""Bookmark and category management with JSON file persistence."""

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

from config import BOOKMARKS_FILE, get_bookmarks_path
from domain.ports.bookmark_repository import BookmarkRepository
from models.schemas import Bookmark, BookmarkCategory, BookmarkStore, Tombstone
from services.file_watcher import schedule as _watcher_schedule, unschedule as _watcher_unschedule
from services.json_safe import safe_load_json, safe_write_json
from domain.store_merge import force_seed_items
from services.store_merge import merge_stores
from services.geo_offline import resolve as _geo_resolve

logger = logging.getLogger(__name__)

# Keep a reference to the config default so _bookmarks_path_default() can detect
# when tests (or other callers) have monkeypatched the module-level name.
_CONFIG_DEFAULT_BOOKMARKS_FILE = BOOKMARKS_FILE


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tombstone(obj_id: str, kind: str) -> Tombstone:
    """Build a deletion record so the delete propagates across cloud-synced
    devices instead of being resurrected by a concurrent writer."""
    return Tombstone(id=obj_id, kind=kind, deleted_at=_now_iso())


def _bookmarks_path_default() -> Path:
    """Resolve the bookmarks file path, honouring test monkeypatches.

    Kept as a module-level function so the BOOKMARKS_FILE monkeypatch seam
    (used by ~16 test fixtures) is preserved when this is passed as the
    path_provider to JsonStore via bootstrap.factories.
    """
    if BOOKMARKS_FILE is not _CONFIG_DEFAULT_BOOKMARKS_FILE:
        return Path(BOOKMARKS_FILE)
    return get_bookmarks_path()


def enrich_bookmark(bm: Bookmark, *, force: bool = False) -> bool:
    """Fill a bookmark's offline geo fields from its coordinates.

    country_code / timezone / city / region come from
    ``geo_offline.resolve``. With ``force=False`` (default) only empty
    fields are filled — an idempotent reconciliation safe to run on every
    bookmark repeatedly. With ``force=True`` every field is re-resolved
    and overwritten — used when a bookmark's coordinates change.

    Never writes an empty value: a failed or ocean-point lookup leaves
    the existing fields untouched rather than wiping them, so a transient
    data-load failure cannot destroy good data (the trade-off: moving a
    bookmark from land to open ocean keeps its now-stale labels — a rare,
    cosmetic edge). Returns True if any field changed.

    Does NOT touch ``updated_at`` — callers own that, so the startup
    sweep can fill legacy records without forcing a cloud-sync write.
    """
    all_filled = bool(bm.country_code and bm.timezone and bm.city and bm.region)
    if not force and all_filled:
        return False
    # Local is `tz`, not `timezone`, to avoid shadowing `datetime.timezone`
    # (imported at module scope and used by _now_iso).
    country_code, tz, city, region = _geo_resolve(bm.lat, bm.lng)
    changed = False
    for field, value in (
        ("country_code", country_code),
        ("timezone", tz),
        ("city", city),
        ("region", region),
    ):
        if not value:
            continue  # never overwrite a known value with an empty lookup
        current = getattr(bm, field)
        if (force or not current) and current != value:
            setattr(bm, field, value)
            changed = True
    return changed


class BookmarkManager:
    """CRUD manager for bookmarks and categories.

    State is persisted via the injected BookmarkRepository (JSON) on every
    write operation. The watcher state machine, threading.Lock, and mtime
    tracking all stay on this manager.
    """

    def __init__(self, repo: BookmarkRepository) -> None:
        self.store = BookmarkStore(
            categories=[
                BookmarkCategory(
                    id="default",
                    name="預設",
                    color="#6c8cff",
                    sort_order=0,
                    created_at=_now_iso(),
                )
            ],
            bookmarks=[],
        )
        # mtime of the file as of our last load/save. The watcher compares
        # against it to skip self-echo events. No longer load-bearing for
        # merge correctness — merge_stores is commutative — just an
        # optimisation to avoid redundant reconcile work.
        self._last_loaded_mtime: float = 0.0
        # Serialise cross-thread store read-modify-write.  _save runs on the
        # asyncio event-loop thread; _watcher_tick runs on a daemon
        # threading.Timer thread.  asyncio.Lock cannot be used here because
        # one side is a non-async thread — threading.Lock is correct.
        #
        # FUTURE MAINTAINER NOTE: do NOT change _watcher_tick's thread-
        # affinity (e.g. marshal it onto the event loop via
        # loop.call_soon_threadsafe) without re-proving atomicity.  The 40+
        # single-threaded bookmark tests in test_bookmark_concurrency.py
        # cannot catch a Timer-vs-event-loop interleave; only the real-thread
        # stress test in test_bookmarks_thread_race.py does.  A refactor that
        # changes thread boundaries must add or extend that test accordingly.
        self._store_lock = threading.Lock()
        self._repo = repo
        self._load()
        # Handle to the watch on the shared file_watcher Observer; set
        # by start_watcher, cleared by stop_watcher.
        self._watch: ObservedWatch | None = None
        self._watcher_debounce_timer: threading.Timer | None = None
        self._on_external_change: Callable[[], None] | None = None

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        self.store = self._repo.load()
        self._record_disk_mtime()

    def _save(self) -> None:
        """Persist the current store to disk via unconditional read-merge-write.

        Delegates the read-merge-write to the injected repo. Holds _store_lock
        across the call so a concurrent _watcher_tick cannot interleave.
        """
        with self._store_lock:
            self.store = self._repo.save(self.store)
            self._record_disk_mtime()

    def _reconcile_from_disk(self) -> None:
        """Merge external on-disk changes into self.store via merge_stores.

        No-op when the on-disk file is empty/missing (transient iCloud
        eviction) — load_or_empty yields an empty store and merging
        with empty leaves self.store untouched.
        """
        path = self._repo.path()
        try:
            if path.stat().st_size == 0:
                return
        except FileNotFoundError:
            return
        self.store = merge_stores(self.store, self._repo.load_or_empty())

    def _record_disk_mtime(self) -> None:
        """Record the file's mtime at the moment self.store is known in sync
        with disk. Used only by the watcher to skip self-echo events."""
        path = self._repo.path()
        try:
            self._last_loaded_mtime = path.stat().st_mtime
        except FileNotFoundError:
            self._last_loaded_mtime = 0.0

    def _bookmarks_path(self) -> Path:
        return self._repo.path()

    # ------------------------------------------------------------------
    # File watcher
    # ------------------------------------------------------------------

    def start_watcher(self, on_change: Callable[[], None]) -> None:
        """Begin watching the bookmarks file for external modifications.

        *on_change* is invoked (no args) on the watcher thread AFTER
        self.store has been reconciled with disk. Callers are responsible
        for marshalling onto whatever loop/thread they need (e.g. asyncio
        via run_coroutine_threadsafe).
        """
        self.stop_watcher()
        path = self._repo.path()
        parent = path.parent
        if not parent.exists():
            logger.warning("Bookmark folder does not exist; watcher not started: %s", parent)
            return
        self._on_external_change = on_change

        manager = self

        class _Handler(FileSystemEventHandler):
            def on_modified(self, event):
                if event.is_directory:
                    return
                if Path(event.src_path) != manager._bookmarks_path():
                    return
                manager._schedule_reconcile()

            on_created = on_modified

            def on_moved(self, event):
                if event.is_directory:
                    return
                bm = manager._bookmarks_path()
                if Path(event.src_path) != bm and Path(getattr(event, "dest_path", "")) != bm:
                    return
                manager._schedule_reconcile()

        self._watch = _watcher_schedule(_Handler(), parent)
        logger.info("Bookmark watcher scheduled on %s", parent)

    def stop_watcher(self) -> None:
        if self._watcher_debounce_timer is not None:
            self._watcher_debounce_timer.cancel()
            self._watcher_debounce_timer = None
        if self._watch is not None:
            _watcher_unschedule(self._watch)
            self._watch = None

    def _schedule_reconcile(self) -> None:
        """Debounce rapid mtime events from a single sync burst."""
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
                return  # transient absence (iCloud cloud-only eviction); retry on next event
            if current_mtime <= self._last_loaded_mtime:
                return  # self-echo or already reconciled
            # Hold _store_lock across the full read-merge-write so this Timer
            # daemon thread is serialised against _save (event-loop thread).
            # The callback is intentionally run OUTSIDE the lock: it may
            # re-enter the manager (which would call _save → lock again) and
            # could take an unbounded amount of time — both would deadlock or
            # stall if the lock were held here.
            with self._store_lock:
                before_payload = self.store.model_dump_json()
                self._reconcile_from_disk()
                after_payload = self.store.model_dump_json()
                if before_payload != after_payload:
                    # Persist the merged state so disk reflects local edits we
                    # may have reapplied on top of the remote update.
                    payload = json.loads(after_payload)
                    safe_write_json(path, payload)
                    self._record_disk_mtime()
                    fire_callback = True
                else:
                    self._record_disk_mtime()  # still resync mtime
                    fire_callback = False
            # Callback runs outside the lock (see note above).
            if fire_callback and self._on_external_change is not None:
                try:
                    self._on_external_change()
                except Exception:
                    logger.exception("on_external_change callback raised")
        except Exception:
            logger.exception("Bookmark watcher tick failed")

    # ------------------------------------------------------------------
    # Categories
    # ------------------------------------------------------------------

    def create_category(
        self,
        name: str,
        color: str = "#6c8cff",
        start_date: str = "",
        end_date: str = "",
    ) -> BookmarkCategory:
        """Create and return a new category."""
        max_order = max((c.sort_order for c in self.store.categories), default=-1)
        now = _now_iso()
        cat = BookmarkCategory(
            id=str(uuid.uuid4()),
            name=name,
            color=color,
            sort_order=max_order + 1,
            created_at=now,
            start_date=start_date,
            end_date=end_date,
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
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> BookmarkCategory | None:
        """Update a category's mutable fields. Returns ``None`` if not found.

        ``None`` for any field means "do not modify"; pass an empty string
        to clear ``start_date`` or ``end_date``.
        """
        cat = self._find_category(cat_id)
        if cat is None:
            return None
        if name is not None:
            cat.name = name
        if color is not None:
            cat.color = color
        if start_date is not None:
            cat.start_date = start_date
        if end_date is not None:
            cat.end_date = end_date
        cat.updated_at = _now_iso()
        self._save()
        return cat

    def delete_category(self, cat_id: str, cascade: bool = False) -> dict | bool:
        """Delete a category.

        With ``cascade=False`` (default), bookmarks in the deleted category are
        moved to ``default``. With ``cascade=True``, those bookmarks are
        deleted along with the category.

        The ``default`` category cannot be deleted in either mode.

        Returns ``False`` when the category is missing or is ``default``.
        Otherwise returns ``{"deleted": True, "deleted_bookmarks": N}``.
        """
        if cat_id == "default":
            logger.warning("Cannot delete the default category")
            return False

        cat = self._find_category(cat_id)
        if cat is None:
            return False

        deleted_count = 0
        now = _now_iso()
        if cascade:
            kept = []
            for bm in self.store.bookmarks:
                if bm.category_id == cat_id:
                    deleted_count += 1
                    # Cascade-deleted bookmarks get their own tombstones so
                    # the deletion propagates per-item, not just per-category.
                    self.store.tombstones.append(_tombstone(bm.id, "bookmark"))
                else:
                    kept.append(bm)
            self.store.bookmarks = kept
        else:
            for bm in self.store.bookmarks:
                if bm.category_id == cat_id:
                    bm.category_id = "default"
                    bm.updated_at = now  # reparenting is a modification

        self.store.categories = [c for c in self.store.categories if c.id != cat_id]
        self.store.tombstones.append(_tombstone(cat_id, "category"))
        self._save()
        return {"deleted": True, "deleted_bookmarks": deleted_count}

    def list_categories(self) -> list[BookmarkCategory]:
        return sorted(self.store.categories, key=lambda c: c.sort_order)

    def _find_category(self, cat_id: str) -> BookmarkCategory | None:
        return next((c for c in self.store.categories if c.id == cat_id), None)

    # ------------------------------------------------------------------
    # Bookmarks
    # ------------------------------------------------------------------

    def create_bookmark(
        self,
        name: str,
        lat: float,
        lng: float,
        address: str = "",
        category_id: str = "default",
        country_code: str = "",
    ) -> Bookmark:
        """Create a new bookmark."""
        # Validate category
        if self._find_category(category_id) is None:
            category_id = "default"

        now = _now_iso()
        bm = Bookmark(
            id=str(uuid.uuid4()),
            name=name,
            lat=lat,
            lng=lng,
            address=address,
            category_id=category_id,
            created_at=now,
            last_used_at=now,
            country_code=country_code.lower(),
            updated_at=now,
        )
        # Offline-resolve country / timezone / city / region. force=False
        # respects an explicitly supplied country_code; the other three are
        # always blank on a fresh bookmark and get filled.
        enrich_bookmark(bm)
        self.store.bookmarks.append(bm)
        self._save()
        return bm

    def update_bookmark(self, bm_id: str, **kwargs: object) -> Bookmark | None:
        """Update a bookmark's fields. Returns ``None`` if not found.

        When the coordinates change, the offline geo fields (country_code,
        timezone, city, region) are re-resolved from the new position via
        ``enrich_bookmark(force=True)`` so the bookmark's flag / city /
        timezone labels never go stale. The resolver is authoritative on a
        coord-change re-resolve: an explicit ``country_code`` passed in the
        same call is overwritten. If the new coordinates cannot be resolved
        (transient data-load failure), the geo fields are left at their
        prior values rather than wiped — see ``enrich_bookmark``.
        """
        bm = self._find_bookmark(bm_id)
        if bm is None:
            return None

        old_lat, old_lng = bm.lat, bm.lng
        allowed = {"name", "lat", "lng", "address", "category_id", "last_used_at", "country_code"}
        for key, value in kwargs.items():
            if key in allowed and value is not None:
                setattr(bm, key, value)

        # Float equality is safe here: no arithmetic was performed on
        # lat/lng, so an unchanged coordinate compares equal bit-for-bit.
        if bm.lat != old_lat or bm.lng != old_lng:
            enrich_bookmark(bm, force=True)

        bm.updated_at = _now_iso()
        self._save()
        return bm

    def delete_bookmark(self, bm_id: str) -> bool:
        """Delete a bookmark by ID."""
        before = len(self.store.bookmarks)
        self.store.bookmarks = [b for b in self.store.bookmarks if b.id != bm_id]
        if len(self.store.bookmarks) < before:
            self.store.tombstones.append(_tombstone(bm_id, "bookmark"))
            self._save()
            return True
        return False

    def list_bookmarks(self) -> list[Bookmark]:
        """Bookmarks ordered by category (sort_order), then by created_at
        within a category, then id as a stable tiebreak.

        merge_stores persists ``self.store.bookmarks`` id-sorted for a
        deterministic, commutative file — meaningless to a human. This read
        path restores a sensible order for the API and UI. Bookmarks whose
        category no longer exists sort last."""
        order = {c.id: c.sort_order for c in self.store.categories}
        return sorted(
            self.store.bookmarks,
            key=lambda b: (
                order.get(b.category_id, float("inf")),
                b.created_at or "",
                b.id,
            ),
        )

    def move_bookmarks(
        self,
        bookmark_ids: list[str],
        target_category_id: str,
    ) -> int:
        """Move multiple bookmarks to *target_category_id*.

        Returns the number of bookmarks actually moved.
        """
        if self._find_category(target_category_id) is None:
            logger.warning("Target category %s does not exist", target_category_id)
            return 0

        moved = 0
        ids_set = set(bookmark_ids)
        now = _now_iso()
        for bm in self.store.bookmarks:
            if bm.id in ids_set and bm.category_id != target_category_id:
                bm.category_id = target_category_id
                bm.updated_at = now
                moved += 1

        if moved:
            self._save()
        return moved

    def enrich_all(self) -> int:
        """Reconciliation sweep: fill missing offline geo fields on every
        bookmark, persisting once if anything changed.

        Runs at startup. ``enrich_bookmark`` only fills blanks here
        (force=False) and does not touch ``updated_at``, so legacy records
        get their flag / city / timezone without manufacturing a
        cloud-sync conflict — every device resolves identical values from
        the same coordinates and converges. Idempotent: once every
        bookmark is filled, later sweeps change nothing and skip the save.

        Cross-version note: an older client that lacks the geo fields in
        its schema will strip them on its next write (pydantic v2 silently
        drops unknown fields). The new client's next sweep refills them.
        That cycle is harmless because the values are deterministic from
        (lat, lng) — just don't try to "optimize" the sweep away.

        Returns the number of bookmarks modified.
        """
        changed = 0
        for bm in self.store.bookmarks:
            if enrich_bookmark(bm):
                changed += 1
        # Always log — a "0 filled" line confirms the sweep ran on a
        # clean store, distinguishing it from a sweep that never fired.
        logger.info("enrich_all filled geo fields on %d bookmarks", changed)
        if changed:
            self._save()
        return changed

    def _find_bookmark(self, bm_id: str) -> Bookmark | None:
        return next((b for b in self.store.bookmarks if b.id == bm_id), None)

    # ------------------------------------------------------------------
    # Import / Export
    # ------------------------------------------------------------------

    def export_json(self) -> str:
        """Serialise the entire store to a JSON string."""
        return self.store.model_dump_json(indent=2)

    def import_json(self, data: str) -> dict:
        """Import bookmarks (and optionally categories) from a JSON string.

        Merges into the existing store -- duplicates by ID are skipped.

        Returns ``{"imported": N, "skipped": M}`` so callers can distinguish
        new entries from collisions. Returns ``{"imported": 0, "skipped": 0}``
        on parse failure.
        """
        try:
            incoming = BookmarkStore(**json.loads(data))
        except Exception as exc:
            logger.error("Invalid bookmark JSON: %s", exc)
            return {"imported": 0, "skipped": 0}

        existing_cat_ids = {c.id for c in self.store.categories}
        for cat in incoming.categories:
            if cat.id not in existing_cat_ids:
                self.store.categories.append(cat)
                existing_cat_ids.add(cat.id)

        existing_bm_ids = {b.id for b in self.store.bookmarks}
        imported = 0
        skipped = 0
        for bm in incoming.bookmarks:
            if bm.id not in existing_bm_ids:
                # Ensure the bookmark's category exists
                if bm.category_id not in existing_cat_ids:
                    bm.category_id = "default"
                enrich_bookmark(bm)  # fill any geo fields the import lacked
                self.store.bookmarks.append(bm)
                existing_bm_ids.add(bm.id)
                imported += 1
            else:
                skipped += 1

        if imported:
            self._save()
        logger.info("Imported %d bookmarks (%d skipped as duplicates)", imported, skipped)
        return {"imported": imported, "skipped": skipped}

    def import_catalog(self, data: str) -> dict:
        """Force-sync from the bundled catalog. Catalog ids are authoritative.

        Differences from :meth:`import_json`:

        * Existing items with catalog ids are **upserted** (name / coords /
          category etc. overwritten with the catalog version) — the
          catalog is the source of truth, so coordinate corrections and
          renames propagate.
        * Every imported item gets ``updated_at = now()``. This is the
          load-bearing detail: locally-deleted catalog entries have a
          tombstone whose ``deleted_at`` is a real ISO timestamp; the
          catalog's incoming ``updated_at`` is empty, so the CRDT
          ``_alive(...)`` check would otherwise let the tombstone win and
          silently kill the import inside ``_save()``. Stamping
          ``updated_at = now()`` flips that contest, resurrecting the
          item.
        * Local items whose ids are NOT in the catalog are left alone.

        Returns ``{'added': N, 'updated': N, 'resurrected': N}`` where
        *resurrected* counts incoming ids that had a tombstone before
        this call. The tombstones themselves are not removed — the
        ``updated_at > deleted_at`` rule handles the resurrection, and
        the stale tombstones GC out after ``TOMBSTONE_RETENTION_DAYS``.
        """
        try:
            incoming = BookmarkStore(**json.loads(data))
        except Exception as exc:
            logger.error("Invalid catalog JSON: %s", exc)
            return {"added": 0, "updated": 0, "resurrected": 0}

        now = _now_iso()
        catalog_ids = {c.id for c in incoming.categories} | {b.id for b in incoming.bookmarks}
        resurrected = sum(1 for t in self.store.tombstones if t.id in catalog_ids)

        force_seed_items(incoming.categories, now)
        force_seed_items(incoming.bookmarks, now)

        existing_cats = {c.id: c for c in self.store.categories}
        added_cats = updated_cats = 0
        for cat in incoming.categories:
            if cat.id in existing_cats:
                old = existing_cats[cat.id]
                old.name = cat.name
                old.color = cat.color
                old.sort_order = cat.sort_order
                old.start_date = cat.start_date
                old.end_date = cat.end_date
                old.updated_at = now
                updated_cats += 1
            else:
                self.store.categories.append(cat)
                existing_cats[cat.id] = cat
                added_cats += 1

        valid_cat_ids = {c.id for c in self.store.categories}
        existing_bms = {b.id: b for b in self.store.bookmarks}
        added_bms = updated_bms = 0
        for bm in incoming.bookmarks:
            if bm.category_id not in valid_cat_ids:
                bm.category_id = "default"
            if bm.id in existing_bms:
                old = existing_bms[bm.id]
                old.name = bm.name
                old.lat = bm.lat
                old.lng = bm.lng
                old.address = bm.address
                old.category_id = bm.category_id
                old.country_code = bm.country_code
                old.updated_at = now
                enrich_bookmark(old, force=True)
                updated_bms += 1
            else:
                enrich_bookmark(bm)
                self.store.bookmarks.append(bm)
                existing_bms[bm.id] = bm
                added_bms += 1

        self._save()
        logger.info(
            "Catalog sync: +%d added, %d updated, %d resurrected",
            added_cats + added_bms, updated_cats + updated_bms, resurrected,
        )
        return {
            "added": added_cats + added_bms,
            "updated": updated_cats + updated_bms,
            "resurrected": resurrected,
        }

    def force_seed(self, items: list) -> dict:
        """Upsert a list of Bookmark items, stamping each with the current time.

        Uses ``force_seed_items`` to guarantee every item's ``updated_at``
        beats any pre-existing real-timestamp tombstone in the CRDT merge —
        encoding the empty-updated_at pitfall so callers don't have to know
        about it.

        Returns ``{'added': N, 'updated': N}`` where *added* counts items
        that were new to the store and *updated* counts items that replaced
        an existing entry.
        """
        now = _now_iso()
        force_seed_items(items, now)

        existing = {b.id: b for b in self.store.bookmarks}
        added = updated = 0
        for bm in items:
            if bm.id in existing:
                old = existing[bm.id]
                old.name = bm.name
                old.lat = bm.lat
                old.lng = bm.lng
                old.address = bm.address
                old.category_id = bm.category_id
                old.country_code = bm.country_code
                old.updated_at = bm.updated_at
                enrich_bookmark(old, force=True)
                updated += 1
            else:
                enrich_bookmark(bm)
                self.store.bookmarks.append(bm)
                existing[bm.id] = bm
                added += 1

        self._save()
        return {"added": added, "updated": updated}
