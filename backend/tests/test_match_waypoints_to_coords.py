"""Pin the pure waypoint->coord-index match extracted from
SimulationEngine._move_along_route (the wp_seg_idx precompute). Monotonic
forward scan with early break when a waypoint can't be matched further
along than the previous one (the multi_stop later-leg cutoff)."""
from models.schemas import Coordinate
from domain.movement import match_waypoints_to_coords


def _c(lat, lng):
    return Coordinate(lat=lat, lng=lng)


def test_each_waypoint_maps_to_nearest_forward_coord():
    # planned coords are a straight east-west line; waypoints sit ON coords 1 and 3.
    planned = [_c(25.0, 121.000), _c(25.0, 121.001), _c(25.0, 121.002),
               _c(25.0, 121.003), _c(25.0, 121.004)]
    user_wps = [_c(25.0, 121.001), _c(25.0, 121.003)]
    assert match_waypoints_to_coords(user_wps, planned, start_index=0) == [1, 3]


def test_start_index_skips_already_consumed_waypoints():
    planned = [_c(25.0, 121.000), _c(25.0, 121.001), _c(25.0, 121.002)]
    user_wps = [_c(25.0, 121.000), _c(25.0, 121.002)]
    # start at index 1 -> only the second waypoint is scanned, from coord 0.
    assert match_waypoints_to_coords(user_wps, planned, start_index=1) == [2]


def test_second_waypoint_scans_strictly_after_the_first():
    # wp0 best-matches coord 2; wp1 then scans from coord 3 onward (last_ci+1),
    # so even though coord 3 is the only remaining candidate it is chosen there.
    planned = [_c(25.0, 121.000), _c(25.0, 121.001), _c(25.0, 121.002),
               _c(25.0, 121.010)]
    user_wps = [_c(25.0, 121.002), _c(25.0, 121.0105)]
    assert match_waypoints_to_coords(user_wps, planned, start_index=0) == [2, 3]


def test_empty_waypoints_returns_empty():
    planned = [_c(25.0, 121.0), _c(25.0, 121.001)]
    assert match_waypoints_to_coords([], planned, start_index=0) == []


def test_break_when_no_coords_remain_to_scan():
    # first wp -> coord 0; second wp scans from coord 1 (range empty) ->
    # best_ci stays -1 -> break, so only [0] is returned.
    planned = [_c(25.0, 121.0)]
    user_wps = [_c(25.0, 121.0), _c(25.0, 121.5)]
    assert match_waypoints_to_coords(user_wps, planned, start_index=0) == [0]
