"""In-process background jobs for AI analysis.

Local models take minutes, so analysis can't run inside a request. A job is
started, runs on a worker thread with its own DB session, and the frontend polls
until it's done. State is in-memory (fine for a single process); Phase 6 persists
analyses to the database for the audit trail.
"""

import logging
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Optional

from ..core import log_context
from ..db.base import SessionLocal
from ..db.models import Tenant, User
from ..llm.providers import LLMError
from ..llm.usage import LimitExceeded
from . import analyzer
from .analyzer import NoBreachError

log = logging.getLogger("backend.ai.jobs")

_JOBS: dict[str, "Job"] = {}
_LOCK = threading.Lock()
_MAX_JOBS = 200


@dataclass
class Job:
    id: str
    kind: str                      # "kpi" | "incident"
    scope: str                     # task name for kpi, "all" for incident
    user_id: int
    status: str = "running"        # running | done | error | no_breach
    result: Optional[dict] = None
    error: Optional[str] = None
    started_at: float = field(default_factory=time.time)
    seconds: float = 0.0

    def public(self) -> dict:
        d = asdict(self)
        d.pop("user_id", None)
        return d


def _finish(job: Job, *, status: str, result=None, error=None):
    job.status = status
    job.result = result
    job.error = error
    job.seconds = round(time.time() - job.started_at, 1)


def _run(job: Job, tenant_id: int, task: Optional[str], as_of: Optional[date], log_ctx: dict):
    # A plain threading.Thread does NOT inherit the parent's contextvars, so
    # without this every log line from this job would show request_id="-" and
    # be unattributable to a user. Re-applying the snapshot taken in start()
    # (still inside the original request, where the context was live) fixes that.
    log_context.apply_context(log_ctx)
    log.info("AI %s analysis job %s started (task=%s)", job.kind, job.id, task or "all")
    db = SessionLocal()
    try:
        user = db.get(User, job.user_id)
        tenant = db.get(Tenant, tenant_id)
        if user is None or tenant is None:
            log.warning("AI analysis job %s: user or cluster no longer exists", job.id)
            return _finish(job, status="error", error="User or cluster no longer exists.")
        try:
            if job.kind == "kpi":
                out = analyzer.analyze_kpi(db, user, tenant, task, as_of)
            else:
                out = analyzer.analyze_incident(db, user, tenant, as_of)
            _finish(job, status="done", result=out.model_dump())
            log.info("AI analysis job %s finished in %ss (model=%s)", job.id, job.seconds, out.model_used)
        except NoBreachError as exc:
            _finish(job, status="no_breach", error=str(exc))
        except LimitExceeded as exc:
            log.warning("AI analysis job %s blocked by usage limit: %s", job.id, exc)
            _finish(job, status="error", error=str(exc))
        except LLMError as exc:
            log.error("AI analysis job %s: all models failed: %s", job.id, exc)
            _finish(job, status="error", error=str(exc))
        except Exception as exc:  # never leave a job hanging on an unexpected fault
            log.exception("AI analysis job %s failed unexpectedly", job.id)
            _finish(job, status="error", error=f"Analysis failed: {exc}")
    finally:
        db.close()


def _register(job: Job):
    with _LOCK:
        _JOBS[job.id] = job
        # Trim oldest finished jobs if we're over the cap.
        if len(_JOBS) > _MAX_JOBS:
            done = sorted(
                (j for j in _JOBS.values() if j.status != "running"),
                key=lambda j: j.started_at,
            )
            for old in done[: len(_JOBS) - _MAX_JOBS]:
                _JOBS.pop(old.id, None)


def start(kind: str, user: User, tenant: Tenant, task: Optional[str], as_of: Optional[date]) -> str:
    job = Job(id=uuid.uuid4().hex, kind=kind, scope=task or "all", user_id=user.id)
    _register(job)
    tenant_id = tenant.id
    log_ctx = log_context.current_context()  # snapshot: taken here, while still on the request thread
    threading.Thread(target=_run, args=(job, tenant_id, task, as_of, log_ctx), daemon=True).start()
    return job.id


def get(job_id: str) -> Optional[Job]:
    return _JOBS.get(job_id)
