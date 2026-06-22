"""Regression: _watcher_tick firing from a real second (Timer-daemon) thread
DURING a _save call must not lose a created bookmark and must not raise.

Without the _store_lock, the two self.store rebinds + file writes interleave
and an item can vanish.  The lock serialises them.

HOW THE OVERLAP IS FORCED
--------------------------
A threading.Barrier(2) is used so the watcher thread and the main thread
enter their respective critical sections at the same time:

  Main thread                     Watcher thread
  ─────────────────────────────   ─────────────────────────────────
  create_bookmark(...)            hammer_watcher() loop iteration N
    → appends to store.bookmarks    → barrier.wait()  ← both unblock
    → calls _save()                 → _watcher_tick() called
        → reads disk                   → reads disk
        → merge_stores              (race window without the lock)
        → writes file
        → self.store = ...             → self.store = ...  (lost-write
                                                             without lock)

The barrier is injected by monkeypatching _watcher_tick to call
barrier.wait() at its entry before proceeding with the real tick.  This
guarantees at least barrier_hits synchronised overlaps during the 200-
iteration loop, so the test is NOT vacuous or relying on lucky timing.
"""
import threading
import time

import pytest

from bootstrap.factories import make_bookmark_manager


def _make_manager(tmp_path, monkeypatch):
    """Point the manager at an isolated temp bookmarks file."""
    monkeypatch.setattr("services.bookmarks.BOOKMARKS_FILE", tmp_path / "bookmarks.json")
    monkeypatch.setattr(
        "services.bookmarks._CONFIG_DEFAULT_BOOKMARKS_FILE",
        tmp_path / "bookmarks.json",
    )
    mgr = make_bookmark_manager()
    return mgr, tmp_path / "bookmarks.json"


def test_watcher_tick_during_save_loses_nothing(tmp_path, monkeypatch):
    """Stress: 200 creates on main thread + 200 watcher ticks on a second thread.

    A barrier forces at least some of these to overlap in their critical
    sections.  After both threads finish, every created bookmark id must
    still be present in the on-disk file.
    """
    mgr, path = _make_manager(tmp_path, monkeypatch)

    cat = mgr.create_category(name="Race", color="#abc")
    cat_id = cat.id

    ROUNDS = 200
    # Barrier with 2 parties ensures the watcher thread and the main thread
    # reach the barrier concurrently before proceeding.  We set a generous
    # timeout so the test does not hang if one side gets scheduled late.
    barrier = threading.Barrier(2, timeout=5)

    errors: list[Exception] = []

    # Wrap _watcher_tick so we can force the overlap at the barrier.
    original_tick = mgr._watcher_tick

    tick_call_count = 0

    def _barrier_tick():
        nonlocal tick_call_count
        try:
            barrier.wait()  # synchronise with the main thread's create_bookmark
        except threading.BrokenBarrierError:
            return  # main thread timed out on its side — stop
        try:
            original_tick()
        except Exception as exc:
            errors.append(exc)
        tick_call_count += 1

    mgr._watcher_tick = _barrier_tick

    # The watcher thread: call _barrier_tick ROUNDS times.
    def hammer_watcher():
        for _ in range(ROUNDS):
            _barrier_tick()

    watcher_thread = threading.Thread(target=hammer_watcher, daemon=True)
    watcher_thread.start()

    created_ids: list[str] = []
    for i in range(ROUNDS):
        try:
            barrier.wait()  # synchronise: both threads hit the barrier together
        except threading.BrokenBarrierError:
            break  # watcher thread already stopped
        bm = mgr.create_bookmark(
            name=f"bm{i}", lat=25.0 + i * 0.001, lng=121.0 + i * 0.001, category_id=cat_id
        )
        created_ids.append(bm.id)

    watcher_thread.join(timeout=15)
    assert not watcher_thread.is_alive(), "watcher thread did not finish in time"
    assert errors == [], f"watcher tick raised exceptions: {errors}"

    # Reload from disk and verify no bookmark was lost.
    import json
    data = json.loads(path.read_text())
    on_disk_ids = {b["id"] for b in data.get("bookmarks", [])}
    missing = [bid for bid in created_ids if bid not in on_disk_ids]
    assert missing == [], (
        f"{len(missing)} bookmark(s) lost to concurrent watcher write: {missing[:5]!r}"
    )
