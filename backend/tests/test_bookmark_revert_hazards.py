"""The bookmark-revert acceptance tests: what E1 and F fixed, and what is left.

Root-cause report: docs/superpowers/specs/2026-08-26-bookmark-revert-root-cause.md

Design root cause, and where each fix sits relative to it:
  - ``update_bookmark`` re-stamps ``bm.updated_at`` on every call that changes
    something, so a stale copy carrying a fresh timestamp beats a newer copy
    carrying an older one. E1 and F both work UPSTREAM of that.
  - backend/domain/store_merge.py used to merge whole records by comparing
    those ``updated_at`` strings. Change G (2026-08-27) replaced that with
    per-unit resolution against ``field_updated_at``, so the record-level
    stamp no longer decides every field at once.

The four tests here, in the order they appear:

  1. ``test_disjoint_field_edits_from_two_machines_both_survive`` — G's
     acceptance test, and the one hazard that stayed open through E1 and F:
     two machines edit *different* fields of one record between syncs. It used
     to assert the loss. The full per-field matrix lives in
     ``test_store_merge_per_field.py`` and ``test_store_writers_stamp_units.py``.
  2. ``test_catalog_force_sync_preserves_local_rename`` — E1's acceptance test.
     ``import_catalog`` resolves each field three ways against a per-machine
     baseline (``domain/catalog_merge.py``) instead of overwriting seed-*
     records wholesale, so a local rename survives a force-sync. The full E1
     matrix lives in ``test_catalog_sync_three_way.py``.
  3. ``test_api_put_omitting_address_field_leaves_it_unchanged`` — F's
     acceptance test at the HTTP layer. The route takes a partial
     ``BookmarkUpdate`` body, so a key the client omits is left alone instead
     of arriving as ``Bookmark``'s schema default and blanking the field.
  4. ``test_sparse_put_does_not_clobber_fresher_remote_field`` — F across two
     machines: a sparse body no longer clobbers a field a peer changed, while
     a client that explicitly sends every field still wins by LWW.

Test 1 is a SERVICE-layer test and F could never reach it: it calls
``BookmarkManager.update_bookmark`` directly, and its staleness lives in
manager A's in-memory record rather than in a request body. What does reach it
is G, at the merge. The no-op write guard shipped with F is why manager A's
call carries one genuine field edit — a call whose values all match the stored
record writes nothing at all, which would make the test vacuous.
"""
import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from bootstrap.factories import make_bookmark_manager
from models.schemas import Bookmark


def _patch_paths(tmp_path, monkeypatch):
    """Same fixture pattern as test_bookmark_concurrency.py / test_bookmarks_thread_race.py.

    NOTE, corrected after review: this is belt-and-braces, not a gap-fill.
    conftest.py's autouse `_isolate_real_data_paths` guard does NOT only
    patch `config.*` — when `services.bookmarks` is already in `sys.modules`
    it also repoints `sb.BOOKMARKS_FILE` and `sb._CONFIG_DEFAULT_BOOKMARKS_FILE`
    directly, to the same tmp_path. And it already is imported by the time
    any test here runs: this module's top-level
    `from bootstrap.factories import make_bookmark_manager` pulls in
    `services.bookmarks` at collection time, before the autouse fixture ever
    executes. So this fixture is redundant with the conftest guard for every
    test in this file today. It stays anyway — an explicit second patch here
    costs nothing and is cheap insurance in a data-destroying area (writes
    real bookmarks.json) against the import chain ever changing such that
    services.bookmarks is no longer pre-imported at collection time."""
    monkeypatch.setattr("services.bookmarks.BOOKMARKS_FILE", tmp_path / "bookmarks.json")
    monkeypatch.setattr("services.bookmarks._CONFIG_DEFAULT_BOOKMARKS_FILE", tmp_path / "bookmarks.json")


