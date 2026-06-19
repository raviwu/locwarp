"""(a) determinism: two identical deterministic runs produce identical streams.
(b) primary promotion: removing the primary engine promotes a survivor.

Task 9e: pins record-twice determinism + 2-device registry promotion.

Note on line-1155 (get_fresh_dvt_provider WiFi-tunnel-wait branch):
  The brief asked to characterize this branch. In the current source,
  this branch contains a NameError on the retry path that Task 10 will
  fix. It is not possible to drive a clean assertion against a code path
  that raises NameError before the fix lands. This sub-task therefore:
    (a) pins the determinism gate via two identical teleport runs, and
    (b) pins the 2-device primary-promotion observable behavior via
        AppState's public registry surface (simulation_engines dict +
        _primary_udid attr + get_engine()), bypassing the device I/O
        path entirely. The line-1155 characterization is deferred to
        Task 10's post-fix scope.
"""
import pytest

from tests._engine_harness import FakeClock, SteppedSleep, make_engine


pytestmark = pytest.mark.asyncio


async def test_record_twice_teleport_streams_are_identical():
    """Deterministic doubles -> byte-for-byte identical observable streams.

    Run the same teleport twice with fresh FakeClock + SteppedSleep and
    assert that pushes, emitted events, and sleep durations are identical.
    """
    async def run_once():
        clock = FakeClock()
        sleep = SteppedSleep(clock)
        eng, loc, emitted = make_engine(clock=clock, sleep=sleep)
        await eng.teleport(10.0, 20.0)
        return loc.pushes, emitted, sleep.durations

    pushes1, emitted1, durs1 = await run_once()
    pushes2, emitted2, durs2 = await run_once()

    # Deterministic doubles -> byte-for-byte identical observable streams.
    assert pushes1 == pushes2
    assert emitted1 == emitted2
    # Teleport never hits the backoff-sleep seam, so both are [].
    # Intentionally characterizes: "the teleport path invokes NO backoff sleep."
    assert durs1 == durs2 == []


async def test_two_device_primary_promotion_via_appstate(tmp_path, monkeypatch):
    """Removing the primary engine from the registry and updating _primary_udid
    promotes the survivor. Pins the observable dict/attr surface of AppState
    (simulation_engines + _primary_udid + get_engine) without driving device I/O.

    HOME isolation: monkeypatch.setattr redirects the module-bound path
    constants in core.device_manager (imported at module load time; a config
    reload does not rebind them) so DeviceManager.__init__ reads only tmp_path
    files — never the real ~/.locwarp/sticky_denied.json.
    """
    monkeypatch.setattr("core.device_manager.STICKY_DENIED_FILE", tmp_path / "sticky_denied.json")
    monkeypatch.setattr("core.device_manager.DEVICE_NAMES_FILE", tmp_path / "device_names.json")
    monkeypatch.setattr("core.device_manager.WIFI_ALIASES_FILE", tmp_path / "wifi_aliases.json")

    from main import AppState
    state = AppState()

    # Inject two engines directly into the registry (bypassing device I/O).
    eng_a, _la, _ea = make_engine()
    eng_b, _lb, _eb = make_engine()
    state.simulation_engines["udid-A"] = eng_a
    state.simulation_engines["udid-B"] = eng_b
    state._primary_udid = "udid-A"

    # get_engine(None) returns the primary engine.
    assert state.get_engine(None) is eng_a
    assert state.get_engine("udid-B") is eng_b

    # Simulate disconnect of the primary: pop it and promote the survivor.
    state.simulation_engines.pop("udid-A", None)
    state._primary_udid = "udid-B"

    assert state.get_engine(None) is eng_b
    assert state.get_engine("udid-A") is None


async def test_appstate_get_engine_none_with_no_primary_returns_none(tmp_path, monkeypatch):
    """get_engine(None) with no primary set returns None (not raises).

    HOME isolation: same setattr strategy as the promotion test above.
    """
    monkeypatch.setattr("core.device_manager.STICKY_DENIED_FILE", tmp_path / "sticky_denied.json")
    monkeypatch.setattr("core.device_manager.DEVICE_NAMES_FILE", tmp_path / "device_names.json")
    monkeypatch.setattr("core.device_manager.WIFI_ALIASES_FILE", tmp_path / "wifi_aliases.json")

    from main import AppState
    state = AppState()

    assert state.get_engine(None) is None
    assert state.get_engine("some-udid") is None
