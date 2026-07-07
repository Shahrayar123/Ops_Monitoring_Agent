"""Tests for the daily log files."""

import logging
from logging.handlers import TimedRotatingFileHandler

import app_logging
from app_logging import setup_logging
from checks import run_all_checks


def _our_handlers():
    return [
        h for h in logging.getLogger().handlers
        if isinstance(h, TimedRotatingFileHandler)
        and getattr(h, "baseFilename", "").endswith("ops_agent.log")
    ]


def test_setup_creates_a_daily_rotating_file_kept_seven_days():
    setup_logging()

    handlers = _our_handlers()
    assert len(handlers) == 1
    assert handlers[0].backupCount == app_logging.KEEP_DAYS == 7
    assert handlers[0].when.upper() == "MIDNIGHT"
    assert app_logging.LOG_FILE.exists()


def test_calling_setup_twice_does_not_duplicate_handlers():
    setup_logging()
    setup_logging()

    assert len(_our_handlers()) == 1


def test_a_monitoring_run_writes_breach_details_to_the_log(source, tenant):
    setup_logging()

    run_all_checks(source, tenant)
    for handler in _our_handlers():
        handler.flush()

    text = app_logging.LOG_FILE.read_text(encoding="utf-8")
    assert "BREACHED" in text
    assert "cpu_percent" in text
