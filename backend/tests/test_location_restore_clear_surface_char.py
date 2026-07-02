"""Interactive /restore must SURFACE a device clear() failure, not report a
false 200 {"status":"restored"} while the phone may still be simulated.

The fix makes the interactive path opt into restore(raise_on_clear_failure=True)
(matching Gold Ditto) and maps a non-device-lost clear failure to 503
restore_failed."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.asyncio


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


def test_restore_surfaces_clear_failure_instead_of_false_success(client):
    from main import app_state
    dm = app_state.device_manager
    resolved = "UDID-RESTORE-CLEARFAIL"

    async def fake_restore(raise_on_clear_failure: bool = False):
        # Lenient (the bug) would swallow and return → false 200 "restored".
        # Strict (the fix) raises a NON-device-lost clear error.
        if raise_on_clear_failure:
            raise RuntimeError("clear failed")

    fake_engine = MagicMock()
    fake_engine.restore = fake_restore  # real coroutine fn honoring the kwarg

    async def fake_engine_resolver(u=None, registry=None):
        app_state._primary_udid = resolved
        return fake_engine

    with (
        patch("api.location._engine", fake_engine_resolver),
        patch.object(dm, "_connections", {resolved: object()}),
        patch.object(dm, "full_reconnect", new=AsyncMock(return_value=False)),
        patch.object(app_state, "_primary_udid", None),
    ):
        resp = client.post("/api/location/restore")

    assert resp.status_code == 503, f"expected 503, got {resp.status_code}: {resp.json()}"
    assert resp.json()["detail"]["code"] == "restore_failed"
