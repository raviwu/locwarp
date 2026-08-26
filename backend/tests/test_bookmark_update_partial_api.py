"""HTTP-level tests for the partial-update ``PUT /api/bookmarks/{id}`` (fix F).

The route takes a ``BookmarkUpdate`` body whose fields are all optional, so an
omitted key means "leave this field alone" instead of arriving as ``Bookmark``'s
concrete schema default (``address=""``, ``category_id="default"``,
``country_code=""``) and blanking a field the client never mentioned.

The same file also pins the no-op write guard: a PUT whose values all already
match the stored record writes nothing at all — ``updated_at`` included — so a
Save that changes nothing cannot out-vote a fresher, still-unsynced edit on the
other Mac under whole-record LWW.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def store_path(tmp_path):
    return tmp_path / "bookmarks.json"


@pytest.fixture
def client(tmp_path, monkeypatch):
    """TestClient with the bookmark store redirected to tmp_path.

    Same shape as test_bookmarks_api.py's `client` fixture.
    """
    monkeypatch.setattr(
        "services.bookmarks.BOOKMARKS_FILE",
        tmp_path / "bookmarks.json",
    )
    import main
    from bootstrap.factories import make_bookmark_manager
    main.app_state.bookmark_manager = make_bookmark_manager()
    return TestClient(main.app)


def _create(client, **over) -> dict:
    payload = {
        "name": "Taipei 101",
        "lat": 25.0339,
        "lng": 121.5645,
        "address": "信義路五段 7 號",
        "category_id": "default",
    }
    payload.update(over)
    resp = client.post("/api/bookmarks", json=payload)
    assert resp.status_code == 200
    return resp.json()


def _fetch(client, bm_id: str) -> dict:
    resp = client.get("/api/bookmarks")
    assert resp.status_code == 200
    return next(b for b in resp.json()["bookmarks"] if b["id"] == bm_id)


def test_put_with_only_a_name_leaves_every_other_field_alone(client):
    """The rename the Edit dialog sends after fix F: one key on the wire."""
    created = _create(client)

    resp = client.put(f"/api/bookmarks/{created['id']}", json={"name": "renamed"})
    assert resp.status_code == 200
    body = resp.json()

    assert body["name"] == "renamed"
    assert body["address"] == "信義路五段 7 號"
    assert body["category_id"] == "default"
    assert body["country_code"] == created["country_code"]
    assert body["lat"] == created["lat"]
    assert body["lng"] == created["lng"]


def test_put_with_an_explicit_empty_address_still_clears_it(client):
    """"Omitted" and "explicitly blank" must stay distinguishable: a client
    that really wants to clear the address sends the empty string."""
    created = _create(client)

    resp = client.put(f"/api/bookmarks/{created['id']}", json={"address": ""})
    assert resp.status_code == 200
    assert resp.json()["address"] == ""
    assert resp.json()["name"] == "Taipei 101"


def test_put_with_an_explicit_null_leaves_the_field_alone(client):
    """A JSON ``null`` is the service's documented "do not modify" value, so it
    behaves like an omission rather than clearing the field."""
    created = _create(client)

    resp = client.put(f"/api/bookmarks/{created['id']}", json={"address": None})
    assert resp.status_code == 200
    assert resp.json()["address"] == "信義路五段 7 號"


def test_put_with_only_coordinates_re_resolves_geo_and_keeps_the_name(client):
    """A pin drag sends lat/lng only; the geo fields follow the coordinates."""
    created = _create(client)
    assert created["country_code"] == "tw"

    resp = client.put(
        f"/api/bookmarks/{created['id']}",
        json={"lat": 35.6762, "lng": 139.6503},  # Tokyo
    )
    assert resp.status_code == 200
    body = resp.json()

    assert body["lat"] == 35.6762
    assert body["country_code"] == "jp"
    assert body["timezone"] == "Asia/Tokyo"
    assert body["name"] == "Taipei 101"
    assert body["address"] == "信義路五段 7 號"


def test_zero_coordinates_are_applied_not_treated_as_omitted(client):
    """0.0 is a legal coordinate (Null Island) and must not read as absent —
    the route filters on presence, never on truthiness."""
    created = _create(client)

    resp = client.put(f"/api/bookmarks/{created['id']}", json={"lat": 0.0, "lng": 0.0})
    assert resp.status_code == 200
    body = resp.json()
    assert body["lat"] == 0.0
    assert body["lng"] == 0.0


def test_put_with_an_empty_body_writes_nothing(client):
    """"Open the Edit dialog and press Save without changing anything" now
    sends a literal {} — it must leave the record byte-identical."""
    created = _create(client)
    before = _fetch(client, created["id"])

    resp = client.put(f"/api/bookmarks/{created['id']}", json={})
    assert resp.status_code == 200
    assert resp.json() == before
    assert _fetch(client, created["id"]) == before


def test_put_resending_the_stored_values_skips_the_save(client, store_path):
    """The no-op guard skips ``_save()`` itself, not just the re-stamp: a write
    with a fresh stamp would beat the other Mac's un-synced edit whole."""
    created = _create(client)
    before = _fetch(client, created["id"])
    bytes_before = store_path.read_bytes()
    mtime_before = store_path.stat().st_mtime_ns

    resp = client.put(
        f"/api/bookmarks/{created['id']}",
        json={
            "name": before["name"],
            "lat": before["lat"],
            "lng": before["lng"],
            "address": before["address"],
            "category_id": before["category_id"],
            "country_code": before["country_code"],
        },
    )
    assert resp.status_code == 200
    assert resp.json()["updated_at"] == before["updated_at"]
    assert store_path.read_bytes() == bytes_before
    assert store_path.stat().st_mtime_ns == mtime_before


