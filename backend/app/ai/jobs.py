"""In-process background jobs for AI analysis.

Local models take minutes, so analysis can't run inside a request. A job is
started, runs on a worker thread with its own DB session, and the frontend polls
until it's done. State is in-memory (fine for a single process); Phase 6 persists
analyses to the database for the audit trail.
"""

import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Optional

from ..db.base import SessionLocal
from ..db.models import Tenant, User
from ..llm.providers import LLMError
from ..llm.usage import LimitExceeded
from . import analyzer
from .analyzer import NoBreachError

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


def _run(job: Job, tenant_id: int, task: Optional[str], as_of: Optional[date]):
    db = SessionLocal()
    try:
        user = db.get(User, job.user_id)
        tenant = db.get(Tenant, tenant_id)
        if user is None or tenant is None:
            return _finish(job, status="error", error="User or cluster no longer exists.")
        try:
            if job.kind == "kpi":
                out = analyzer.analyze_kpi(db, user, tenant, task, as_of)
            else:
                out = analyzer.analyze_incident(db, user, tenant, as_of)
            _finish(job, status="done", result=out.model_dump())
        except NoBreachError as exc:
            _finish(job, status="no_breach", error=str(exc))
        except LimitExceeded as exc:
            _finish(job, status="error", error=str(exc))
        except LLMError as exc:
            _finish(job, status="error", error=str(exc))
        except Exception as exc:  # never leave a job hanging on an unexpected fault
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
    threading.Thread(target=_run, args=(job, tenant_id, task, as_of), daemon=True).start()
    return job.id


def get(job_id: str) -> Optional[Job]:
    return _JOBS.get(job_id)
