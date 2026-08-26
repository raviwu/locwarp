"""Port for the local catalog-baseline snapshot. stdlib + typing only (domain ring).

BookmarkManager (services ring) depends on this Protocol; the concrete
FileCatalogBaselineStore (infra ring) implements it and is wired at the
composition root, so services never import infra.
"""
from __future__ import annotations

from typing import Protocol


class CatalogBaselineRepository(Protocol):
    def read(self) -> dict | None:
        """Parsed baseline snapshot, or None if absent/unreadable."""
        ...

    def write(self, payload: dict) -> None:
        """Atomically (over)write the baseline snapshot."""
        ...
