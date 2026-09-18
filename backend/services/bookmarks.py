"""Bookmark and category management with JSON file persistence."""

from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from config import BOOKMARKS_FILE, get_bookmarks_path
from domain.catalog_merge import (
    BOOKMARK_MERGE_FIELDS,
    CATEGORY_MERGE_FIELDS,
    Resolution,
    resolve_record,
)
from domain.coords import round_coord
from domain.ports.bookmark_repository import BookmarkRepository
from domain.ports.catalog_baseline_repository import CatalogBaselineRepository
from models.schemas import Bookmark, BookmarkCategory, BookmarkStore, Tombstone
from services.file_watch_binding import FileWatchBinding
from domain.store_merge import (
    BOOKMARK_MERGE_UNITS,
    CATEGORY_MERGE_UNITS,
    force_seed_items,
    stamp_units,
)
from services.store_merge import merge_stores
from services.geo_offline import resolve as _geo_resolve

logger = logging.getLogger(__name__)

# Keep a reference to the config default so _bookmarks_path_default() can detect
# when tests (or other callers) have monkeypatched the module-level name.
_CONFIG_DEFAULT_BOOKMARKS_FILE = BOOKMARKS_FILE


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _baseline_entry(section: dict, item_id: str) -> dict | None:
    """One record's baseline values, or None to bootstrap that record.

    Tolerates a hand-edited or truncated baseline file: anything that is not a
    dict reads as "no baseline here", which resolve_record handles as
    ``base := theirs`` — the same safe path a first run takes.
    """
    entry = section.get(item_id)
    return entry if isinstance(entry, dict) else None


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


def _units_changed(pending) -> set[str]:
    """Merge units touched by a set of changed field names.

    A field that belongs to no unit (the geo four, which ride with `coords`)
    contributes nothing — enrich_bookmark owns those and must never stamp.
    """
    field_to_unit = {
        f: unit
        for units in (BOOKMARK_MERGE_UNITS, CATEGORY_MERGE_UNITS)
        for unit, fields in units.items()
        for f in fields
    }
    geo = {"country_code", "timezone", "city", "region"}
    return {field_to_unit[f] for f in pending if f in field_to_unit and f not in geo}


