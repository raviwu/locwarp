"""The manager snapshot_export() seams the rotating backup reads from."""
from bootstrap.factories import make_bookmark_manager, make_route_manager


def test_bookmark_snapshot_export_shape():
    bm = make_bookmark_manager()
    cat = bm.create_category(name="C")
    bm.create_bookmark(name="b", lat=1.0, lng=2.0, category_id=cat.id)
    snap = bm.snapshot_export()
    assert set(snap) == {"categories", "bookmarks"}
    assert len(snap["bookmarks"]) == 1
    assert snap["bookmarks"][0]["name"] == "b"
    # Must be JSON-serializable (mode="json") so safe_write_json never chokes.
    import json

    json.dumps(snap)


def test_route_snapshot_export_shape():
    rm = make_route_manager()
    snap = rm.snapshot_export()
    assert set(snap) == {"categories", "routes"}
    import json

    json.dumps(snap)
