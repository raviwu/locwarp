"""The autouse _isolate_real_data_paths guard (conftest.py) must redirect
RECENT_PLACES_FILE to the per-test tmp dir AND reset services.recent._singleton,
so a recent-places write can never touch the user's real ~/.locwarp file and one
test's singleton cannot leak into the next. RECENT_PLACES_FILE is captured at
import time inside services.recent, so patching config alone is not enough — the
guard must also clear the singleton so get_manager() rebuilds against the patch.
"""
from __future__ import annotations

from pathlib import Path


def test_recent_places_file_is_redirected_to_tmp(tmp_path):
    # The autouse guard redirected RECENT_PLACES_FILE into this test's tmp_path.
    import services.recent as recent
    assert Path(recent.RECENT_PLACES_FILE) == tmp_path / "recent_places.json"


def test_recent_singleton_is_reset_and_writes_into_tmp(tmp_path):
    import services.recent as recent
    # Guard must have reset the singleton so a fresh manager binds the patched
    # path; build it and push an entry.
    assert recent._singleton is None, "guard must reset _singleton before each test"
    mgr = recent.get_manager()
    mgr.push(lat=10.0, lng=20.0, kind="teleport", name="X")
    # The entry must land in the patched (tmp) file, proving real data is safe.
    written = Path(recent.RECENT_PLACES_FILE)
    assert written == tmp_path / "recent_places.json"
    assert written.exists()
