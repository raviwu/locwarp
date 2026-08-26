"""Characterization tests pinning the two confirmed bookmark-revert hazards.

Root-cause report: docs/superpowers/specs/2026-08-26-bookmark-revert-root-cause.md

Design root cause (unchanged by these tests — they PIN today's behavior on
purpose, they do not fix it):
  - backend/domain/store_merge.py:41-52 merges whole records by comparing
    ``updated_at`` strings; there is no field-level merge.
  - backend/services/bookmarks.py:419 unconditionally re-stamps
    ``bm.updated_at = _now_iso()`` on every ``update_bookmark`` call, even
    when the caller's copy of the record is stale.

These two facts combine into two independently-triggerable hazards:
  1. Catalog force-sync wholesale-overwrites every seed-* record
     (backend/services/bookmarks.py:560-565, via ``import_catalog``).
  2. A stale full-record PUT (e.g. from the Edit dialog re-submitting a
     snapshot taken at dialog-open time) beats a fresher remote edit,
     because the stale PUT gets a *newer* timestamp than the remote edit
     simply by being submitted later in wall-clock time.

Test 2 below asserts TODAY'S (buggy) outcome and is expected to INVERT when
fix E ships (catalog sync respects a local edit instead of always
overwriting seed-* records) — do not delete it, it is the acceptance
baseline fix E is measured against.

Test 1 is a different shape, and a previous version of this docstring
overclaimed what inverts it. Test 1 drives ``BookmarkManager.update_bookmark``
DIRECTLY, at the SERVICE layer, with every field passed explicitly (never
omitted) — it never goes through the HTTP route at all. Fix F, as scoped in
the root-cause report, is an API-layer-only change (``api/bookmarks.py``
gains a ``BookmarkUpdate`` model and forwards
``bookmark.model_dump(exclude_unset=True)`` instead of every field); it does
not touch ``update_bookmark``'s own allowed/``is not None`` loop, so fix F
alone changes nothing Test 1 exercises and does NOT invert it. Test 1 instead
pins the underlying SERVICE-level mechanism: the unconditional
``bm.updated_at = _now_iso()`` re-stamp (services/bookmarks.py:419) combined
with the whole-record strict-greater LWW (domain/store_merge.py:41-52). That
would only flip if a future change makes the re-stamp itself conditional on
an actual field diff, which fix F does not do. The test that fix F genuinely
inverts is the new API-level one added below,
``test_api_put_omitting_address_field_blanks_it_today`` — it drives the real
``PUT /api/bookmarks/{id}`` route with a partial JSON body.
"""
import json

import pytest
from fastapi.testclient import TestClient

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


