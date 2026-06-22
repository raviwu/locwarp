"""Re-export shim — RouteInterpolator moved to domain/movement.py (Phase 3, Task 7).

Kept so non-core importers (services.cooldown, characterization tests, and any
external `from services.interpolator import RouteInterpolator`) keep working. The
three CORE importers were flipped to import from domain.movement directly, which
removes the last interpolator-driven core->services import edge.
"""
from domain.movement import RouteInterpolator

__all__ = ["RouteInterpolator"]
