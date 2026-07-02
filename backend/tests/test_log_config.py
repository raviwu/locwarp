"""Backend file logs must retain multiple days (was ~27h with 4x2MB size
rotation — too short for post-hoc investigation)."""
import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from log_config import LOG_RETENTION_DAYS, build_file_log_handler


def test_retention_is_at_least_a_week():
    assert LOG_RETENTION_DAYS >= 7


def test_file_handler_is_daily_rotating_with_multiday_retention(tmp_path: Path):
    handler = build_file_log_handler(tmp_path, "%(message)s")
    try:
        assert isinstance(handler, TimedRotatingFileHandler)
        assert handler.when.upper() == "MIDNIGHT"
        assert handler.backupCount == LOG_RETENTION_DAYS
        assert handler.level == logging.INFO
    finally:
        handler.close()
