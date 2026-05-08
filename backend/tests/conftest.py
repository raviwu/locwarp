"""Pytest configuration. Adds the backend/ root to sys.path so tests can
import models.*, core.*, services.* the same way the runtime does.
"""
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
