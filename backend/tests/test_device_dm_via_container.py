"""api/device.py module-level accessors resolve dm / engines / helper from the
DI container, never via `from main import ...`."""
from pathlib import Path

import bootstrap.runtime as runtime
import api.device as device


def test_dm_and_engines_and_helper_read_container(monkeypatch):
    class _FakeDM: pass
    class _FakeEngines: pass
    class _FakeHelper: pass

    class _FakeContainer:
        device_manager = _FakeDM()
        engine_registry = _FakeEngines()
        helper_client = _FakeHelper()

    fake = _FakeContainer()
    monkeypatch.setattr(runtime, "_CONTAINER", fake)
    assert device._dm() is fake.device_manager
    assert device._engines() is fake.engine_registry
    assert device._helper() is fake.helper_client


def test_device_source_has_no_main_import_at_migrated_sites():
    src = Path(device.__file__).read_text()
    assert "from main import app_state" not in src
    assert "from main import helper_client" not in src
