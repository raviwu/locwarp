"""A backup must carry deletion history.

A snapshot that omits tombstones resurrects deleted items the moment it is
restored against a peer copy that still holds them alive. Regression cover for
the 2026-09-18 store-loss incident: the recovered live ``bookmarks.json`` held
13 tombstones while the snapshot-derived restore held 0.

Every manager here gets explicit tmp path providers — never rely on the autouse
isolation guard alone for a test that writes stores.
"""

import json
from datetime import datetime, timezone

import pytest

import domain.backup as backup
from bootstrap.factories import make_bookmark_manager, make_route_manager
from merge_backup import restore_combined_snapshot
from models.schemas import BookmarkStore, Coordinate, RouteStore, SavedRoute


@pytest.fixture
def managers(tmp_path):
    bm = make_bookmark_manager(
        path_provider=lambda: tmp_path / "bookmarks.json",
        baseline_path_provider=lambda: tmp_path / "catalog_baseline.json",
    )
    rm = make_route_manager(path_provider=lambda: tmp_path / "routes.json")
    return bm, rm


def _snapshot(bm, rm):
    """The combined payload exactly as the lifespan loop assembles it."""
    return backup.build_snapshot(
        bm.snapshot_export(),
        rm.snapshot_export(),
        [],
        datetime.now(timezone.utc),
        "test",
    )


def _route(name="R"):
    return SavedRoute(
        name=name,
        waypoints=[Coordinate(lat=1.0, lng=1.0), Coordinate(lat=2.0, lng=2.0)],
        profile="walking",
    )


def test_restore_does_not_resurrect_a_deleted_bookmark(managers, tmp_path):
    bm, rm = managers
    cat = bm.create_category(name="C")
    keep = bm.create_bookmark(name="keep", lat=1.0, lng=2.0, category_id=cat.id)
    doomed = bm.create_bookmark(name="doomed", lat=3.0, lng=4.0, category_id=cat.id)

    # A peer machine's copy, captured while `doomed` was still alive.
    peer_path = tmp_path / "peer_bookmarks.json"
    peer_path.write_text(
        BookmarkStore(
            categories=list(bm.store.categories), bookmarks=[keep, doomed]
        ).model_dump_json(indent=2)
    )

    assert bm.delete_bookmark(doomed.id) is True
    snap = _snapshot(bm, rm)

    restore_combined_snapshot(snap, peer_path, tmp_path / "peer_routes.json")

    restored = BookmarkStore(**json.loads(peer_path.read_text()))
    alive = {b.id for b in restored.bookmarks}
    assert keep.id in alive
    assert doomed.id not in alive, (
        "deleted bookmark resurrected — the snapshot carried no tombstone"
    )


def test_restore_does_not_resurrect_a_deleted_route(managers, tmp_path):
    bm, rm = managers
    keep = rm.create_route(_route("keep"))
    doomed = rm.create_route(_route("doomed"))

    peer_path = tmp_path / "peer_routes.json"
    peer_path.write_text(
        RouteStore(
            categories=list(rm.store.categories), routes=[keep, doomed]
        ).model_dump_json(indent=2)
    )

    assert rm.delete_route(doomed.id) is True
    snap = _snapshot(bm, rm)

    restore_combined_snapshot(snap, tmp_path / "peer_bookmarks.json", peer_path)

    restored = RouteStore(**json.loads(peer_path.read_text()))
    alive = {r.id for r in restored.routes}
    assert keep.id in alive
    assert doomed.id not in alive, (
        "deleted route resurrected — the snapshot carried no tombstone"
    )


def test_snapshot_export_carries_exactly_the_live_tombstones(managers):
    bm, rm = managers
    cat = bm.create_category(name="C")
    b = bm.create_bookmark(name="b", lat=1.0, lng=2.0, category_id=cat.id)
    bm.delete_bookmark(b.id)
    r = rm.create_route(_route())
    rm.delete_route(r.id)

    assert bm.snapshot_export()["tombstones"] == [
        t.model_dump(mode="json") for t in bm.store.tombstones
    ]
    assert rm.snapshot_export()["tombstones"] == [
        t.model_dump(mode="json") for t in rm.store.tombstones
    ]


def test_snapshot_payload_stays_json_serializable(managers):
    """Guards the mode="json" requirement — a raw Tombstone model or a
    datetime would make safe_write_json choke at backup time."""
    bm, rm = managers
    cat = bm.create_category(name="C")
    b = bm.create_bookmark(name="b", lat=1.0, lng=2.0, category_id=cat.id)
    bm.delete_bookmark(b.id)
    json.dumps(_snapshot(bm, rm))


def test_restore_suppresses_a_live_item_with_an_empty_updated_at(managers, tmp_path):
    """The repo's documented pitfall: ``updated_at = ""`` always loses to a
    real-timestamp tombstone, so a legacy peer record must also stay deleted."""
    bm, rm = managers
    cat = bm.create_category(name="C")
    doomed = bm.create_bookmark(name="doomed", lat=3.0, lng=4.0, category_id=cat.id)

    legacy = doomed.model_copy(update={"updated_at": ""})
    peer_path = tmp_path / "peer_bookmarks.json"
    peer_path.write_text(
        BookmarkStore(
            categories=list(bm.store.categories), bookmarks=[legacy]
        ).model_dump_json(indent=2)
    )

    bm.delete_bookmark(doomed.id)
    restore_combined_snapshot(_snapshot(bm, rm), peer_path, tmp_path / "peer_routes.json")

    restored = BookmarkStore(**json.loads(peer_path.read_text()))
    assert all(b.id != doomed.id for b in restored.bookmarks)


@pytest.fixture
def route_client(tmp_path, monkeypatch):
    """TestClient with the route store redirected to tmp_path."""
    monkeypatch.setattr("services.route_store.ROUTES_FILE", tmp_path / "routes.json")
    monkeypatch.setattr("services.route_store._CONFIG_DEFAULT_ROUTES_FILE", object())
    import main
    from fastapi.testclient import TestClient

    main.app_state.route_manager = make_route_manager()
    return TestClient(main.app)


def test_get_route_saved_export_still_carries_tombstones(route_client):
    """The route leg's tombstone fidelity is an accidental side effect of
    export_json() using model_dump_json(). Pin it, so a future refactor to a
    hand-built dict cannot silently undo it — that is exactly how the bookmark
    side lost its tombstones."""
    created = route_client.post(
        "/api/route/saved",
        json={
            "name": "R",
            "waypoints": [{"lat": 1.0, "lng": 1.0}, {"lat": 2.0, "lng": 2.0}],
            "profile": "walking",
        },
    )
    assert created.status_code == 200
    rid = created.json()["id"]
    assert route_client.delete(f"/api/route/saved/{rid}").status_code == 200

    store = RouteStore(**route_client.get("/api/route/saved/export").json())
    assert rid in {t.id for t in store.tombstones}
