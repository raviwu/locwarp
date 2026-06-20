"""get_event_publisher resolves to the ONE injected publisher singleton."""
from main import app, app_state


def test_get_event_publisher_returns_container_singleton():
    from api.deps import get_event_publisher

    class _Req:
        class app:
            class state:
                container = app.state.container

    pub = get_event_publisher(_Req)
    assert pub is app.state.container.event_publisher
    assert pub is app_state.device_manager._events
