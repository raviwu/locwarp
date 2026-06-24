"""The simulation_engine setter only supports `= None` (clear all). Assigning
a real engine is a programming error (engines are created via
create_engine_for_device) and must raise, not silently stash under __legacy__.
"""
from __future__ import annotations

import pytest


def _fresh_appstate():
    from main import AppState
    return AppState()


def test_setter_none_clears_all_engines():
    st = _fresh_appstate()
    st.simulation_engines["UDID-X"] = object()
    st._primary_udid = "UDID-X"
    st.simulation_engine = None
    assert st.simulation_engines == {}
    assert st._primary_udid is None


def test_setter_non_none_raises_and_does_not_stash_legacy():
    st = _fresh_appstate()
    with pytest.raises(TypeError):
        st.simulation_engine = object()
    assert "__legacy__" not in st.simulation_engines
