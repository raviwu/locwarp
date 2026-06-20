"""The injected container.engine_registry IS main.app_state."""


def test_container_engine_registry_is_app_state():
    from main import app, app_state
    assert app.state.container.engine_registry is app_state


def test_engine_registry_exposes_expected_surface():
    from main import app
    reg = app.state.container.engine_registry
    assert hasattr(reg, "simulation_engines")
    assert hasattr(reg, "_primary_udid")
    assert hasattr(reg, "_engines_lock")
    assert callable(reg.get_engine)
    assert callable(reg.create_engine_for_device)
    assert callable(reg.remove_engine)  # added in Group 2
