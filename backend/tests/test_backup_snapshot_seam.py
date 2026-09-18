"""The manager snapshot_export() seams the rotating backup reads from."""
from bootstrap.factories import make_bookmark_manager, make_route_manager


def test_bookmark_snapshot_export_shape():
    bm = make_bookmark_manager()
    cat = bm.create_category(name="C")
    bm.create_bookmark(name="b", lat=1.0, lng=2.0, category_id=cat.id)
    doomed = bm.create_bookmark(name="doomed", lat=3.0, lng=4.0, category_id=cat.id)
    bm.delete_bookmark(doomed.id)
    snap = bm.snapshot_export()
    assert set(snap) == {"categories", "bookmarks", "tombstones"}
    assert len(snap["bookmarks"]) == 1
    assert snap["bookmarks"][0]["name"] == "b"
    # Deletion history travels with the snapshot — without it a restore
    # resurrects `doomed` on any peer that still holds it.
    assert [t["id"] for t in snap["tombstones"]] == [doomed.id]
    # Must be JSON-serializable (mode="json") so safe_write_json never chokes.
    import json

    json.dumps(snap)


def test_route_snapshot_export_shape():
    rm = make_route_manager()
    snap = rm.snapshot_export()
    assert set(snap) == {"categories", "routes", "tombstones"}
    import json

    json.dumps(snap)
