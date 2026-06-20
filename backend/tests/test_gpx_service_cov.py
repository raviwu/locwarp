"""Characterization tests for services.gpx_service.

These freeze the CURRENT behavior of GpxService.parse_gpx / generate_gpx,
including the track > route > waypoint precedence, elevation/timestamp
handling, and the actual exceptions raised on bad input. Pure / offline —
no network, no clock dependency.
"""

from __future__ import annotations

from datetime import datetime

import gpxpy.gpx
import pytest

from models.schemas import Coordinate
from services.gpx_service import GpxService


# ---------------------------------------------------------------------------
# parse_gpx
# ---------------------------------------------------------------------------


def _gpx(body: str) -> str:
    return (
        '<?xml version="1.0"?>'
        '<gpx version="1.1" creator="test">' + body + "</gpx>"
    )


def test_parse_waypoints_only():
    xml = _gpx('<wpt lat="25.0" lon="121.5"></wpt>')
    coords = GpxService.parse_gpx(xml)
    assert coords == [Coordinate(lat=25.0, lng=121.5)]


def test_parse_track_points():
    xml = _gpx(
        "<trk><trkseg>"
        '<trkpt lat="1.0" lon="2.0"></trkpt>'
        '<trkpt lat="3.0" lon="4.0"></trkpt>'
        "</trkseg></trk>"
    )
    coords = GpxService.parse_gpx(xml)
    assert coords == [Coordinate(lat=1.0, lng=2.0), Coordinate(lat=3.0, lng=4.0)]


def test_parse_route_points():
    xml = _gpx('<rte><rtept lat="50.0" lon="60.0"></rtept></rte>')
    coords = GpxService.parse_gpx(xml)
    assert coords == [Coordinate(lat=50.0, lng=60.0)]


def test_track_wins_over_route_and_waypoint():
    """When tracks exist, route/waypoint are ignored entirely."""
    xml = _gpx(
        '<wpt lat="99.0" lon="99.0"></wpt>'
        '<rte><rtept lat="50.0" lon="60.0"></rtept></rte>'
        "<trk><trkseg>"
        '<trkpt lat="1.0" lon="2.0"></trkpt>'
        '<trkpt lat="3.0" lon="4.0"></trkpt>'
        "</trkseg></trk>"
    )
    coords = GpxService.parse_gpx(xml)
    assert coords == [Coordinate(lat=1.0, lng=2.0), Coordinate(lat=3.0, lng=4.0)]


def test_route_wins_over_waypoint():
    """With no tracks but a route present, waypoints are ignored."""
    xml = _gpx(
        '<wpt lat="99.0" lon="99.0"></wpt>'
        '<rte><rtept lat="50.0" lon="60.0"></rtept></rte>'
    )
    coords = GpxService.parse_gpx(xml)
    assert coords == [Coordinate(lat=50.0, lng=60.0)]


def test_parse_empty_gpx_returns_empty_list():
    coords = GpxService.parse_gpx(_gpx(""))
    assert coords == []


def test_parse_multi_segment_track_flattens():
    xml = _gpx(
        "<trk>"
        '<trkseg><trkpt lat="1.0" lon="1.0"></trkpt></trkseg>'
        '<trkseg><trkpt lat="2.0" lon="2.0"></trkpt></trkseg>'
        "</trk>"
    )
    coords = GpxService.parse_gpx(xml)
    assert coords == [Coordinate(lat=1.0, lng=1.0), Coordinate(lat=2.0, lng=2.0)]


def test_parse_malformed_raises_syntax_exception():
    with pytest.raises(gpxpy.gpx.GPXXMLSyntaxException):
        GpxService.parse_gpx("not xml at all")


def test_parse_out_of_range_lat_raises_validation_error():
    """Coordinate(ge=-90,le=90) rejects an out-of-range waypoint lat."""
    from pydantic import ValidationError

    xml = _gpx('<wpt lat="99.0" lon="0.0"></wpt>')
    with pytest.raises(ValidationError):
        GpxService.parse_gpx(xml)


# ---------------------------------------------------------------------------
# generate_gpx
# ---------------------------------------------------------------------------


def test_generate_default_name():
    xml = GpxService.generate_gpx([{"lat": 1.0, "lng": 2.0}])
    assert "<name>LocWarp Route</name>" in xml
    assert "<gpx" in xml


def test_generate_custom_name():
    xml = GpxService.generate_gpx([{"lat": 1.0, "lng": 2.0}], name="MyTrip")
    assert "<name>MyTrip</name>" in xml


def test_generate_emits_trkpt_coordinates():
    xml = GpxService.generate_gpx([{"lat": 10.5, "lng": 20.5}])
    assert 'lat="10.5"' in xml
    assert 'lon="20.5"' in xml


def test_generate_iso_timestamp_string_written():
    xml = GpxService.generate_gpx(
        [{"lat": 1.0, "lng": 2.0, "timestamp": "2020-01-01T00:00:00"}]
    )
    assert "2020-01-01" in xml
    assert "<time>" in xml


def test_generate_bad_timestamp_string_omits_time():
    """A non-ISO string is swallowed -> no <time> element."""
    xml = GpxService.generate_gpx(
        [{"lat": 1.0, "lng": 2.0, "timestamp": "not-a-date"}]
    )
    assert "<time>" not in xml


def test_generate_naive_datetime_gets_utc():
    xml = GpxService.generate_gpx(
        [{"lat": 1.0, "lng": 2.0, "timestamp": datetime(2021, 5, 5, 12, 0, 0)}]
    )
    assert "2021-05-05" in xml
    # naive datetime is stamped tzinfo=utc -> serialized with Z or +00:00
    assert ("Z" in xml) or ("+00:00" in xml)


def test_generate_elevation_key():
    xml = GpxService.generate_gpx([{"lat": 1.0, "lng": 2.0, "elevation": 100}])
    assert "<ele>100" in xml


def test_generate_ele_alias_key():
    xml = GpxService.generate_gpx([{"lat": 1.0, "lng": 2.0, "ele": 55}])
    assert "<ele>55" in xml


def test_generate_no_elevation_omits_ele():
    xml = GpxService.generate_gpx([{"lat": 1.0, "lng": 2.0}])
    assert "<ele>" not in xml


def test_generate_empty_coords_still_valid_gpx():
    xml = GpxService.generate_gpx([])
    assert isinstance(xml, str)
    assert "<gpx" in xml
    assert "<trkpt" not in xml


def test_generate_missing_lat_raises_keyerror():
    with pytest.raises(KeyError):
        GpxService.generate_gpx([{"lng": 2.0}])


def test_roundtrip_generate_then_parse():
    src = [{"lat": 10.5, "lng": 20.5}, {"lat": 11.0, "lng": 21.0}]
    xml = GpxService.generate_gpx(src)
    coords = GpxService.parse_gpx(xml)
    assert coords == [
        Coordinate(lat=10.5, lng=20.5),
        Coordinate(lat=11.0, lng=21.0),
    ]
