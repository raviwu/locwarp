"""Pytest configuration. Adds the backend/ root to sys.path so tests can
import models.*, core.*, services.* the same way the runtime does.
"""
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


@pytest.fixture(scope="session", autouse=True)
def _ensure_data_dir():
    """Belt-and-suspenders: guarantee DATA_DIR exists for tests that build
    managers without going through the FastAPI lifespan."""
    import config
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