def test_disjoint_field_edits_from_two_machines_both_survive(tmp_path, monkeypatch):
    """CLOSED BY G: two machines edit different fields of one record between
    syncs, and both edits survive.

    Two BookmarkManager instances share one on-disk store file, mirroring
    Ravi's two-Mac iCloud-sync setup:

      Manager A                          Manager B
      ────────────────────────────────   ────────────────────────────────
      create_bookmark(name="old")
      (holds in-memory copy: "old")      make_bookmark_manager() loads
                                          the same file -> also holds "old"
                                          update_bookmark(name="new") + save
                                          (disk now has "new", timestamp t_b)
      update_bookmark(address=...)       <- A edits a DIFFERENT field, never
      + save                                having seen B's rename; its own
                                             record still carries "old", and
                                             the re-stamp makes it t_a > t_b

    Before G this was the residual hazard, and the assertions below were its
    mirror image: A's save won the merge whole because t_a > t_b, so the
    on-disk name reverted to "old" even though B's rename was the newer
    *intent*. Neither shipped fix could reach it — E1 is a catalog-sync rule,
    and F narrows the request BODY while the staleness here lives in manager
    A's in-memory record: ``update_bookmark`` mutates the object
    ``_find_bookmark`` returns, A's own copy, which still holds "old".

    G closes it at the merge. A's write stamps only the `address` unit and
    backfills `name` with A's PREVIOUS record stamp, so B's genuinely newer
    `name` out-ranks it unit-for-unit even though A's record-level
    ``updated_at`` is later. The record-stamp assertion below is kept exactly
    as it was: t_a > t_b still holds, and that is the point — it is no longer
    what decides the name.

    A's call still carries ``address="A's own edit"`` rather than re-sending
    its own stored values, because F's no-op guard skips a write that changes
    nothing.
    """
    _patch_paths(tmp_path, monkeypatch)
    store_path = tmp_path / "bookmarks.json"

    mgr_a = make_bookmark_manager()
    bm = mgr_a.create_bookmark(name="old", lat=25.0, lng=121.0, category_id="default")

    mgr_b = make_bookmark_manager()  # loads the file A just wrote; also sees "old"
    assert any(b.id == bm.id and b.name == "old" for b in mgr_b.list_bookmarks())

    b_result = mgr_b.update_bookmark(
        bm.id,
        name="new",
        lat=bm.lat,
        lng=bm.lng,
        address=bm.address,
        category_id=bm.category_id,
        country_code=bm.country_code,
    )
    assert b_result is not None and b_result.name == "new"

    # Manager A never saw B's rename — it still holds the ORIGINAL snapshot
    # from create_bookmark, so its in-memory `name` is the stale "old". A edits
    # a field B did not touch: that is a real write, which F's no-op guard
    # therefore lets through, and it drags A's whole stale record to disk.
    a_result = mgr_a.update_bookmark(
        bm.id,
        name=bm.name,       # "old" -- stale
        lat=bm.lat,
        lng=bm.lng,
        address="A's own edit",
        category_id=bm.category_id,
        country_code=bm.country_code,
    )
    assert a_result is not None

    on_disk = json.loads(store_path.read_text(encoding="utf-8"))
    on_disk_bm = next(b for b in on_disk["bookmarks"] if b["id"] == bm.id)

    # Outcome: both edits survive. B's rename is not collateral damage of A's
    # unrelated address edit.
    assert on_disk_bm["name"] == "new"
    assert on_disk_bm["address"] == "A's own edit"
    # Mechanism: A's record-level stamp IS still the newer one — that has not
    # changed and is exactly why this used to fail. What decides `name` now is
    # the per-unit stamp, and A's write backfilled that unit with A's previous
    # record stamp instead of re-stamping it.
    assert on_disk_bm["updated_at"] > b_result.updated_at
    assert on_disk_bm["field_updated_at"]["name"] == b_result.field_updated_at["name"]
    assert on_disk_bm["field_updated_at"]["address"] > on_disk_bm["field_updated_at"]["name"]


