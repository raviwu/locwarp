"""Persisted coordinate-format preference (DD / DMS / DM).

The DD/DMS/DM parser + formatter once lived here but was dead code: production
only ever reads/writes `.format`. The parser is gone; this is now a thin
holder for the user's persisted coord-format choice, wired through the DI
container (bootstrap/container.py) and surfaced via the WS settings payload
and the REST GET/PUT /api/settings/coord-format endpoints.
"""

from __future__ import annotations

from models.schemas import CoordinateFormat


class CoordinateFormatter:
    """Holds the persisted coordinate-format preference."""

    def __init__(self) -> None:
        self.format: CoordinateFormat = CoordinateFormat.DD