class BookmarkManager:
    """CRUD manager for bookmarks and categories.

    State is persisted via the injected BookmarkRepository (JSON) on every
    write operation. The watcher state machine, threading.Lock, and mtime
    tracking all stay on this manager.

    bootstrap.factories.make_bookmark_manager is the only intended constructor:
    it injects both ports. Building one directly leaves ``catalog_baseline``
    None, which degrades the catalog force-sync to its permanent-bootstrap path
    (every diverged field reads as a local edit forever).
    """

    def __init__(
        self,
        repo: BookmarkRepository,
        catalog_baseline: CatalogBaselineRepository | None = None,
    ) -> None:
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
        # Per-machine snapshot of the catalog values last applied here, read as
        # the `base` of the force-sync's three-way merge. Injected (never built
        # here) so services stays clear of infra, and per manager rather than
        # process-wide because the baseline is per machine.
        self._catalog_baseline = catalog_baseline
        self._load()
        # FileWatchBinding owns the watchdog plumbing + debounce; set by
        # start_watcher, cleared by stop_watcher. _on_external_change is still
        # set in start_watcher and fired inside _watcher_tick (after _store_lock).
        self._watch_binding: FileWatchBinding | None = None
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
        self._on_external_change = on_change
        self._watch_binding = FileWatchBinding(self._bookmarks_path, self._watcher_tick)
        self._watch_binding.start()

    def stop_watcher(self) -> None:
        if self._watch_binding is not None:
            self._watch_binding.stop()
            self._watch_binding = None

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
                    # Persist the merged state through the repo (read-merge-write +
                    # tombstone GC) so disk reflects local edits we may have
                    # reapplied on top of the remote update. We already hold
                    # _store_lock, so call the repo directly rather than _save()
                    # (which would re-acquire the non-reentrant lock).
                    self.store = self._repo.save(self.store)
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

        A call whose supplied values all already match the stored category is
        a no-op: ``updated_at`` is left alone and ``_save()`` is skipped, for
        the same reason as :meth:`update_bookmark`. The category dialog
        submits an empty patch when the user opened it and changed nothing,
        and the re-stamp on its own is enough to replace the other Mac's
        un-synced rename inside merge_stores.
        """
        cat = self._find_category(cat_id)
        if cat is None:
            return None

        pending: dict[str, str] = {}
        for key, value in (
            ("name", name),
            ("color", color),
            ("start_date", start_date),
            ("end_date", end_date),
        ):
            if value is None or getattr(cat, key) == value:
                continue
            pending[key] = value
        if not pending:
            return cat

        for key, value in pending.items():
            setattr(cat, key, value)
        stamp_units(cat, _units_changed(pending), _now_iso(), CATEGORY_MERGE_UNITS)
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
            lat=round_coord(lat),
            lng=round_coord(lng),
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

        A ``None`` value means "leave this field unchanged" — that is what lets
        the partial-update PUT tell an omitted key apart from a deliberate
        blank.

        A call whose supplied values all already match the stored record is a
        no-op: ``updated_at`` is left alone and ``_save()`` is skipped
        entirely. The re-stamp on its own would be enough to revert another
        machine, because merge_stores replaces the whole record by
        ``updated_at`` — so a Save that changed nothing must never reach the
        merge carrying a fresh timestamp.

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

        allowed = {"name", "lat", "lng", "address", "category_id", "last_used_at", "country_code"}
        # Diff before mutating, so "nothing actually differs" is still
        # answerable. Coordinates are rounded first, so float noise below store
        # precision does not read as an edit.
        pending: dict[str, object] = {}
        for key, value in kwargs.items():
            if key not in allowed or value is None:
                continue
            if key in ("lat", "lng"):
                value = round_coord(value)  # type: ignore[arg-type]
            # Float equality is safe here: no arithmetic was performed on
            # lat/lng, so an unchanged coordinate compares equal bit-for-bit.
            if getattr(bm, key) != value:
                pending[key] = value
        if not pending:
            return bm

        for key, value in pending.items():
            setattr(bm, key, value)

        if "lat" in pending or "lng" in pending:
            enrich_bookmark(bm, force=True)

        # Stamp the units this write actually touched. The geo fields
        # enrich_bookmark just refreshed are part of the `coords` unit, so they
        # need no stamp of their own.
        stamp_units(bm, _units_changed(pending), _now_iso(), BOOKMARK_MERGE_UNITS)
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
                # This record ships to the merge on a fresh timestamp, so it has
                # to carry a rounded coordinate like every other write path —
                # otherwise a legacy long-precision value wins every later merge
                # while keeping its drifted tail.
                rounded = (round_coord(bm.lat), round_coord(bm.lng))
                coords_changed = rounded != (bm.lat, bm.lng)
                bm.lat, bm.lng = rounded
                # Only `category_id` (and `coords`, if the rounding actually
                # moved the point) is this write's doing. Stamping the whole
                # record would let a drag-and-drop out-vote a rename the other
                # Mac has not synced yet.
                changed = {"category_id"} | ({"coords"} if coords_changed else set())
                stamp_units(bm, changed, now, BOOKMARK_MERGE_UNITS)
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
        """Serialise the entire store — categories, bookmarks AND tombstones —
        to a JSON string.

        Held under _store_lock for the same reason snapshot_export() is: the
        watcher thread reassigns self.store mid-merge, so an unlocked read can
        tear. Callers on the event loop must therefore go through
        asyncio.to_thread (see GET /api/bookmarks/store)."""
        with self._store_lock:
            return self.store.model_dump_json(indent=2)

    def snapshot_export(self) -> dict:
        """Consistent {categories, bookmarks, tombstones} read under _store_lock
        so the rotating backup never captures a torn state mid-_save /
        mid-_watcher_tick. The critical section is just the dict build; the
        caller writes outside.

        ``tombstones`` is NOT optional: a snapshot without deletion history
        resurrects every deleted item when restored against a peer that still
        holds it alive (an item is alive iff no tombstone has
        ``deleted_at >= item.updated_at``). Captured in the same critical
        section as the other two lists so the three cannot tear apart."""
        with self._store_lock:
            return {
                "categories": [c.model_dump(mode="json") for c in self.store.categories],
                "bookmarks": [b.model_dump(mode="json") for b in self.store.bookmarks],
                "tombstones": [t.model_dump(mode="json") for t in self.store.tombstones],
            }

    def _upsert_items(
        self,
        items: list,
        *,
        stamp_now: bool,
        enrich_force: bool,
        resolver: Callable[[Bookmark, Bookmark], Resolution] | None = None,
    ) -> tuple[int, int, int, int]:
        """Upsert bookmark *items* into self.store.bookmarks; the single seed/
        import primitive shared by import_json / import_catalog / force_seed.

        ``stamp_now`` stamps each incoming item's ``updated_at = now()`` via
        force_seed_items so it beats any pre-existing real-timestamp tombstone
        in merge_stores inside _save() (the empty-updated_at pitfall). This is
        a PARAMETER, not a per-path omission — every caller declares whether it
        wants the stamp instead of duplicating the logic.

        For an ADD (id absent) the new item is enriched with ``force=False``
        (fill blanks only) and appended. For an UPDATE (id already present) the
        branch depends on ``resolver``:

        * ``resolver is None`` — the existing record's mutable fields are
          overwritten wholesale and re-stamped with the incoming timestamp.
          This is the import_json / force_seed contract, unchanged.
        * ``resolver`` supplied — it decides per field which value wins
          (domain/catalog_merge.resolve_record), and the live record is
          re-stamped ONLY when the resolution took a value from the catalog or
          the re-enrich rewrote a geo field. An unchanged record keeps its own
          ``updated_at``, so a force-sync cannot out-vote a fresher edit that
          has not yet arrived from the other Mac. The re-stamp is per unit
          (``Resolution.taken``): correcting a name leaves the address reading
          as of whenever the user last edited it.

        ``country_code`` (and its siblings timezone / city / region) is written
        by ``enrich_bookmark`` alone on the resolver path — the catalog never
        assigns it onto an existing record. When the offline resolve comes back
        empty the record simply keeps what it had.

        Caller-owned: validating category_id, appending categories, calling
        _save(), the resurrection stamp, logging, and the return-shape mapping.
        Returns (added, updated, kept_local, conflicts); the last two are always
        0 without a resolver.
        """
        if stamp_now:
            force_seed_items(items, _now_iso())
        existing = {b.id: b for b in self.store.bookmarks}
        added = updated = kept_local = conflicts = 0
        for bm in items:
            bm.lat = round_coord(bm.lat)
            bm.lng = round_coord(bm.lng)
            old = existing.get(bm.id)
            if old is not None:
                if resolver is None:
                    old.name = bm.name
                    old.lat = bm.lat
                    old.lng = bm.lng
                    old.address = bm.address
                    old.category_id = bm.category_id
                    old.country_code = bm.country_code
                    old.updated_at = bm.updated_at
                    # A blind overwrite means every unit is as of now. Leaving
                    # the old per-unit stamps in place would let a peer's older
                    # edit out-rank the value force_seed just wrote, which is
                    # the opposite of what this branch promises.
                    old.field_updated_at = {}
                    enrich_bookmark(old, force=enrich_force)
                else:
                    res = resolver(old, bm)
                    for field, value in res.values.items():
                        setattr(old, field, value)
                    # After the merge, so the geo fields follow whichever
                    # coordinates survived — ours if the user moved the pin,
                    # theirs if the catalog corrected it.
                    enriched = enrich_bookmark(old, force=enrich_force)
                    if res.changed or enriched:
                        # Only the units the catalog actually corrected. An
                        # enrich-only change stamps NO unit: it re-derived the
                        # geo four from coordinates nobody moved, and claiming
                        # `coords` for that would out-vote a real pin move on
                        # the other Mac. The record-level bump still happens,
                        # because that is what carries the record past a
                        # tombstone.
                        stamp_units(
                            old, _units_changed(res.taken),
                            bm.updated_at, BOOKMARK_MERGE_UNITS,
                        )
                    if res.kept:
                        kept_local += 1
                    if res.conflicts:
                        conflicts += 1
                updated += 1
            else:
                enrich_bookmark(bm)
                self.store.bookmarks.append(bm)
                existing[bm.id] = bm
                added += 1
        return added, updated, kept_local, conflicts

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
        new_items = [bm for bm in incoming.bookmarks if bm.id not in existing_bm_ids]
        skipped = len(incoming.bookmarks) - len(new_items)
        for bm in new_items:
            if bm.category_id not in existing_cat_ids:
                bm.category_id = "default"
        imported, _, _, _ = self._upsert_items(new_items, stamp_now=True, enrich_force=False)

        if imported:
            self._save()
        logger.info("Imported %d bookmarks (%d skipped as duplicates)", imported, skipped)
        return {"imported": imported, "skipped": skipped}

    def import_catalog(self, data: str) -> dict:
        """Force-sync from the bundled catalog, resolving each field three ways.

        Differences from :meth:`import_json`:

        * Existing items with catalog ids are **merged per field** against a
          local baseline (the catalog values this machine last applied). A
          field the user never edited takes the catalog's value — that is the
          correction-propagation the Refresh button exists for. A field the
          user did edit keeps the local value; when both sides moved apart the
          local value still wins and the record is reported as a conflict.
          ``country_code`` is not in the merge at all: ``enrich_bookmark``
          owns it, along with timezone / city / region.
        * Every *incoming* item gets ``updated_at = now()``. This is the
          load-bearing detail: locally-deleted catalog entries have a
          tombstone whose ``deleted_at`` is a real ISO timestamp; the
          catalog's incoming ``updated_at`` is empty, so the CRDT
          ``_alive(...)`` check would otherwise let the tombstone win and
          silently kill the import inside ``_save()``. Stamping
          ``updated_at = now()`` flips that contest, resurrecting the
          item. A *live* record is re-stamped only when it genuinely changed
          or when it has to out-vote a tombstone — an unconditional re-stamp
          would make Refresh itself a revert trigger for the other Mac.
        * Local items whose ids are NOT in the catalog are left alone.

        Returns ``{'added': N, 'updated': N, 'resurrected': N,
        'kept_local': N, 'conflicts': N}``. *resurrected* counts incoming ids
        that had a tombstone before this call — in memory OR on disk, since a
        deletion made on the other Mac may not have been reconciled yet.
        *updated* keeps its old meaning (an id collision, changed or not);
        *kept_local* counts records where at least one field was preserved
        over a differing catalog value, and *conflicts* its subset where both
        sides had moved. The tombstones themselves are not removed — the
        ``updated_at > deleted_at`` rule handles the resurrection, and
        the stale tombstones GC out after ``TOMBSTONE_RETENTION_DAYS``.
        """
        if self._catalog_baseline is None:
            # Only a caller that bypassed the composition root can land here.
            # It is not fatal, but it silently disables the local-edit
            # protection, so say so rather than degrade in the dark.
            logger.warning(
                "Catalog sync without a baseline port: every diverged field "
                "reads as a local edit (permanent bootstrap). "
                "Build the manager via bootstrap.factories.make_bookmark_manager."
            )

        try:
            raw = json.loads(data)
            incoming = BookmarkStore(**raw)
        except Exception as exc:
            logger.error("Invalid catalog JSON: %s", exc)
            return {"added": 0, "updated": 0, "resurrected": 0, "kept_local": 0, "conflicts": 0}

        now = _now_iso()
        base_cats, base_bms = self._read_catalog_baseline()
        catalog_ids = {c.id for c in incoming.categories} | {b.id for b in incoming.bookmarks}
        # UNION of the in-memory and the on-disk tombstones. _save() merges
        # against the on-disk copy, so a deletion the other Mac wrote but this
        # process has not reconciled is invisible in self.store.tombstones —
        # and an otherwise-unchanged record, left unstamped by the rule below,
        # would be killed by it inside that same _save(). The same union fixes
        # the `resurrected` count, which memory alone under-reports.
        tomb_ids = {t.id for t in self.store.tombstones}
        tomb_ids |= {t.id for t in self._repo.load_or_empty().tombstones}
        resurrect_ids = catalog_ids & tomb_ids
        resurrected = len(resurrect_ids)

        force_seed_items(incoming.categories, now)
        force_seed_items(incoming.bookmarks, now)

        existing_cats = {c.id: c for c in self.store.categories}
        added_cats = updated_cats = kept_cats = conflict_cats = 0
        for cat in incoming.categories:
            if cat.id in existing_cats:
                old = existing_cats[cat.id]
                res = resolve_record(
                    _baseline_entry(base_cats, cat.id),
                    {f: getattr(old, f) for f in CATEGORY_MERGE_FIELDS},
                    {f: getattr(cat, f) for f in CATEGORY_MERGE_FIELDS},
                    CATEGORY_MERGE_FIELDS,
                )
                for field, value in res.values.items():
                    setattr(old, field, value)
                if res.changed:
                    stamp_units(
                        old, _units_changed(res.taken), now, CATEGORY_MERGE_UNITS,
                    )
                kept_cats += bool(res.kept)
                conflict_cats += bool(res.conflicts)
                updated_cats += 1
            else:
                self.store.categories.append(cat)
                existing_cats[cat.id] = cat
                added_cats += 1

        valid_cat_ids = {c.id for c in self.store.categories}
        for bm in incoming.bookmarks:
            if bm.category_id not in valid_cat_ids:
                bm.category_id = "default"

        def _resolve_bookmark(old: Bookmark, incoming_bm: Bookmark) -> Resolution:
            return resolve_record(
                _baseline_entry(base_bms, incoming_bm.id),
                {f: getattr(old, f) for f in BOOKMARK_MERGE_FIELDS},
                {f: getattr(incoming_bm, f) for f in BOOKMARK_MERGE_FIELDS},
                BOOKMARK_MERGE_FIELDS,
            )

        # incoming.bookmarks already stamped via force_seed_items above, so
        # stamp_now=False here avoids double-stamping; catalog upserts re-resolve
        # geo on coord changes (enrich_force=True).
        added_bms, updated_bms, kept_bms, conflict_bms = self._upsert_items(
            incoming.bookmarks, stamp_now=False, enrich_force=True, resolver=_resolve_bookmark
        )

        # Resurrection intent, the third re-stamp condition: an id under a
        # tombstone must out-vote it even when the merge left every field
        # alone. Records that came through the ADD branch already carry `now`.
        if resurrect_ids:
            for item in (*self.store.categories, *self.store.bookmarks):
                if item.id in resurrect_ids:
                    item.updated_at = now

        self._save()
        self._write_catalog_baseline(incoming, raw, now)
        logger.info(
            "Catalog sync: +%d added, %d updated, %d resurrected, %d kept local, %d conflicts",
            added_cats + added_bms, updated_cats + updated_bms, resurrected,
            kept_cats + kept_bms, conflict_cats + conflict_bms,
        )
        return {
            "added": added_cats + added_bms,
            "updated": updated_cats + updated_bms,
            "resurrected": resurrected,
            "kept_local": kept_cats + kept_bms,
            "conflicts": conflict_cats + conflict_bms,
        }

    def _read_catalog_baseline(self) -> tuple[dict, dict]:
        """The catalog values this machine last applied, as (categories, bookmarks).

        Both come back empty when there is no baseline port, no file yet, or a
        file this build cannot make sense of — all three mean "bootstrap",
        which resolve_record spells as ``base := theirs`` per field (§4.7).
        """
        payload = self._catalog_baseline.read() if self._catalog_baseline is not None else None
        if not isinstance(payload, dict):
            return {}, {}
        sections = []
        for key in ("categories", "bookmarks"):
            section = payload.get(key)
            sections.append(section if isinstance(section, dict) else {})
        return sections[0], sections[1]

    def _write_catalog_baseline(self, incoming: BookmarkStore, raw: dict, applied_at: str) -> None:
        """Record what was just applied, so the next sync can tell a catalog
        correction from a local edit. Only the merged fields are stored —
        created_at / last_used_at / the geo fields are not the catalog's.

        ``compiled_at`` is diagnostic only (which catalog version seeded this
        baseline); it is never used as a change-detection key, because a
        same-day catalog edit would not bump it.
        """
        if self._catalog_baseline is None:
            return
        meta = raw.get("_meta") if isinstance(raw, dict) else None
        compiled_at = meta.get("compiled_at", "") if isinstance(meta, dict) else ""
        self._catalog_baseline.write({
            "_meta": {
                "format_version": 1,
                "compiled_at": compiled_at,
                "applied_at": applied_at,
            },
            "categories": {
                c.id: {f: getattr(c, f) for f in CATEGORY_MERGE_FIELDS}
                for c in incoming.categories
            },
            "bookmarks": {
                b.id: {f: getattr(b, f) for f in BOOKMARK_MERGE_FIELDS}
                for b in incoming.bookmarks
            },
        })

    def force_seed(self, items: list) -> dict:
        """Upsert a list of Bookmark items, stamping each with the current time.

        Uses ``force_seed_items`` to guarantee every item's ``updated_at``
        beats any pre-existing real-timestamp tombstone in the CRDT merge —
        encoding the empty-updated_at pitfall so callers don't have to know
        about it.

        This is the public force-seed entry point (e.g. for a future
        bulk/catalog-seed caller). ``import_catalog`` does its own upsert
        (with enrich + a richer return shape) and calls the shared
        ``force_seed_items`` primitive directly rather than this method.

        Returns ``{'added': N, 'updated': N}`` where *added* counts items
        that were new to the store and *updated* counts items that replaced
        an existing entry.
        """
        # No resolver: this path keeps the blind-overwrite update branch. A
        # future catalog-shaped caller that must respect local edits should
        # pass one, the way import_catalog does (R6).
        added, updated, _, _ = self._upsert_items(items, stamp_now=True, enrich_force=True)
        self._save()
        return {"added": added, "updated": updated}
