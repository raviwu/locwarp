"""Timing-aware GPX import/export round-trip.

- parse_gpx_timed extracts per-point seconds-from-start offsets from <time>.
- timing-less GPX yields empty offsets (profile-speed fallback downstream).
- /route/gpx/import populates SavedRoute.timestamps.
- export reproduces <time> when the route carries timestamps.
Pure / offline — no network, no clock.
"""
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from models.schemas import Coordinate, SavedRoute
from services.gpx_service import GpxService


def _gpx(body: str) -> str:
    return ('<?xml version="1.0"?>'
            '<gpx version="1.1" creator="test">' + body + "</gpx>")


def test_parse_gpx_timed_extracts_offsets_from_track_time():
    xml = _gpx(
        "<trk><trkseg>"
        '<trkpt lat="1.0" lon="2.0"><time>2020-01-01T00:00:00Z</time></trkpt>'
        '<trkpt lat="3.0" lon="4.0"><time>2020-01-01T00:00:10Z</time></trkpt>'
        '<trkpt lat="5.0" lon="6.0"><time>2020-01-01T00:00:25Z</time></trkpt>'
        "</trkseg></trk>"
    )
    coords, offsets = GpxService.parse_gpx_timed(xml)
    assert coords == [
        Coordinate(lat=1.0, lng=2.0),
        Coordinate(lat=3.0, lng=4.0),
        Coordinate(lat=5.0, lng=6.0),
    ]
    assert offsets == [0.0, 10.0, 25.0]


def test_parse_gpx_timed_no_time_yields_empty_offsets():
    xml = _gpx(
        "<trk><trkseg>"
        '<trkpt lat="1.0" lon="2.0"></trkpt>'
        '<trkpt lat="3.0" lon="4.0"></trkpt>'
        "</trkseg></trk>"
    )
    coords, offsets = GpxService.parse_gpx_timed(xml)
    assert len(coords) == 2
    assert offsets == []


def test_parse_gpx_timed_partial_time_yields_empty_offsets():
    """If ANY track point lacks <time>, fall back to no timing."""
    xml = _gpx(
        "<trk><trkseg>"
        '<trkpt lat="1.0" lon="2.0"><time>2020-01-01T00:00:00Z</time></trkpt>'
        '<trkpt lat="3.0" lon="4.0"></trkpt>'
        "</trkseg></trk>"
    )
    coords, offsets = GpxService.parse_gpx_timed(xml)
    assert len(coords) == 2
    assert offsets == []


def test_parse_gpx_still_returns_bare_coords():
    """The bare parse_gpx is unchanged (regression guard for cov tests)."""
    xml = _gpx(
        "<trk><trkseg>"
        '<trkpt lat="1.0" lon="2.0"><time>2020-01-01T00:00:00Z</time></trkpt>'
        '<trkpt lat="3.0" lon="4.0"><time>2020-01-01T00:00:10Z</time></trkpt>'
        "</trkseg></trk>"
    )
    assert GpxService.parse_gpx(xml) == [
        Coordinate(lat=1.0, lng=2.0), Coordinate(lat=3.0, lng=4.0),
    ]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("services.route_store.ROUTES_FILE", tmp_path / "routes.json")
    import main
    from bootstrap.factories import make_route_manager
    main.app_state.route_manager = make_route_manager()
    return TestClient(main.app)


def test_import_populates_timestamps(client):
    xml = _gpx(
        "<trk><trkseg>"
        '<trkpt lat="1.0" lon="2.0"><time>2020-01-01T00:00:00Z</time></trkpt>'
        '<trkpt lat="3.0" lon="4.0"><time>2020-01-01T00:00:10Z</time></trkpt>'
        "</trkseg></trk>"
    )
    files = {"file": ("trip.gpx", io.BytesIO(xml.encode()), "application/gpx+xml")}
    res = client.post("/api/route/gpx/import", files=files)
    assert res.status_code == 200
    rid = res.json()["id"]
    saved = next(r for r in client.get("/api/route/saved").json() if r["id"] == rid)
    assert saved["timestamps"] == [0.0, 10.0]


def test_export_reproduces_time_when_route_has_timestamps():
    route = SavedRoute(
        name="Timed",
        waypoints=[Coordinate(lat=1.0, lng=2.0), Coordinate(lat=3.0, lng=4.0)],
        timestamps=[0.0, 10.0],
    )
    # Build the export point dicts the way api.route.export_gpx will (Task 8 step 5).
    base_ts = "2020-01-01T00:00:00+00:00"
    from datetime import datetime, timezone, timedelta
    base = datetime(2020, 1, 1, tzinfo=timezone.utc)
    points = [
        {"lat": c.lat, "lng": c.lng,
         "timestamp": (base + timedelta(seconds=route.timestamps[i])).isoformat()}
        for i, c in enumerate(route.waypoints)
    ]
    xml = GpxService.generate_gpx(points, name=route.name)
    assert "<time>" in xml
    assert "2020-01-01T00:00:00" in xml
    assert "2020-01-01T00:00:10" in xml
