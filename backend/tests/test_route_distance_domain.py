from domain.route_distance import (
    straight_line_distance_m,
    route_distance_fingerprint,
    decimate_waypoints,
)
from models.schemas import Coordinate


def _wp(lat, lng):
    return Coordinate(lat=lat, lng=lng)


def test_straight_line_distance_sums_haversine():
    # 0/1 waypoint -> 0.0
    assert straight_line_distance_m([]) == 0.0
    assert straight_line_distance_m([_wp(25.0, 121.0)]) == 0.0
    # Two points ~157 km apart (1 deg lat ~111 km, plus lng) -> positive, sane
    d = straight_line_distance_m([_wp(25.0, 121.0), _wp(26.0, 122.0)])
    assert 100_000 < d < 200_000


def test_fingerprint_stable_and_path_sensitive():
    a = [_wp(25.0, 121.0), _wp(26.0, 122.0)]
    assert route_distance_fingerprint(a, "walking") == route_distance_fingerprint(a, "walking")
    # profile change flips it
    assert route_distance_fingerprint(a, "walking") != route_distance_fingerprint(a, "driving")
    # waypoint move flips it
    b = [_wp(25.0, 121.0), _wp(26.1, 122.0)]
    assert route_distance_fingerprint(a, "walking") != route_distance_fingerprint(b, "walking")


def test_decimate_keeps_endpoints_and_caps_count():
    pts = [_wp(0.0, float(i)) for i in range(100)]
    out = decimate_waypoints(pts, 25)
    assert len(out) <= 25
    assert out[0] is pts[0] and out[-1] is pts[-1]
    # short routes pass through unchanged
    short = [_wp(0.0, 0.0), _wp(0.0, 1.0)]
    assert decimate_waypoints(short, 25) == short
    # degenerate max_n guard -> returns all
    assert decimate_waypoints(pts, 1) == pts
