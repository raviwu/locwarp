"""Process-global container handle.

main.py calls set_container() exactly once after building the Container. The
outer-ring adapter modules (api/*) that run OUTSIDE a FastAPI request — module-
level watchdogs, tunnel restart helpers — read the container through
get_container() instead of `from main import app_state`, which keeps api/* from
importing the composition root and lets the no-api-imports-main contract hold.

Inside a request, prefer the api/deps.py providers (Depends). This module is the
seam ONLY for the non-request module-level code paths.
"""
from __future__ import annotations

_CONTAINER = None


def set_container(container) -> None:
    global _CONTAINER
    _CONTAINER = container


def get_container():
    if _CONTAINER is None:
        raise RuntimeError(
            "Container not initialized — set_container() must run during app "
            "startup before any module-level adapter touches it."
        )
    return _CONTAINER