def test_catalog_force_sync_preserves_local_rename(tmp_path, monkeypatch):
    """HAZARD #1, now closed by E1 (root-cause report § "4. Catalog force-sync
    wholesale-overwrites `seed-*` records"): import_catalog resolves each
    field against the local baseline instead of copying the catalog's values
    wholesale, so a locally-renamed and locally-moved seed-* bookmark survives
    a force-sync.

    Uses a small INLINE catalog payload constructed in this test, not the
    real backend/static/catalog.json (whose contents change over time).

    This machine has no catalog_baseline.json, so the merge bootstraps
    `base := theirs` for every field. The record therefore resolves as
    ours != base, theirs == base for name/lat/lng — a pure local edit, not a
    conflict: the values are kept, `kept_local` is 1 and `conflicts` is 0.
    updated_at is left alone because none of §4.4's three re-stamp conditions
    fires — nothing was taken from the catalog, the id has no tombstone, and
    enrich_bookmark re-resolves the same coordinates the local move already
    resolved, so it reports no change.
    """
    _patch_paths(tmp_path, monkeypatch)

    mgr = make_bookmark_manager()

    # Seed a bookmark whose id matches an entry in our inline catalog below,
    # as if it had been installed by a prior catalog sync.
    seed = Bookmark(
        id="seed-hazard-test-1",
        name="Catalog Original",
        lat=25.0,
        lng=121.0,
        address="",
        category_id="default",
        created_at="2026-01-01T00:00:00+00:00",
        last_used_at="2026-01-01T00:00:00+00:00",
        country_code="tw",
        updated_at="2026-01-01T00:00:00+00:00",
    )
    mgr.store.bookmarks.append(seed)
    mgr._save()

    # Rename AND move it locally through the normal update path.
    renamed = mgr.update_bookmark(
        seed.id,
        name="My Renamed Spot",
        lat=26.0,
        lng=122.0,
        category_id="default",
    )
    assert renamed is not None and renamed.name == "My Renamed Spot"
    local_updated_at = renamed.updated_at

    catalog_payload = json.dumps(
        {
            "categories": [
                {
                    "id": "default",
                    "name": "預設",
                    "color": "#6c8cff",
                    "sort_order": 0,
                    "created_at": "2026-01-01T00:00:00+00:00",
                }
            ],
            "bookmarks": [
                {
                    "id": "seed-hazard-test-1",
                    "name": "Catalog Original",
                    "lat": 25.0,
                    "lng": 121.0,
                    "address": "",
                    "category_id": "default",
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "last_used_at": "2026-01-01T00:00:00+00:00",
                    "country_code": "tw",
                }
            ],
            "tombstones": [],
        }
    )

    result = mgr.import_catalog(catalog_payload)
    # An id collision is still an "update", changed or not (plan Q4).
    assert result["updated"] >= 1
    assert result["kept_local"] == 1
    assert result["conflicts"] == 0

    preserved = mgr._find_bookmark(seed.id)
    assert preserved is not None
    # Outcome: the local rename AND the local move both survive.
    assert preserved.name == "My Renamed Spot"
    assert preserved.lat == 26.0
    assert preserved.lng == 122.0
    assert preserved.category_id == "default"  # unchanged on both sides here
    # Mechanism: nothing was taken from the catalog, so the record is not
    # re-stamped — a force-sync here cannot out-vote a fresher edit still
    # un-synced on the other Mac.
    assert preserved.updated_at == local_updated_at


# ── API-level sibling of Test 1: the test fix F actually inverted ─────────
#
# Test 1 above (test_stale_whole_record_update_outranks_fresher_remote_copy)
# calls BookmarkManager.update_bookmark directly, so it pins the SERVICE-level
# mechanism and is out of F's reach (see that test's docstring). This test
# drives the real FastAPI route instead, using the TestClient(main.app) pattern
# from test_bookmarks_api.py's `client` fixture, and it is the one F inverted:
# `Bookmark.address` defaults to `""` (models/schemas.py), so before F a JSON
# body that simply OMITTED "address" still arrived at the route as address=""
# (Pydantic filling the default), which update_bookmark's `value is not None`
# check happily applied — blanking a field the client never touched. The route
# now takes a partial `BookmarkUpdate` and forwards only the keys the client
# actually sent.


@pytest.fixture
def _api_client(tmp_path, monkeypatch):
    """Same shape as test_bookmarks_api.py's `client` fixture: TestClient
    with the bookmark store redirected to tmp_path and a fresh manager built
    against the patched path."""
    monkeypatch.setattr("services.bookmarks.BOOKMARKS_FILE", tmp_path / "bookmarks.json")
    import main
    main.app_state.bookmark_manager = make_bookmark_manager()
    return TestClient(main.app)