def test_put_unknown_id_is_404(client):
    resp = client.put("/api/bookmarks/no-such-id", json={"name": "x"})
    assert resp.status_code == 404


def test_full_body_with_one_changed_field_still_bumps_updated_at(client):
    """Regression: the guard fires on "nothing differs", not on "a full body"."""
    created = _create(client)

    resp = client.put(
        f"/api/bookmarks/{created['id']}",
        json={
            "name": "renamed",
            "lat": created["lat"],
            "lng": created["lng"],
            "address": created["address"],
            "category_id": created["category_id"],
            "country_code": created["country_code"],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "renamed"
    assert body["updated_at"] > created["updated_at"]


# ── Categories (F2) ───────────────────────────────────────
#
# PUT /api/bookmarks/categories/{cat_id} had the identical defect: a body
# parsed as BookmarkCategory fills color="#6c8cff", start_date="" and
# end_date="" for every key the client omitted. The route also validates the
# date pair, so the all-Optional body forced _validate_date_range to learn
# what "not supplied" means — None, which it treats exactly like "".


def _create_category(client, **over) -> dict:
    payload = {
        "name": "Sanga",
        "color": "#ef4444",
        "start_date": "2026-02-06",
        "end_date": "2026-06-07",
    }
    payload.update(over)
    resp = client.post("/api/bookmarks/categories", json=payload)
    assert resp.status_code == 200
    return resp.json()


def test_validate_date_range_treats_none_like_an_empty_string():
    """None reaches the validator from every key the partial body omits.

    Before F2 the signature was ``(str, str)`` and only ``""`` short-circuited,
    so a None fell through to ``_ISO_DATE_RE.match(None)`` — a TypeError, i.e.
    a 500 on every request that omitted a date.
    """
    from api.bookmarks import _validate_date_range

    _validate_date_range(None, None)
    _validate_date_range(None, "")
    _validate_date_range("2026-02-06", None)
    _validate_date_range(None, "2026-06-07")


def test_put_category_with_only_a_name_leaves_color_and_dates_alone(client):
    """The rename the category dialog sends after F2: one key on the wire."""
    cat = _create_category(client)

    resp = client.put(f"/api/bookmarks/categories/{cat['id']}", json={"name": "Sanga 2"})
    assert resp.status_code == 200
    body = resp.json()

    assert body["name"] == "Sanga 2"
    assert body["color"] == "#ef4444"
    assert body["start_date"] == "2026-02-06"
    assert body["end_date"] == "2026-06-07"


def test_put_category_with_only_a_color_leaves_the_name_alone(client):
    cat = _create_category(client)

    resp = client.put(f"/api/bookmarks/categories/{cat['id']}", json={"color": "#22c55e"})
    assert resp.status_code == 200
    body = resp.json()

    assert body["color"] == "#22c55e"
    assert body["name"] == "Sanga"
    assert body["start_date"] == "2026-02-06"


def test_put_category_explicit_empty_dates_still_clear_them(client):
    """Omission means "leave alone"; an explicit "" still means "clear"."""
    cat = _create_category(client)

    resp = client.put(
        f"/api/bookmarks/categories/{cat['id']}",
        json={"start_date": "", "end_date": ""},
    )
    assert resp.status_code == 200
    body = resp.json()

    assert body["start_date"] == ""
    assert body["end_date"] == ""
    assert body["name"] == "Sanga"


def test_put_category_explicit_null_leaves_the_field_alone(client):
    """An explicit null is the service's own "do not modify" sentinel."""
    cat = _create_category(client)

    resp = client.put(
        f"/api/bookmarks/categories/{cat['id']}",
        json={"name": "Sanga 2", "color": None},
    )
    assert resp.status_code == 200
    body = resp.json()

    assert body["name"] == "Sanga 2"
    assert body["color"] == "#ef4444"


def test_put_category_rejects_a_malformed_date_it_was_actually_given(client):
    """A supplied bad date is still 422 — the None handling only skips absent ones."""
    cat = _create_category(client)

    resp = client.put(
        f"/api/bookmarks/categories/{cat['id']}",
        json={"end_date": "tomorrow"},
    )
    assert resp.status_code == 422


def test_put_category_rejects_start_after_end_when_both_are_supplied(client):
    cat = _create_category(client)

    resp = client.put(
        f"/api/bookmarks/categories/{cat['id']}",
        json={"start_date": "2026-06-07", "end_date": "2026-02-06"},
    )
    assert resp.status_code == 422


def test_put_category_start_after_a_stored_end_is_not_a_cross_field_error(client):
    """The cross-field check reads the two SUPPLIED values, not the stored pair.

    Sending only start_date leaves end_date None, so there is nothing to
    compare it against — the same rule the empty string has always followed.
    """
    cat = _create_category(client)

    resp = client.put(
        f"/api/bookmarks/categories/{cat['id']}",
        json={"start_date": "2026-12-31"},
    )
    assert resp.status_code == 200
    assert resp.json()["start_date"] == "2026-12-31"


def test_put_category_with_an_empty_body_still_re_stamps(client):
    """Deliberate asymmetry with the bookmark route — plan §6.6.

    The no-op write guard was scoped to update_bookmark, where the revert was
    actually observed. update_category keeps its unconditional re-stamp; this
    test exists so removing the guard from one side is a conscious act rather
    than an accident.
    """
    cat = _create_category(client)

    resp = client.put(f"/api/bookmarks/categories/{cat['id']}", json={})
    assert resp.status_code == 200
    assert resp.json()["updated_at"] > cat["updated_at"]


def test_put_unknown_category_id_is_404(client):
    resp = client.put("/api/bookmarks/categories/no-such-id", json={"name": "x"})
    assert resp.status_code == 404
