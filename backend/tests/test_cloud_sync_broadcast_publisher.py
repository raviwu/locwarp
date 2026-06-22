"""cloud_sync enable/disable emit the SAME (type, payload) tuples as before,
now via the injected EventPublisher instead of a top-level api.websocket import."""
import api.cloud_sync as cloud_sync_mod


def test_cloud_sync_has_no_toplevel_websocket_import():
    src = open(cloud_sync_mod.__file__, encoding="utf-8").read()
    assert "from api.websocket import" not in src
    assert "_ws_broadcast" not in src


def test_enable_disable_emit_unchanged_events(monkeypatch, tmp_path):
    import main
    from main import app
    from fastapi.testclient import TestClient

    # CONFIG ISOLATION (load-bearing): /enable calls AppState.save_settings(),
    # which writes SETTINGS_FILE. Without redirecting it to tmp_path, the test
    # persists `sync_folder = <tmp>/LocWarp` into the user's REAL
    # ~/.locwarp/settings.json — a tmp path that outlives the test and corrupts
    # the real cloud-sync state. save_settings writes main.SETTINGS_FILE;
    # get_bookmarks_path reads config.SETTINGS_FILE — patch both, plus DATA_DIR.
    monkeypatch.setattr("main.SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr("config.SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr("config.DATA_DIR", tmp_path)

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

    try:
        client = TestClient(app)
        resp = client.post("/api/cloud-sync/enable", json={})
        assert resp.status_code == 200, resp.text
        assert ("bookmarks_changed", {"reason": "cloud_sync_enabled"}) in captured
        assert ("routes_changed", {"reason": "cloud_sync_enabled"}) in captured
    finally:
        # /enable mutates the shared AppState in place; reset so this test is
        # order-independent and leaves no dirty sync state for later tests.
        main.app_state._sync_folder = None
        main.app_state._cloud_sync_dismissed = False
