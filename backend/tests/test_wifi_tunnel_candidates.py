"""Characterization + unit: build_tunnel_udid_candidates priority/dedup/fallback,
plus the api wrapper resolving connected udids + cached pair records."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import api.device as device_mod
from api.device import WifiTunnelStartRequest
from services.wifi_tunnel_service import build_tunnel_udid_candidates


def test_pure_priority_order_dedup():
    out = build_tunnel_udid_candidates(
        "REQ-UDID", "192.168.0.5", 49152,
        connected_udids=["USB-1", "REQ-UDID"],   # REQ-UDID dup must drop
        pair_record_idents=["CACHE-A", "USB-1"],  # USB-1 dup must drop
    )
    assert out == ["REQ-UDID", "USB-1", "CACHE-A"]


def test_pure_no_req_udid_starts_with_connected():
    out = build_tunnel_udid_candidates(
        None, "10.0.0.9", 50000,
        connected_udids=["USB-1"],
        pair_record_idents=["CACHE-A"],
    )
    assert out == ["USB-1", "CACHE-A"]


def test_pure_empty_falls_back_to_pending_key():
    out = build_tunnel_udid_candidates(
        None, "10.0.0.9", 50000,
        connected_udids=[],
        pair_record_idents=[],
    )
    assert out == ["pending:10.0.0.9:50000"]


def test_wrapper_resolves_dm_and_pair_records(monkeypatch):
    req = WifiTunnelStartRequest(ip="192.168.0.5", port=49152, udid="REQ-UDID")
    dm = MagicMock()
    dm._connections = {"USB-1": object()}
    # Stub the lazy pair-records iterator to two fake Path-like records.
    class _Rec:
        def __init__(self, name, mtime):
            self.name = name
            self._mtime = mtime
        def stat(self):
            return MagicMock(st_mtime=self._mtime)
    recs = [_Rec("remote_CACHE-A.plist", 100.0), _Rec("CACHE-B.plist", 200.0)]
    monkeypatch.setattr(
        "pymobiledevice3.pair_records.iter_remote_pair_records",
        lambda: recs, raising=False,
    )
    with patch.object(device_mod, "_dm", return_value=dm):
        out = device_mod._build_tunnel_udid_candidates(req)
    # req.udid first, then USB-tracked, then pair-record idents (wrapper sorts
    # mtime DESC: CACHE-B mtime 200 before CACHE-A mtime 100; remote_ stripped).
    assert out == ["REQ-UDID", "USB-1", "CACHE-B", "CACHE-A"]
