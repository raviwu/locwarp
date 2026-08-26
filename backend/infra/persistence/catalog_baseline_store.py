"""Infra adapter: catalog-baseline file I/O under a caller-provided path.

Built ONLY at the composition root (bootstrap/factories.make_bookmark_manager).
Reuses services.json_safe for the same atomic temp+replace guarantee the live
store enjoys (the infra -> services.json_safe edge already exists in json_store).

Deliberately shape-agnostic: it persists whatever dict it is handed. The field
set of the payload is import_catalog's concern, not the store's.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from services.json_safe import safe_load_json, safe_write_json


class FileCatalogBaselineStore:
    """Implements domain.ports.catalog_baseline_repository.CatalogBaselineRepository.

    The path is resolved lazily via ``path_provider()`` so test isolation
    (monkeypatch of config.CATALOG_BASELINE_FILE) takes effect, and so each
    manager can own its own baseline — the file is per machine, and the repo
    models two machines as two managers over one shared store file.
    """

    def __init__(self, path_provider: Callable[[], Path]):
        self._path_provider = path_provider

    def read(self) -> dict | None:
        # safe_load_json returns None for missing/empty/corrupt files.
        data = safe_load_json(Path(self._path_provider()))
        return data if isinstance(data, dict) else None

    def write(self, payload: dict) -> None:
        safe_write_json(Path(self._path_provider()), payload)
