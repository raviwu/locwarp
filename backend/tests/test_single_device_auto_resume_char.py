"""Characterization: single-device auto-resume (finding #2 / W1).

When the SOLE connected device drops mid-multi-stop, the usbmux watchdog captures
a resumable snapshot but the existing promotion path only resumes onto a SURVIVING
follower — a single device has no successor, so the snapshot was discarded and the
reconnected device got a position-less engine (manual restart then failed
"Cannot start multi-stop: no current position. Teleport first.").

These pin: (a) stash/take with a TTL and pop-once semantics, and (b)
create_engine_for_device's consume seam auto-resumes from a fresh stashed snapshot.
"""
import asyncio

import pytest

pytestmark = pytest.mark.asyncio


def _make_state(tmp_path, monkeypatch):
    # HOME isolation: redirect module-bound path constants so AppState()'s
    # DeviceManager reads only tmp files (mirrors the promotion char test).
    monkeypatch.setattr("core.device_manager.STICKY_DENIED_FILE", tmp_path / "sticky_denied.json")
    monkeypatch.setattr("core.device_manager.DEVICE_NAMES_FILE", tmp_path / "device_names.json")
    monkeypatch.setattr("core.device_manager.WIFI_ALIASES_FILE", tmp_path / "wifi_aliases.json")
    from main import AppState
    return AppState()


async def test_take_pending_resume_ttl_and_pop_once(tmp_path, monkeypatch):
    import time
    state = _make_state(tmp_path, monkeypatch)
    snap = {"kind": "multi_stop", "segment_index": 66, "args": {}}

    state.stash_pending_resume("udid-A", snap)
    # Fresh → returned once, then popped.
    assert state.take_pending_resume("udid-A") == snap
    assert state.take_pending_resume("udid-A") is None

    # Expired (timestamp older than the TTL) → dropped, not returned.
    state._pending_resume["udid-A"] = (snap, time.monotonic() - 10_000)
    assert state.take_pending_resume("udid-A") is None
    assert "udid-A" not in state._pending_resume


async def test_maybe_auto_resume_consumes_fresh_snapshot(tmp_path, monkeypatch):
    state = _make_state(tmp_path, monkeypatch)
    snap = {"kind": "multi_stop", "segment_index": 66, "args": {}}
    state.stash_pending_resume("udid-B", snap)

    captured: list[dict] = []

    class _FakeEngine:
        async def resume_from_snapshot(self, s):
            captured.append(s)

    await state._maybe_auto_resume("udid-B", _FakeEngine())
    await asyncio.sleep(0)  # let the scheduled resume task run

    assert captured == [snap]
    # Snapshot consumed — not left dangling for a later reconnect.
    assert state.take_pending_resume("udid-B") is None


async def test_maybe_auto_resume_noop_without_snapshot(tmp_path, monkeypatch):
    state = _make_state(tmp_path, monkeypatch)

    class _FakeEngine:
        async def resume_from_snapshot(self, s):
            raise AssertionError("must not resume when nothing is stashed")

    await state._maybe_auto_resume("udid-C", _FakeEngine())
    await asyncio.sleep(0)  # nothing should have been scheduled


async def test_no_current_position_guard_logged_clean_not_failed_unexpectedly(caplog):
    """A run started before any teleport raises the 'no current position' guard.
    _run_handler must log that expected precondition at WARNING (no traceback),
    not ERROR 'failed unexpectedly'."""
    import logging

    from tests._engine_harness import make_engine

    eng, _loc, _em = make_engine()

    async def _boom():
        raise RuntimeError("Cannot start multi-stop: no current position. Teleport first.")

    with caplog.at_level(logging.WARNING, logger="core.simulation_engine"):
        await eng._run_handler(_boom(), "Multi-stop")

    assert not any(
        r.levelno >= logging.ERROR and "failed unexpectedly" in r.getMessage()
        for r in caplog.records
    )
    assert any("no current position" in r.getMessage() for r in caplog.records)
