"""Tests for ``materialize_if_placeholder``.

These never touch real iCloud — ``subprocess.run`` is monkeypatched so the
tests assert only the helper's branching and error handling. The placeholder
sibling (``.<name>.icloud``) is faked by ``touch``ing a file with the
expected name.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from services import cloud_sync


def _make_placeholder(canonical: Path) -> Path:
    placeholder = canonical.parent / f".{canonical.name}.icloud"
    placeholder.write_text("")
    return placeholder


def test_no_placeholder_is_noop(tmp_path, monkeypatch):
    canonical = tmp_path / "bookmarks.json"
    canonical.write_text("{}")

    run_mock = MagicMock()
    monkeypatch.setattr(cloud_sync.subprocess, "run", run_mock)

    cloud_sync.materialize_if_placeholder(canonical)

    run_mock.assert_not_called()


def test_placeholder_triggers_brctl(tmp_path, monkeypatch):
    canonical = tmp_path / "bookmarks.json"
    _make_placeholder(canonical)

    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"", stderr=b"")
    run_mock = MagicMock(return_value=completed)
    monkeypatch.setattr(cloud_sync.subprocess, "run", run_mock)

    cloud_sync.materialize_if_placeholder(canonical)

    run_mock.assert_called_once()
    args, kwargs = run_mock.call_args
    cmd = args[0]
    assert cmd[0] == "brctl"
    assert cmd[1] == "download"
    assert cmd[2] == str(canonical)
    assert kwargs.get("check") is False
    assert "timeout" in kwargs


def test_timeout_does_not_raise(tmp_path, monkeypatch, caplog):
    canonical = tmp_path / "routes.json"
    _make_placeholder(canonical)

    def _raise_timeout(*a, **kw):
        raise subprocess.TimeoutExpired(cmd=["brctl"], timeout=kw.get("timeout", 1.0))

    monkeypatch.setattr(cloud_sync.subprocess, "run", _raise_timeout)

    with caplog.at_level("WARNING"):
        cloud_sync.materialize_if_placeholder(canonical)
    assert any("timed out" in r.message for r in caplog.records)


def test_brctl_missing_does_not_raise(tmp_path, monkeypatch):
    canonical = tmp_path / "bookmarks.json"
    _make_placeholder(canonical)

    def _raise_fnf(*a, **kw):
        raise FileNotFoundError("brctl: not found")

    monkeypatch.setattr(cloud_sync.subprocess, "run", _raise_fnf)
    cloud_sync.materialize_if_placeholder(canonical)  # must not raise


def test_non_zero_exit_does_not_raise(tmp_path, monkeypatch, caplog):
    canonical = tmp_path / "bookmarks.json"
    _make_placeholder(canonical)

    completed = subprocess.CompletedProcess(
        args=[], returncode=1, stdout=b"", stderr=b"download failed",
    )
    monkeypatch.setattr(cloud_sync.subprocess, "run", MagicMock(return_value=completed))

    with caplog.at_level("WARNING"):
        cloud_sync.materialize_if_placeholder(canonical)
    assert any("exited 1" in r.message for r in caplog.records)


def test_timeout_env_var_respected(monkeypatch):
    monkeypatch.setenv("LOCWARP_ICLOUD_DOWNLOAD_TIMEOUT_S", "3.5")
    assert cloud_sync._icloud_download_timeout() == 3.5


def test_timeout_env_var_clamped_to_max(monkeypatch):
    monkeypatch.setenv("LOCWARP_ICLOUD_DOWNLOAD_TIMEOUT_S", "9999")
    assert cloud_sync._icloud_download_timeout() == cloud_sync._ICLOUD_DOWNLOAD_TIMEOUT_MAX


def test_timeout_env_var_invalid_falls_back(monkeypatch):
    monkeypatch.setenv("LOCWARP_ICLOUD_DOWNLOAD_TIMEOUT_S", "not-a-number")
    assert (
        cloud_sync._icloud_download_timeout()
        == cloud_sync._ICLOUD_DOWNLOAD_TIMEOUT_DEFAULT
    )
