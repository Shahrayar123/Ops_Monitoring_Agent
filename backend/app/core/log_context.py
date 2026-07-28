"""Per-request/per-user logging context.

Every log line written anywhere in the app — a route handler, the engine's
checks, the AI analyzer, a background job thread — gets the SAME request_id,
user_id, and user_email attached automatically, via a `logging.Filter` that
reads from contextvars. That's what makes the logs "end-to-end": grep one
request_id and you see every line it touched, across every module, in order.

contextvars propagate through async/await automatically, but NOT into a plain
`threading.Thread` (ai/jobs.py runs analysis on one) — for that, capture the
context in the parent thread and re-apply it inside the worker; see
`current_context()` / `apply_context()` below.
"""

from __future__ import annotations

import contextvars
import logging
from typing import Optional

_request_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("request_id", default=None)
_user_id: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar("user_id", default=None)
_user_email: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("user_email", default=None)


def set_request_id(request_id: Optional[str]) -> None:
    _request_id.set(request_id)


def set_user(user_id: Optional[int], email: Optional[str]) -> None:
    _user_id.set(user_id)
    _user_email.set(email)


def current_context() -> dict:
    """A snapshot of the current logging context, for handing to another thread."""
    return {
        "request_id": _request_id.get(),
        "user_id": _user_id.get(),
        "user_email": _user_email.get(),
    }


def apply_context(ctx: dict) -> None:
    """Apply a snapshot taken by current_context() — call this as the FIRST line
    inside a new thread's target function, before it logs anything."""
    _request_id.set(ctx.get("request_id"))
    _user_id.set(ctx.get("user_id"))
    _user_email.set(ctx.get("user_email"))


class ContextFilter(logging.Filter):
    """Attaches request_id/user_id/user_email to every LogRecord. Installed on
    the root logger's handlers in logging_config.py, so it applies everywhere —
    including third-party loggers (uvicorn, sqlalchemy) — not just our own code."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get() or "-"
        record.user_id = _user_id.get() or "-"
        record.user_email = _user_email.get() or "-"
        return True