def test_stale_whole_record_update_outranks_fresher_remote_copy(tmp_path, monkeypatch):
    """HAZARD #2 (root-cause report § "1. Whole-record PUT carrying a stale
    client snapshot — **PRIME SUSPECT**"): a stale PUT
    re-stamps updated_at and therefore wins merge_stores against a fresher
    remote rename, even though the remote rename happened first.

    Two BookmarkManager instances share one on-disk store file, mirroring
    Ravi's two-Mac iCloud-sync setup:

      Manager A                          Manager B
      ────────────────────────────────   ────────────────────────────────
      create_bookmark(name="old")
      (holds in-memory copy: "old")      make_bookmark_manager() loads
                                          the same file -> also holds "old"
                                          update_bookmark(name="new") + save
                                          (disk now has "new", timestamp t_b)
      update_bookmark(name="old", ...)   <- the HTTP PUT shape: full record,
      + save                                built from A's STALE in-memory
                                             copy, going through the real
                                             services/bookmarks.py:419
                                             re-stamp (timestamp t_a > t_b)

    Expected (buggy, current) outcome: A's save wins the merge because
    t_a > t_b, so the on-disk name reverts to "old" even though B's rename
    to "new" was the newer *intent*. This test pins BOTH the outcome (final
    name) and the mechanism (t_a > t_b) so it explains itself.

    This test calls ``BookmarkManager.update_bookmark`` DIRECTLY (the SERVICE
    layer), passing `name` explicitly on every call — including A's stale
    copy of it. It therefore does NOT go through the HTTP route at all, and
    fix F (as scoped in the root-cause report: an API-layer change that makes
    ``api/bookmarks.py`` forward only the keys the HTTP client actually sent)
    changes nothing this test exercises. Fix F alone does NOT invert this
    test.

    What this test actually pins is the SERVICE-level mechanism: the
    unconditional ``bm.updated_at = _now_iso()`` re-stamp at
    services/bookmarks.py:419, combined with the whole-record strict-greater
    LWW in domain/store_merge.py:41-52. The two lines this test would need to
    flip are ``assert on_disk_bm["name"] == "old"`` and
    ``assert on_disk_bm["updated_at"] > b_result.updated_at`` below — and
    they only flip if a future change makes that re-stamp conditional on an
    actual field diff (e.g. skip the re-stamp, or skip applying a field,
    when the incoming value matches what the manager already had before the
    caller's snapshot went stale). That is a deeper change than fix F, which
    touches only how the API layer builds the kwargs it passes into
    ``update_bookmark`` — the loop inside ``update_bookmark`` itself is
    unchanged by fix F.

    A future engineer has two honest options here, not one:
      (a) If the service-level re-stamp is ever made conditional, update
          THIS test's two assertions above to match the new (fixed) outcome.
      (b) Otherwise, leave this test alone — it keeps pinning the service
          mechanism — and rely on the sibling API-level test added below,
          ``test_api_put_omitting_address_field_blanks_it_today``, which
          drives the real ``PUT /api/bookmarks/{id}`` route with a partial
          JSON body. THAT is the test fix F is actually expected to invert.
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
    # from create_bookmark. This is exactly the full-record body an HTTP PUT
    # built from a stale client-side copy would send.
    a_result = mgr_a.update_bookmark(
        bm.id,
        name=bm.name,       # "old" -- stale
        lat=bm.lat,
        lng=bm.lng,
        address=bm.address,
        category_id=bm.category_id,
        country_code=bm.country_code,
    )
    assert a_result is not None

    on_disk = json.loads(store_path.read_text(encoding="utf-8"))
    on_disk_bm = next(b for b in on_disk["bookmarks"] if b["id"] == bm.id)

    # Outcome: the stale value won.
    assert on_disk_bm["name"] == "old"
    # Mechanism: it won BECAUSE the stale PUT got re-stamped strictly newer
    # than B's genuinely-fresher edit -- not because of id ordering or luck.
    assert on_disk_bm["updated_at"] > b_result.updated_at


def test_catalog_force_sync_discards_local_rename(tmp_path, monkeypatch):
    """HAZARD #1 (root-cause report § "4. Catalog force-sync
    wholesale-overwrites `seed-*` records"): import_catalog
    unconditionally overwrites a locally-renamed seed-* bookmark back to the
    bundled catalog's values, because _upsert_items (services/bookmarks.py:
    559-566) overwrites name/lat/lng/category_id/country_code on any id
    collision and force_seed_items stamps updated_at=now() so the catalog
    copy always wins merge_stores.

    Uses a small INLINE catalog payload constructed in this test, not the
    real backend/static/catalog.json (whose contents change over time).

    Fix E (catalog sync respects local edits) is expected to INVERT this
    assertion: a locally-renamed/moved seed-* bookmark should survive a
    force-sync instead of being silently reverted.
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
    assert result["updated"] >= 1

    reverted = mgr._find_bookmark(seed.id)
    assert reverted is not None
    # Outcome: the local rename AND the local move are both discarded.
    assert reverted.name == "Catalog Original"
    assert reverted.lat == 25.0
    assert reverted.lng == 121.0
    assert reverted.category_id == "default"
    # Mechanism: force_seed_items stamped a fresh updated_at, strictly newer
    # than the local rename's, so the catalog copy always wins the merge.
    assert reverted.updated_at > local_updated_at


# ── API-level sibling of Test 1: the test fix F actually inverts ──────────
#
# Test 1 above (test_stale_whole_record_update_outranks_fresher_remote_copy)
# calls BookmarkManager.update_bookmark directly and always passes `name`
# explicitly, so it pins the SERVICE-level mechanism and is untouched by an
# API-only fix F (see that test's docstring). This test drives the real
# FastAPI route instead, using the TestClient(main.app) pattern from
# test_bookmarks_api.py's `client` fixture, and is the one fix F (root-cause
# report § "1. Whole-record PUT carrying a stale client snapshot —
# **PRIME SUSPECT**" → "Proposed fix (smallest correct change)") is expected
# to invert: today, `Bookmark.address` defaults to `""` (models/schemas.py),
# so a JSON body that simply OMITS "address" still arrives at the route as
# address="" (Pydantic fills the default), which update_bookmark's
# `value is not None` check happily applies — blanking a field the client
# never touched. After fix F ships (the route accepts a partial
# `BookmarkUpdate` and forwards only `model_dump(exclude_unset=True)`), an
# omitted "address" key would leave the existing address alone and this
# test's final assertion (`body["address"] == "existing address"`) would
# flip.


@pytest.fixture
def _api_client(tmp_path, monkeypatch):
    """Same shape as test_bookmarks_api.py's `client` fixture: TestClient
    with the bookmark store redirected to tmp_path and a fresh manager built
    against the patched path."""
    monkeypatch.setattr("services.bookmarks.BOOKMARKS_FILE", tmp_path / "bookmarks.json")
    import main
    main.app_state.bookmark_manager = make_bookmark_manager()
    return TestClient(main.app)


def test_api_put_omitting_address_field_blanks_it_today(_api_client):
    """HAZARD #2, API layer (root-cause report § "1. Whole-record PUT
    carrying a stale client snapshot — **PRIME SUSPECT**"): a PUT body that
    omits a field the client never intended to touch still blanks it, because
    ``Bookmark.address`` defaults to ``""`` and the route has no way to tell
    "the client sent an empty string" apart from "the client sent nothing".

    Expected (buggy, current) outcome: the address is wiped even though the
    PUT body never mentioned it. Fix F is expected to INVERT the final
    assertion below (`body["address"] == "有地址"` instead of `== ""`), since
    it changes the route to only apply keys the client actually sent.
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
    # Outcome (buggy today): the never-mentioned address field is blanked.
    assert body["address"] == ""
