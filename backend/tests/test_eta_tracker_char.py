"""Characterize EtaTracker before it moves to domain/movement.py (Phase 3, Task 2).

Imports via the stable public path `from core import EtaTracker` and monkeypatches
`datetime` on EtaTracker's OWN module (resolved via EtaTracker.__module__), so this
net passes identically before the move (core.simulation_engine) and after it
(domain.movement) with no edit.
"""
import importlib
from datetime import datetime, timezone

import pytest

from core import EtaTracker


def test_initial_state_is_zeroed():
    t = EtaTracker()
    assert (t.total_distance, t.traveled, t.speed_mps) == (0.0, 0.0, 0.0)
    # total_distance == 0 -> progress short-circuits to 1.0
    assert t.progress == 1.0
    assert t.eta_seconds == 0.0
    assert t.eta_arrival == ""
    assert t.distance_remaining == 0.0


def test_start_clamps_speed_and_resets_traveled():
    t = EtaTracker()
    t.traveled = 50.0
    t.start(total_distance=1000.0, speed_mps=0.0)  # 0 -> clamped to 0.001
    assert t.total_distance == 1000.0
    assert t.traveled == 0.0
    assert t.speed_mps == 0.001


def test_progress_and_distance_remaining_math():
    t = EtaTracker()
    t.start(1000.0, 10.0)
    t.update(250.0)
    assert t.progress == 0.25
    assert t.distance_remaining == 750.0
    assert t.eta_seconds == 75.0  # 750 / 10


def test_progress_clamps_to_one_when_overshot():
    t = EtaTracker()
    t.start(100.0, 10.0)
    t.update(150.0)
    assert t.progress == 1.0
    assert t.distance_remaining == 0.0   # max(100-150, 0)
    assert t.eta_seconds == 0.0


def test_eta_arrival_empty_when_no_time_remaining():
    t = EtaTracker()
    t.start(100.0, 10.0)
    t.update(100.0)            # eta_seconds == 0 -> ''
    assert t.eta_arrival == ""


def test_eta_arrival_is_now_plus_eta_seconds(monkeypatch):
    """eta_arrival = datetime.now(utc) + timedelta(eta_seconds), iso 'seconds'."""
    fixed = datetime(2026, 6, 22, 12, 0, 0, tzinfo=timezone.utc)

    class _FixedDatetime:
        @staticmethod
        def now(tz=None):
            return fixed

    mod = importlib.import_module(EtaTracker.__module__)
    monkeypatch.setattr(mod, "datetime", _FixedDatetime)

    t = EtaTracker()
    t.start(1000.0, 10.0)
    t.update(0.0)             # eta_seconds == 100.0
    assert t.eta_arrival == "2026-06-22T12:01:40+00:00"
