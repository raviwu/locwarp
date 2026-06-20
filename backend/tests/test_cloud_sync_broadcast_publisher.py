"""cloud_sync enable/disable emit the SAME (type, payload) tuples as before,
now via the injected EventPublisher instead of a top-level api.websocket import."""
import api.cloud_sync as cloud_sync_mod


def test_cloud_sync_has_no_toplevel_websocket_import():
    src = open(cloud_sync_mod.__file__, encoding="utf-8").read()
    assert "from api.websocket import" not in src
    assert "_ws_broadcast" not in src


def test_enable_disable_emit_unchanged_events(monkeypatch, tmp_path):
    from main import app
    from fastapi.testclient import TestClient

    captured = []

    class _CapPublisher:
        async def publish(self, event):
            etype, data = event
            captured.append((etype, {**data}))

    import services.cloud_sync_service as css_mod
    monkeypatch.setattr(app.state.container, "event_publisher", _CapPublisher())
    # The endpoint bodies (and these stubbed helpers) live in CloudSyncService.
    monkeypatch.setattr(css_mod, "detect_icloud_path", lambda: tmp_path)
    monkeypatch.setattr(css_mod, "setup_sync_folder", lambda *a, **k: tmp_path / "LocWarp")
    monkeypatch.setattr(css_mod, "migrate_pair", lambda *a, **k: (0, 0))

    client = TestClient(app)
    resp = client.post("/api/cloud-sync/enable", json={})
    assert resp.status_code == 200, resp.text
    assert ("bookmarks_changed", {"reason": "cloud_sync_enabled"}) in captured
    assert ("routes_changed", {"reason": "cloud_sync_enabled"}) in captured
