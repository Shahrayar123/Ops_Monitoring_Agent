"""End-to-end logging setup: console (human-readable) + rotating JSON files.

    logs/app.log      INFO and above — everything, one JSON object per line
    logs/errors.log   ERROR and above only — for a fast "what broke today" scan

Both rotate at midnight and keep 7 days of history (older files are deleted
automatically by TimedRotatingFileHandler itself — no cron/cleanup job needed).

Every line — from any logger, anywhere in the app or the monitoring engine —
carries request_id/user_id/user_email via log_context.ContextFilter, so a
support request ("user X saw an error at 3pm") is one grep away:

    grep '"user_email": "x@company.com"' logs/app.log
    grep '"request_id": "a1b2c3d4"' logs/app.log | jq .

JSON lines were chosen over plain text specifically so logs stay queryable as
the product grows (jq today; Loki/ELK/CloudWatch later) without changing the
logging code — only where the files are shipped changes.
"""

import json
import logging
import logging.handlers
from pathlib import Path

from .log_context import ContextFilter

REPO_ROOT = Path(__file__).resolve().parents[3]
LOG_DIR = REPO_ROOT / "logs"

RETENTION_DAYS = 7

# Handlers share one LogRecord instance and run in sequence, so an earlier
# handler's Formatter.format() can leave side-effect attributes (asctime,
# message) on the record before ours runs. Exclude both explicitly, on top of
# the record's own default fields, so they never leak into the extras merge.
_RESERVED = set(logging.LogRecord(None, 0, "", 0, "", None, None).__dict__.keys()) | {"asctime", "message"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
            "user_id": getattr(record, "user_id", "-"),
            "user_email": getattr(record, "user_email", "-"),
            "module": record.module,
            "func": record.funcName,
            "line": record.lineno,
        }
        # Anything passed via logging's `extra={...}` that isn't a stdlib
        # LogRecord field rides along too (e.g. tenant slug, model id).
        for key, value in record.__dict__.items():
            if key not in _RESERVED and key not in payload:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_level = getattr(logging, level.upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(log_level)
    root.handlers.clear()  # idempotent: --reload re-imports this module on every code change

    context_filter = ContextFilter()

    console = logging.StreamHandler()
    console.setLevel(log_level)
    console.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s | %(message)s"))
    console.addFilter(context_filter)
    root.addHandler(console)

    app_file = logging.handlers.TimedRotatingFileHandler(
        LOG_DIR / "app.log", when="midnight", backupCount=RETENTION_DAYS, encoding="utf-8", utc=True,
    )
    app_file.setLevel(log_level)
    app_file.setFormatter(JsonFormatter())
    app_file.addFilter(context_filter)
    root.addHandler(app_file)

    error_file = logging.handlers.TimedRotatingFileHandler(
        LOG_DIR / "errors.log", when="midnight", backupCount=RETENTION_DAYS, encoding="utf-8", utc=True,
    )
    error_file.setLevel(logging.ERROR)
    error_file.setFormatter(JsonFormatter())
    error_file.addFilter(context_filter)
    root.addHandler(error_file)

    # sqlalchemy.engine is extremely chatty at INFO (every SQL statement); we
    # already log the request lifecycle ourselves in errors.py.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    # uvicorn ships its own handlers with propagate=False (to avoid double-
    # printing to console), which would silently exclude every HTTP access line
    # ("GET /tenants/... 200") from our files. Strip its handlers and let its
    # records fall through to root instead, so they land in app.log too.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers.clear()
        uv_logger.propagate = True
