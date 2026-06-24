"""Shared file-watcher binding: the start/stop/debounce state machine that
BookmarkManager and RouteManager duplicated.

Owns ONLY the watchdog plumbing (schedule/unschedule on the shared Observer)
and the threading.Timer(0.5) debounce. It does NOT own merge/mtime/reconcile
logic — that stays on each manager, injected here as the ``on_reconcile``
callback (the manager's own _watcher_tick). path_accessor is called fresh on
every fs event so a path rebind (cloud-sync folder change) is honoured.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEventHandler
from watchdog.observers.api import ObservedWatch

from services.file_watcher import schedule as _schedule, unschedule as _unschedule

logger = logging.getLogger(__name__)


class FileWatchBinding:
    def __init__(
        self,
        path_accessor: Callable[[], Path],
        on_reconcile: Callable[[], None],
        *,
        debounce_s: float = 0.5,
    ) -> None:
        self._path_accessor = path_accessor
        self._on_reconcile = on_reconcile
        self._debounce_s = debounce_s
        self._watch: ObservedWatch | None = None
        self._timer: threading.Timer | None = None

    def start(self) -> None:
        self.stop()
        path = self._path_accessor()
        parent = path.parent
        if not parent.exists():
            logger.warning("Watch folder does not exist; watcher not started: %s", parent)
            return
        binding = self

        class _Handler(FileSystemEventHandler):
            def on_modified(self, event):
                if event.is_directory:
                    return
                if Path(event.src_path) != binding._path_accessor():
                    return
                binding._schedule()

            on_created = on_modified

            def on_moved(self, event):
                if event.is_directory:
                    return
                target = binding._path_accessor()
                if Path(event.src_path) != target and Path(getattr(event, "dest_path", "")) != target:
                    return
                binding._schedule()

        self._watch = _schedule(_Handler(), parent)
        logger.info("Watcher scheduled on %s", parent)

    def stop(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        if self._watch is not None:
            _unschedule(self._watch)
            self._watch = None

    def _schedule(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
        self._timer = threading.Timer(self._debounce_s, self._on_reconcile)
        self._timer.daemon = True
        self._timer.start()
