"""Characterization test for services.coord_format.CoordinateFormatter.

The DD/DMS/DM parser + formatter + conversion helpers were deleted as dead
code (only this test exercised them; production reads ONLY `.format`). What
remains is a thin holder for the persisted UI coord-format preference, wired
through the DI container and echoed in the WS settings payload + the REST
GET/PUT /settings/coord-format endpoints. This test freezes that surface.
"""

from __future__ import annotations

from models.schemas import CoordinateFormat
from services.coord_format import CoordinateFormatter


def test_default_format_is_dd():
    assert CoordinateFormatter().format == CoordinateFormat.DD


def test_format_attribute_is_assignable():
    # main.py load_state assigns `.format = CoordinateFormat(fmt)` from the
    # persisted settings; api/location.py PUT assigns `.format = req.format`.
    f = CoordinateFormatter()
    f.format = CoordinateFormat.DMS
    assert f.format.value == "dms"
