"""Backend file-log handler construction (extracted for testability)."""
from __future__ import annotations

import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

LOG_RETENTION_DAYS = 14


def build_file_log_handler(log_dir: Path, fmt: str) -> logging.Handler:
    """Daily-rotating file handler keeping ~LOG_RETENTION_DAYS days of logs.

    Replaces the old size-based rotation (RotatingFileHandler, 2MB x 3) which
    retained only ~1 day of a busy session — too short for post-hoc
    investigation. Time-based rotation guarantees N days regardless of volume;
    a single very busy day's file is size-uncapped, an acceptable trade for a
    personal tool (and daily volume drops once the watchdog/USB-reconnect
    fixes land).
    """
    handler = TimedRotatingFileHandler(
        log_dir / "backend.log",
        when="midnight",
        interval=1,
        backupCount=LOG_RETENTION_DAYS,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(fmt))
    handler.setLevel(logging.INFO)
    return handler
