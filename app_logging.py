"""Application logging: daily files in logs/, kept for 7 days.

Call setup_logging() once at startup. After that, any module logs with:

    import logging
    log = logging.getLogger(__name__)
    log.info("...")

How it works:
- Everything goes to logs/ops_agent.log.
- At midnight the file is rotated: the old day is renamed to
  ops_agent.log.YYYY-MM-DD and a fresh file starts.
- Only the last 7 rotated days are kept; older ones are deleted automatically.
"""

import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_FILE = LOG_DIR / "ops_agent.log"
KEEP_DAYS = 7

_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"


def setup_logging(level: int = logging.INFO) -> None:
    """Set up the daily-rotating log file. Safe to call more than once —
    a second call does nothing (prevents duplicate log lines when the
    dashboard re-runs its script)."""
    root = logging.getLogger()

    already_set_up = any(
        isinstance(h, TimedRotatingFileHandler)
        and Path(getattr(h, "baseFilename", "")) == LOG_FILE
        for h in root.handlers
    )
    if already_set_up:
        return

    LOG_DIR.mkdir(exist_ok=True)

    handler = TimedRotatingFileHandler(
        LOG_FILE,
        when="midnight",       # start a new file each day
        backupCount=KEEP_DAYS, # keep 7 old days, delete anything older
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(_FORMAT))

    root.addHandler(handler)
    root.setLevel(level)

    logging.getLogger(__name__).info("Logging started (daily files, %s days kept)", KEEP_DAYS)
