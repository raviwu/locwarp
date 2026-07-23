"""Coordinate precision policy (pure domain rule).

Stored bookmark coordinates are rounded so no bookmark persists a long,
drifted coordinate. 7 decimals ≈ 1.1 cm — finer than any GPS fix and finer
than any coordinate a human types or a map URL provides, so real input is
preserved exactly while the full-float64 tail introduced by GPS jitter,
route interpolation, or map-pixel projection (13–16 decimals) is stripped.
"""
from __future__ import annotations

COORD_PRECISION = 7


def round_coord(value: float) -> float:
    """Round a latitude or longitude to COORD_PRECISION decimal places."""
    return round(value, COORD_PRECISION)
