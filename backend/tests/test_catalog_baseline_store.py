"""Catalog-baseline path isolation + the infra store that reads/writes it.

The baseline records the catalog values this machine last applied, so the
force-sync can tell a user edit from a catalog correction. It lives under
~/.locwarp (local-only, never the iCloud sync_folder), which is exactly the
class of path the autouse conftest guard must redirect.
"""
import json
from pathlib import Path

from bootstrap.factories import make_bookmark_manager
from infra.persistence.catalog_baseline_store import FileCatalogBaselineStore

PAYLOAD = {
    "_meta": {
        "format_version": 1,
        "compiled_at": "2026-05-23",
        "applied_at": "2026-08-26T09:00:00+00:00",
    },
    "categories": {
        "seed-sapporo-tour": {
            "name": "Sapporo Tour",
            "color": "#3b82f6",
            "sort_order": 1,
            "start_date": "",
            "end_date": "",
        }
    },
    "bookmarks": {
        "seed-sapporo-a": {
            "name": "Odori Park",
            "lat": 43.068027,
            "lng": 141.350895,
            "address": "",
            "category_id": "seed-sapporo-tour",
        }
    },
}


def test_baseline_path_is_isolated_by_conftest(tmp_path):
    import config

    assert config.CATALOG_BASELINE_FILE == tmp_path / "catalog_baseline.json"
    assert Path.home() / ".locwarp" not in config.CATALOG_BASELINE_FILE.parents


def test_baseline_round_trips_format_version_1_payload(tmp_path):
    """Key-for-key, _meta included — a store that drops a key or coerces a
    nested dict must fail here rather than at sync time."""
    store = FileCatalogBaselineStore(lambda: tmp_path / "catalog_baseline.json")
    store.write(PAYLOAD)
    assert store.read() == PAYLOAD


def test_read_returns_none_when_the_file_is_missing(tmp_path):
    store = FileCatalogBaselineStore(lambda: tmp_path / "nope.json")
    assert store.read() is None


def test_read_returns_none_on_a_corrupt_file(tmp_path):
    path = tmp_path / "catalog_baseline.json"
    path.write_text("{not json", encoding="utf-8")
    assert FileCatalogBaselineStore(lambda: path).read() is None


def test_path_is_resolved_lazily_at_every_call(tmp_path):
    """The provider is called per operation, never captured at construction —
    that is what makes the conftest monkeypatch of config.CATALOG_BASELINE_FILE
    effective for a store built before the patch."""
    target = {"p": tmp_path / "first.json"}
    store = FileCatalogBaselineStore(lambda: target["p"])
    store.write({"which": "first"})

    target["p"] = tmp_path / "second.json"
    store.write({"which": "second"})

    assert json.loads((tmp_path / "first.json").read_text()) == {"which": "first"}
    assert store.read() == {"which": "second"}


def test_factory_wires_a_baseline_port_into_the_manager():
    """bootstrap/factories.py is the ONLY construction site of BookmarkManager
    in the repo, so a dropped argument there would silently degrade every sync
    to the permanent-bootstrap path. Pin it."""
    mgr = make_bookmark_manager()
    assert mgr._catalog_baseline is not None


def test_manager_constructs_without_a_baseline_port(tmp_path):
    from infra.persistence.json_store import JsonStore
    from models.schemas import BookmarkStore
    from services.bookmarks import BookmarkManager

    mgr = BookmarkManager(repo=JsonStore(BookmarkStore, lambda: tmp_path / "bm.json"))
    assert mgr._catalog_baseline is None


def test_two_managers_keep_two_independent_baselines(tmp_path):
    """The baseline is per MACHINE, and the repo models two machines as two
    managers over one shared store file. Without a per-manager path seam both
    would share one baseline and a two-machine test would prove the wrong thing.
    """
    p1 = tmp_path / "mac1.json"
    p2 = tmp_path / "mac2.json"
    shared = tmp_path / "bookmarks.json"

    mac1 = make_bookmark_manager(lambda: shared, baseline_path_provider=lambda: p1)
    mac2 = make_bookmark_manager(lambda: shared, baseline_path_provider=lambda: p2)

    mac1._catalog_baseline.write({"which": "mac1"})
    assert not p2.exists()
    assert mac2._catalog_baseline.read() is None

    mac2._catalog_baseline.write({"which": "mac2"})
    assert mac1._catalog_baseline.read() == {"which": "mac1"}
    assert mac2._catalog_baseline.read() == {"which": "mac2"}


def test_import_catalog_without_a_baseline_port_warns(tmp_path, caplog):
    """R4: the None default cannot fail loudly (it is what keeps the port
    optional and the domain testable), so it must at least be audible."""
    import logging

    from infra.persistence.json_store import JsonStore
    from models.schemas import BookmarkStore
    from services.bookmarks import BookmarkManager

    mgr = BookmarkManager(repo=JsonStore(BookmarkStore, lambda: tmp_path / "bm.json"))
    with caplog.at_level(logging.WARNING, logger="services.bookmarks"):
        mgr.import_catalog(json.dumps({"categories": [], "bookmarks": []}))

    assert any("baseline" in r.getMessage().lower() for r in caplog.records)
