"""Process-wide filesystem watcher.

Both BookmarkManager and RouteManager need to watch ``~/.locwarp/`` (or
``<sync_folder>/`` when cloud sync is on) for external file changes. If
each manager owns its own ``watchdog.Observer``, macOS fsevents raises
``RuntimeError: Cannot add watch ... already scheduled`` the second time
the same directory is scheduled within the same process, and the
second emitter's thread dies silently — so for example the route
watcher never fires its callback in production.

This module exposes a single, lazily-started Observer that the managers
schedule onto. ``watchdog.observers.api.BaseObserver.schedule`` reuses
the existing emitter for a given (path, recursive) pair and only adds
the handler to its handler list, which means multiple handlers can
coexist on the same directory.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver, ObservedWatch

logger = logging.getLogger(__name__)

_observer: BaseObserver | None = None
_lock = threading.Lock()


def _get_or_create_observer() -> BaseObserver:
    """Return the singleton Observer, starting it if needed."""
    global _observer
    with _lock:
        if _observer is None:
            _observer = Observer()
            _observer.start()
            logger.info("Shared file_watcher Observer started")
        return _observer


def schedule(handler: FileSystemEventHandler, path: Path) -> ObservedWatch:
    """Schedule *handler* on the shared Observer watching *path* (non-recursive).

    Returns the ``ObservedWatch`` so the caller can later unschedule it.
    """
    observer = _get_or_create_observer()
    return observer.schedule(handler, str(path), recursive=False)


def unschedule(watch: ObservedWatch | None) -> None:
    """Detach a previously-scheduled watch.

    Safe to call with None or with a watch that is already detached.
    """
    if watch is None:
        return
    observer = _observer
    if observer is None:
        return
    try:
        observer.unschedule(watch)
    except (KeyError, ValueError):
        # Already detached; happens when stop_watcher races with shutdown.
        pass


def shutdown() -> None:
    """Stop and clear the shared Observer.

    Called from the FastAPI lifespan shutdown path so the Observer thread
    exits cleanly with the application.
    """
    global _observer
    with _lock:
        if _observer is None:
            return
        try:
            _observer.stop()
            _observer.join(timeout=2.0)
        except Exception:
            logger.exception("Failed to stop shared file_watcher observer")
        _observer = None
