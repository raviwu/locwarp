"""RecentPlacesManager: manual entries and route stops share one file but not
one budget. These tests pin the invariants the old single-list implementation
could not hold — a manual push truncating route stops away, and a manual
teleport deduping into a leading route stop (which also broke the frontend's
reverse-geocode name backfill)."""
from __future__ import annotations

import pytest


class _FakeTime:
    """Stand-in for the `time` module inside services.recent."""

    def __init__(self, values):
        self._it = iter(values)

    def time(self):
        return next(self._it)


@pytest.fixture
def mgr():
    import services.recent as recent
    # The autouse conftest guard redirected RECENT_PLACES_FILE and reset the
    # module singleton, so this builds a manager bound to the per-test tmp file.
    assert recent._singleton is None
    return recent.get_manager()


def test_manual_push_does_not_dedupe_into_a_leading_route_stop(mgr):
    mgr.push_route_stop(25.0, 121.0)
    mgr.push(25.0, 121.0, "teleport")
    entries = mgr.list()
    kinds = [e["kind"] for e in entries]
    assert kinds.count("teleport") == 1
    assert kinds.count("route_stop") == 1
    route = next(e for e in entries if e["kind"] == "route_stop")
    assert route["visit_count"] == 1


def test_manual_name_backfill_survives_a_leading_route_stop(mgr):
    # Mirrors useRecentPlaces' push-twice flow: unnamed push, then a second
    # push carrying the reverse-geocoded name. A route stop inserted between
    # them must not steal the backfill.
    mgr.push(35.0, 139.0, "teleport")
    mgr.push_route_stop(10.0, 20.0)
    mgr.push(35.0, 139.0, "teleport", "Shibuya")
    manual = [e for e in mgr.list() if e["kind"] == "teleport"]
    assert len(manual) == 1
    assert manual[0]["name"] == "Shibuya"
    route = next(e for e in mgr.list() if e["kind"] == "route_stop")
    assert route["name"] == ""


def test_route_stop_dedupes_globally_and_counts_visits(mgr):
    mgr.push_route_stop(25.0, 121.0)
    mgr.push_route_stop(25.1, 121.1)
    mgr.push_route_stop(25.0, 121.0)  # back to the first stop on the next lap
    routes = [e for e in mgr.list() if e["kind"] == "route_stop"]
    assert len(routes) == 2
    assert routes[0]["lat"] == 25.0
    assert routes[0]["visit_count"] == 2
    assert routes[1]["visit_count"] == 1


def test_route_stops_never_evict_manual_entries(mgr):
    for i in range(20):
        mgr.push(1.0 + i, 2.0 + i, "teleport")
    for i in range(40):  # more than MAX_ROUTE_STOP_ENTRIES
        mgr.push_route_stop(40.0 + i * 0.5, 100.0 + i * 0.5)
    kinds = [e["kind"] for e in mgr.list()]
    assert kinds.count("teleport") == 20
    assert kinds.count("route_stop") == 30


def test_manual_push_never_evicts_route_stops(mgr):
    """The old single-list [:MAX_ENTRIES] slice destroyed 11 route stops here."""
    for i in range(30):
        mgr.push_route_stop(40.0 + i * 0.5, 100.0 + i * 0.5)
    mgr.push(1.0, 2.0, "teleport")
    kinds = [e["kind"] for e in mgr.list()]
    assert kinds.count("route_stop") == 30
    assert kinds.count("teleport") == 1


def test_list_is_ts_descending(mgr, monkeypatch):
    import services.recent as recent
    monkeypatch.setattr(recent, "time", _FakeTime([100, 200, 300]))
    mgr.push(1.0, 2.0, "teleport")
    mgr.push_route_stop(40.0, 100.0)
    mgr.push(5.0, 6.0, "search")
    assert [e["ts"] for e in mgr.list()] == [300, 200, 100]


def test_manual_entries_carry_no_visit_count(mgr):
    entry = mgr.push(1.0, 2.0, "teleport")
    assert "visit_count" not in entry


def test_push_rejects_the_route_stop_kind(mgr):
    with pytest.raises(ValueError):
        mgr.push(1.0, 2.0, "route_stop")


def test_clear_empties_both_classes(mgr):
    mgr.push(1.0, 2.0, "teleport")
    mgr.push_route_stop(40.0, 100.0)
    mgr.clear()
    assert mgr.list() == []


def test_legacy_manual_only_file_loads_and_caps(monkeypatch):
    import services.recent as recent
    from pathlib import Path
    from services.json_safe import safe_write_json

    legacy = [
        {"lat": 1.0 + i, "lng": 2.0 + i, "kind": "teleport", "name": "", "ts": 9000 - i}
        for i in range(25)
    ]
    safe_write_json(Path(recent.RECENT_PLACES_FILE), legacy)
    monkeypatch.setattr(recent, "_singleton", None, raising=False)

    entries = recent.get_manager().list()
    assert len(entries) == 20
    assert all(e["kind"] == "teleport" for e in entries)
    assert "visit_count" not in entries[0]


def test_load_caps_each_class_independently(monkeypatch):
    import services.recent as recent
    from pathlib import Path
    from services.json_safe import safe_write_json

    rows = [
        {"lat": 1.0 + i, "lng": 2.0 + i, "kind": "teleport", "name": "", "ts": 9000 - i}
        for i in range(25)
    ] + [
        {"lat": 40.0 + i * 0.5, "lng": 100.0 + i * 0.5, "kind": "route_stop",
         "name": "", "ts": 8000 - i, "visit_count": 3}
        for i in range(40)
    ]
    safe_write_json(Path(recent.RECENT_PLACES_FILE), rows)
    monkeypatch.setattr(recent, "_singleton", None, raising=False)

    kinds = [e["kind"] for e in recent.get_manager().list()]
    assert kinds.count("teleport") == 20
    assert kinds.count("route_stop") == 30


def test_record_route_stop_never_raises(monkeypatch):
    import services.recent as recent

    class Boom:
        def push_route_stop(self, *a, **k):
            raise RuntimeError("disk on fire")

    monkeypatch.setattr(recent, "get_manager", lambda: Boom())
    recent.record_route_stop(1.0, 2.0)  # must not raise


@pytest.mark.parametrize(
    "event_type,data,udid,primary,expected",
    [
        ("stop_reached", {"lat": 1.0, "lng": 2.0, "origin": False}, "a", "a", True),
        ("stop_reached", {"lat": 1.0, "lng": 2.0}, "a", "a", True),
        ("stop_reached", {"lat": 1.0, "lng": 2.0, "origin": True}, "a", "a", False),
        ("stop_reached", {"lat": 1.0, "lng": 2.0, "origin": False}, "b", "a", False),
        ("stop_reached", {"lat": 1.0, "lng": 2.0, "origin": False}, "a", None, False),
        ("stop_reached", {"origin": False}, "a", "a", False),
        ("position_update", {"lat": 1.0, "lng": 2.0}, "a", "a", False),
    ],
)
def test_should_record_stop(event_type, data, udid, primary, expected):
    import services.recent as recent
    assert recent.should_record_stop(event_type, data, udid, primary) is expected
