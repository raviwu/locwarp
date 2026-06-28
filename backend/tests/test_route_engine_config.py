import config
from services.route_service import _osrm_headers


def test_default_engine_is_fossgis_not_demo():
    assert config.DEFAULT_ROUTE_ENGINE == config.ROUTE_ENGINE_OSRM_FOSSGIS
    assert config.DEFAULT_ROUTE_ENGINE != config.ROUTE_ENGINE_OSRM


def test_road_compute_tunables_present():
    assert isinstance(config.ROAD_MAX_WAYPOINTS, int) and config.ROAD_MAX_WAYPOINTS >= 2
    assert config.ROAD_COMPUTE_TIMEOUT_S > 0
    assert len(config.ROAD_RETRY_BACKOFF_S) >= 1


def test_fossgis_requests_carry_x_client_id():
    assert _osrm_headers(config.ROUTE_ENGINE_OSRM_FOSSGIS) == {"X-Client-Id": "LocWarp"}
    # the no-SLA demo path adds no identifying header
    assert _osrm_headers(config.ROUTE_ENGINE_OSRM) == {}
