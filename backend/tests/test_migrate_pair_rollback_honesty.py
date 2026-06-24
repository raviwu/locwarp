"""Characterization (A16): migrate_pair is NOT all-or-nothing across dst.

On a merge into a pre-existing dst file, a later failure restores src from
snapshot but leaves the (convergent, CRDT-merged) dst as-is. This pins that
behavior so the docstring stays honest. See cloud_sync.migrate_pair.
"""
from pathlib import Path

import pytest

from services import cloud_sync
from services.cloud_sync import migrate_pair


def _store(*names: str) -> str:
    # Minimal valid bookmark-store JSON with the given bookmark ids.
    import json
    return json.dumps(
        {
            "categories": [],
            "bookmarks": [
                {
                    "id": n,
                    "name": n,
                    "lat": 1.0,
                    "lng": 2.0,
                    "updated_at": "2025-01-01T00:00:00+00:00",
                }
                for n in names
            ],
        }
    )


def test_partial_failure_restores_src_but_not_premerge_dst(tmp_path, monkeypatch):
    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst"
    src_dir.mkdir()
    dst_dir.mkdir()

    # bookmarks: both sides exist with different content -> triggers a real merge.
    (src_dir / "bookmarks.json").write_text(_store("from-src"), encoding="utf-8")
    (dst_dir / "bookmarks.json").write_text(_store("already-in-dst"), encoding="utf-8")
    dst_bookmarks_before = (dst_dir / "bookmarks.json").read_text(encoding="utf-8")

    # routes: present in src so the SECOND _PAIR_FILES iteration runs and we can
    # make it blow up, proving the bookmarks merge already happened + isn't undone.
    # (_PAIR_FILES order is bookmarks-then-routes, confirmed at cloud_sync.py:130.)
    (src_dir / "routes.json").write_text(_store("r1"), encoding="utf-8")

    # Force the routes step to fail AFTER the bookmarks merge mutated dst.
    real_move = cloud_sync._move_or_merge_file

    def _boom(src, dst, kind):
        if kind == "routes":
            raise RuntimeError("simulated routes-move failure")
        return real_move(src, dst, kind)

    monkeypatch.setattr(cloud_sync, "_move_or_merge_file", _boom)

    with pytest.raises(RuntimeError, match="simulated routes-move failure"):
        migrate_pair(src_dir, dst_dir)

    # src restored from snapshot (the bookmarks src was unlinked by the merge,
    # then put back by rollback).
    assert (src_dir / "bookmarks.json").exists(), "src bookmarks not restored on failure"
    # dst was MERGED in place and is NOT rolled back to its pre-merge bytes:
    # the convergent union now contains BOTH ids.
    import json
    dst_after = json.loads((dst_dir / "bookmarks.json").read_text(encoding="utf-8"))
    ids = {b["id"] for b in dst_after["bookmarks"]}
    assert ids == {"from-src", "already-in-dst"}, (
        "dst should hold the convergent union, proving it is not all-or-nothing"
    )
    assert (dst_dir / "bookmarks.json").read_text(encoding="utf-8") != dst_bookmarks_before