def test_api_put_omitting_address_field_leaves_it_unchanged(_api_client):
    """HAZARD #2, API layer, closed by F (root-cause report § "1. Whole-record
    PUT carrying a stale client snapshot — **PRIME SUSPECT**"): a PUT body that
    omits a field the client never intended to touch now leaves it alone.

    The route's request model is ``BookmarkUpdate``, whose fields are all
    optional, and it forwards only ``model_dump(exclude_unset=True)`` — so
    "the client sent an empty string" and "the client sent nothing" are finally
    distinguishable, and only the first one clears the field.
    """
    create_resp = _api_client.post(
        "/api/bookmarks",
        json={"name": "x", "lat": 1.0, "lng": 2.0, "address": "有地址", "category_id": "default"},
    )
    assert create_resp.status_code == 200
    bm_id = create_resp.json()["id"]
    assert create_resp.json()["address"] == "有地址"

    # PUT body omits "address" entirely -- the client only meant to rename.
    put_resp = _api_client.put(
        f"/api/bookmarks/{bm_id}",
        json={"name": "y", "lat": 1.0, "lng": 2.0, "category_id": "default"},
    )
    assert put_resp.status_code == 200
    body = put_resp.json()
    assert body["name"] == "y"
    # Outcome: the never-mentioned address field survives untouched.
    assert body["address"] == "有地址"


def test_sparse_put_does_not_clobber_fresher_remote_field(tmp_path, monkeypatch):
    """F across two machines: a sparse PUT no longer drags a stale name along.

    This is the realistic topology, and it is NOT the one Test 1 pins. Each Mac
    runs its own backend whose watcher reconciles the synced file, so by the
    time the user presses Save that Mac's manager already holds the peer's
    rename — the staleness lives only in the dialog snapshot in the browser.
    So the manager HTTP serves here is built after B's save (it loads "new"),
    and the only stale thing left is the request body.

      Manager A                          Manager B
      ────────────────────────────────   ────────────────────────────────
      create_bookmark(name="old")
                                          renames it to "new" and saves
      serving = make_bookmark_manager()  <- reads "new" back off disk;
      PUT {"address": ...}                  the sparse body never mentions
                                             the name, so "new" survives

    The second half is the retained characterization: a client that explicitly
    sends every field still wins by LWW. That is correct behavior, not a bug —
    F narrows what the client says, it does not second-guess what it means.
    The store-level hazard that remains is Test 1's, and only change G closes
    it.
    """
    _patch_paths(tmp_path, monkeypatch)
    store_path = tmp_path / "bookmarks.json"

    # The body below is parseable ONLY because the route now takes
    # BookmarkUpdate. The persisted model still requires name/lat/lng, which is
    # why this same body was a 422 before F — and why widening `Bookmark` would
    # have been the wrong fix.
    with pytest.raises(ValidationError):
        Bookmark(**{"address": "Zhongshan Rd"})

    mgr_a = make_bookmark_manager()
    bm = mgr_a.create_bookmark(name="old", lat=25.0, lng=121.0, category_id="default")

    mgr_b = make_bookmark_manager()
    b_result = mgr_b.update_bookmark(bm.id, name="new")
    assert b_result is not None and b_result.name == "new"

    import main
    serving = make_bookmark_manager()  # Mac A's backend after its watcher caught up
    assert any(b.id == bm.id and b.name == "new" for b in serving.list_bookmarks())
    monkeypatch.setattr(main.app_state, "bookmark_manager", serving)
    client = TestClient(main.app)

    # The user only edited the address, so only the address goes on the wire.
    sparse_resp = client.put(f"/api/bookmarks/{bm.id}", json={"address": "Zhongshan Rd"})
    assert sparse_resp.status_code == 200

    on_disk = json.loads(store_path.read_text(encoding="utf-8"))
    on_disk_bm = next(b for b in on_disk["bookmarks"] if b["id"] == bm.id)
    assert on_disk_bm["name"] == "new"
    assert on_disk_bm["address"] == "Zhongshan Rd"
    # B's rename survives even though A's write is strictly newer -- which is
    # the whole point: the sparse body had nothing to say about the name.
    assert on_disk_bm["updated_at"] > b_result.updated_at

    # Retained characterization: an explicit full body still wins by LWW.
    full_resp = client.put(
        f"/api/bookmarks/{bm.id}",
        json={
            "name": "old",
            "lat": bm.lat,
            "lng": bm.lng,
            "address": bm.address,
            "category_id": bm.category_id,
            "country_code": bm.country_code,
        },
    )
    assert full_resp.status_code == 200

    on_disk = json.loads(store_path.read_text(encoding="utf-8"))
    on_disk_bm = next(b for b in on_disk["bookmarks"] if b["id"] == bm.id)
    assert on_disk_bm["name"] == "old"
