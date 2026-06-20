"""Characterization tests for services.coord_format.CoordinateFormatter.

These freeze the ACTUAL current behavior of the parser/formatter. Surprising
behaviors are asserted as-is and noted in comments:

* The module does NOT parse URL-embedded coordinates (``?ll=``, ``/@lat,lng``,
  ``!3d/!4d``) — those all return ``None``. URL parsing lives elsewhere.
* DMS / DM paths have NO out-of-range guard, so an out-of-range value raises
  pydantic ``ValidationError`` (not ``None``). Only the DD path range-checks
  and returns ``None`` when out of [-90,90] / [-180,180].
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from models.schemas import Coordinate, CoordinateFormat
from services.coord_format import CoordinateFormatter


# ---------------------------------------------------------------------------
# Parsing — DD (decimal degrees)
# ---------------------------------------------------------------------------


def test_parse_plain_dd_comma():
    c = CoordinateFormatter.parse_coord("25.033, 121.565")
    assert isinstance(c, Coordinate)
    assert c.lat == 25.033
    assert c.lng == 121.565


def test_parse_dd_with_degree_and_hemisphere():
    c = CoordinateFormatter.parse_coord("25.033°N, 121.565°E")
    assert c is not None
    assert c.lat == 25.033
    assert c.lng == 121.565


def test_parse_dd_negative_signs():
    c = CoordinateFormatter.parse_coord("-25.033, -121.565")
    assert c is not None
    assert c.lat == -25.033
    assert c.lng == -121.565


def test_parse_dd_south_west_hemisphere_negates():
    c = CoordinateFormatter.parse_coord("25.033S, 121.565W")
    assert c is not None
    assert c.lat == -25.033
    assert c.lng == -121.565


def test_parse_dd_lowercase_hemisphere():
    c = CoordinateFormatter.parse_coord("25.033s, 121.565w")
    assert c is not None
    assert c.lat == -25.033
    assert c.lng == -121.565


def test_parse_dd_semicolon_separator():
    c = CoordinateFormatter.parse_coord("25.033;121.565")
    assert c is not None
    assert c.lat == 25.033
    assert c.lng == 121.565


def test_parse_dd_whitespace_separator():
    c = CoordinateFormatter.parse_coord("25.033 121.565")
    assert c is not None
    assert c.lat == 25.033
    assert c.lng == 121.565


def test_parse_dd_strips_surrounding_whitespace():
    c = CoordinateFormatter.parse_coord("  25.033, 121.565  ")
    assert c is not None
    assert c.lat == 25.033


def test_parse_dd_ignores_trailing_tokens():
    # Trailing ", 15z" is simply not consumed by re.match — still parses.
    c = CoordinateFormatter.parse_coord("25.033, 121.565, 15z")
    assert c is not None
    assert c.lat == 25.033
    assert c.lng == 121.565


def test_parse_dd_boundary_values_inclusive():
    c = CoordinateFormatter.parse_coord("90, 180")
    assert c is not None
    assert c.lat == 90.0
    assert c.lng == 180.0

    c2 = CoordinateFormatter.parse_coord("-90, -180")
    assert c2 is not None
    assert c2.lat == -90.0
    assert c2.lng == -180.0


# ---------------------------------------------------------------------------
# Parsing — DMS
# ---------------------------------------------------------------------------


def test_parse_dms_basic():
    c = CoordinateFormatter.parse_coord("25°2'1.5\"N, 121°33'52.3\"E")
    assert c is not None
    assert c.lat == pytest.approx(25 + 2 / 60 + 1.5 / 3600)
    assert c.lng == pytest.approx(121 + 33 / 60 + 52.3 / 3600)


def test_parse_dms_south_west():
    c = CoordinateFormatter.parse_coord("25°2'1.5\"S, 121°33'52.3\"W")
    assert c is not None
    assert c.lat < 0
    assert c.lng < 0
    assert c.lat == pytest.approx(-(25 + 2 / 60 + 1.5 / 3600))


def test_parse_dms_unicode_prime_and_double_prime():
    # Uses U+2032 prime and U+2033 double-prime instead of ASCII ' and ".
    c = CoordinateFormatter.parse_coord(
        "25°2′1.5″N, 121°33′52.3″E"
    )
    assert c is not None
    assert c.lat == pytest.approx(25 + 2 / 60 + 1.5 / 3600)


def test_parse_dms_out_of_range_raises_validation_error():
    # No range guard on the DMS path -> pydantic rejects lat>90.
    with pytest.raises(ValidationError):
        CoordinateFormatter.parse_coord("91°0'0\"N, 0°0'0\"E")


# ---------------------------------------------------------------------------
# Parsing — DM (degrees + decimal minutes)
# ---------------------------------------------------------------------------


def test_parse_dm_basic():
    c = CoordinateFormatter.parse_coord("25°2.025'N, 121°33.872'E")
    assert c is not None
    assert c.lat == pytest.approx(25 + 2.025 / 60)
    assert c.lng == pytest.approx(121 + 33.872 / 60)


def test_parse_dm_south_west():
    c = CoordinateFormatter.parse_coord("25°2.025'S, 121°33.872'W")
    assert c is not None
    assert c.lat == pytest.approx(-(25 + 2.025 / 60))
    assert c.lng == pytest.approx(-(121 + 33.872 / 60))


def test_parse_dm_out_of_range_raises_validation_error():
    with pytest.raises(ValidationError):
        CoordinateFormatter.parse_coord("0°0'N, 200°0'E")


# ---------------------------------------------------------------------------
# Parsing — malformed / unsupported -> None
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "not a coord",
        "abc, def",
        "25.033",  # only one number
        "25.033,",  # trailing comma, no second value
        "25.0.3, 121.5",  # malformed float -> ValueError caught -> None
    ],
)
def test_parse_malformed_returns_none(text):
    assert CoordinateFormatter.parse_coord(text) is None


@pytest.mark.parametrize(
    "text",
    [
        "999, 999",  # both out of DD range
        "91, 200",  # lat and lng out of range
        "0, 181",  # lng just out of range
        "91, 0",  # lat just out of range
    ],
)
def test_parse_dd_out_of_range_returns_none(text):
    # DD path DOES range-check (unlike DMS/DM) and returns None.
    assert CoordinateFormatter.parse_coord(text) is None


@pytest.mark.parametrize(
    "text",
    [
        "https://maps.google.com/@25.033,121.565,15z",  # /@lat,lng URL
        "?ll=25.033,121.565",  # ?ll= URL param
        "!3d25.033!4d121.565",  # !3d/!4d URL fragment
    ],
)
def test_parse_url_embedded_not_supported_returns_none(text):
    # This module does NOT parse URL-embedded coordinates. Documented here as
    # a behavior freeze: such parsing lives in another module, not here.
    assert CoordinateFormatter.parse_coord(text) is None


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def test_default_format_is_dd():
    assert CoordinateFormatter().format == CoordinateFormat.DD


def test_format_coord_dd():
    f = CoordinateFormatter()
    assert f.format_coord(25.033, 121.565) == "25.033000°N, 121.565000°E"


def test_format_lat_negative_uses_south():
    f = CoordinateFormatter()
    assert f.format_lat(-25.033) == "25.033000°S"


def test_format_lng_negative_uses_west():
    f = CoordinateFormatter()
    assert f.format_lng(-121.565) == "121.565000°W"


def test_format_lat_zero_is_north():
    # lat >= 0 -> "N", so exactly zero formats as N.
    f = CoordinateFormatter()
    assert f.format_lat(0.0) == "0.000000°N"


def test_format_coord_dms():
    f = CoordinateFormatter()
    f.format = CoordinateFormat.DMS
    assert f.format_coord(25.033, -121.565) == "25°1'58.80\"N, 121°33'54.00\"W"


def test_format_coord_dm():
    f = CoordinateFormatter()
    f.format = CoordinateFormat.DM
    assert f.format_coord(25.033, 121.565) == "25°1.9800'N, 121°33.9000'E"


def test_format_value_unknown_format_falls_back_to_dd():
    # _format_value has a fallthrough return for an unrecognized format value.
    f = CoordinateFormatter()
    f.format = "bogus"  # type: ignore[assignment]
    assert f.format_lat(25.033) == "25.033000°N"


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------


def test_dd_to_dms():
    assert CoordinateFormatter._dd_to_dms(25.0337) == (25, 2, 1.32)


def test_dd_to_dms_whole_degree():
    assert CoordinateFormatter._dd_to_dms(10.0) == (10, 0, 0.0)


def test_dd_to_dm():
    assert CoordinateFormatter._dd_to_dm(25.0337) == (25, 2.022)


def test_dd_to_dm_whole_degree():
    assert CoordinateFormatter._dd_to_dm(10.0) == (10, 0.0)


# ---------------------------------------------------------------------------
# Round trip: format then parse (DD)
# ---------------------------------------------------------------------------


def test_round_trip_dd():
    f = CoordinateFormatter()
    formatted = f.format_coord(25.033, 121.565)
    parsed = CoordinateFormatter.parse_coord(formatted)
    assert parsed is not None
    assert parsed.lat == pytest.approx(25.033)
    assert parsed.lng == pytest.approx(121.565)
