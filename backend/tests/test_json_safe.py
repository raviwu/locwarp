"""Behavior of services.json_safe load/write helpers."""

import json
import logging
from pathlib import Path

import pytest

from services.json_safe import safe_load_json, safe_write_json


def test_load_returns_none_for_missing_file(tmp_path):
    assert safe_load_json(tmp_path / "no_such_file.json") is None


def test_load_round_trips_valid_payload(tmp_path):
    p = tmp_path / "data.json"
    payload = {"a": 1, "b": [2, 3]}
    assert safe_write_json(p, payload) is True
    assert safe_load_json(p) == payload


def test_load_empty_file_is_silent_no_backup(tmp_path, caplog):
    """An empty file is the benign zero-byte case (interrupted write,
    external truncation). It must NOT be backed up as corrupt and must
    NOT log at ERROR level — those are reserved for files that contain
    bytes which fail to parse."""
    p = tmp_path / "empty.json"
    p.write_text("")

    with caplog.at_level(logging.DEBUG, logger="services.json_safe"):
        assert safe_load_json(p) is None

    # No error log line.
    assert not any(rec.levelno >= logging.WARNING for rec in caplog.records), (
        [(r.levelname, r.message) for r in caplog.records]
    )
    # No .bak-* sibling created.
    backups = list(tmp_path.glob("empty.json.bak-*"))
    assert backups == [], backups
    # Empty file was cleaned up so next write starts fresh.
    assert not p.exists()


def test_load_truly_corrupt_file_is_backed_up(tmp_path, caplog):
    """A file with bytes that fail to parse must be backed up to a
    .bak-<timestamp> sibling and logged at ERROR level."""
    p = tmp_path / "broken.json"
    p.write_text("{not json}")

    with caplog.at_level(logging.ERROR, logger="services.json_safe"):
        assert safe_load_json(p) is None

    assert any(rec.levelno >= logging.ERROR for rec in caplog.records)
    backups = list(tmp_path.glob("broken.json.bak-*"))
    assert len(backups) == 1
    # Original bytes were preserved in the backup.
    assert backups[0].read_text() == "{not json}"


def test_write_succeeds_despite_unwritable_stale_tmp(tmp_path):
    """A stale, unwritable sibling .tmp must not block a write.

    An interrupted admin-mode (root) run can leave a root-owned
    ``<name>.tmp`` behind. A later non-root run then cannot open that
    fixed-name temp for writing, so every save fails silently and the
    real file is never updated. The atomic write must use a unique temp
    name per call so a foreign or read-only stale .tmp can never collide.
    """
    p = tmp_path / "data.json"
    p.write_text(json.dumps({"original": True}))

    # The stale root-owned temp, simulated: a sibling .tmp the current
    # process cannot open for writing.
    stale_tmp = tmp_path / "data.json.tmp"
    stale_tmp.write_text("garbage from an interrupted run")
    stale_tmp.chmod(0o444)

    try:
        assert safe_write_json(p, {"updated": True}) is True
        assert safe_load_json(p) == {"updated": True}
    finally:
        stale_tmp.chmod(0o644)


def test_failed_write_leaves_no_orphan_temp(tmp_path):
    """A write that fails after the temp file is created must not leave
    the temp behind. With unique per-call temp names, an uncleaned
    failure would litter the (cloud-synced) folder with junk files."""
    # Target path is a directory, so the final atomic replace fails.
    target = tmp_path / "data.json"
    target.mkdir()

    assert safe_write_json(target, {"x": 1}) is False
    leftovers = [q for q in tmp_path.iterdir() if q != target]
    assert leftovers == [], leftovers
