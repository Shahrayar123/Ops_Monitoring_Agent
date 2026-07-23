"""AI analysis endpoints.

    POST /tenants/{slug}/analyze/{task}   start a scoped per-KPI analysis -> job_id
    POST /tenants/{slug}/analyze          start an all-breaches analysis   -> job_id
    GET  /analysis/{job_id}               poll a job (running/done/error/no_breach)
    GET  /tenants/{slug}/dependencies     the deterministic "affected by" map (instant)

The analyze endpoints fail fast on the two things worth catching early: the
user's model chain being empty, or already being over their plan limit. Otherwise
they return a job_id immediately and the work runs in the background.
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ...ai import jobs
from ...ai.dependencies import DEPENDENCIES, affected_by, downstream_of
from ...db.base import get_db
from ...db.models import Tenant, User
from ...llm.access import effective_priority, effective_allowed_models
from ...llm.usage import LimitExceeded, check_limit
from ..deps import get_current_user
from ..tenant_deps import get_tenant_or_404

router = APIRouter(tags=["ai-analysis"])

_VALID_TASKS = set(DEPENDENCIES.keys())


def _preflight(db: Session, user: User):
    """Cheap checks before spawning a job, so the user gets an instant, clear
    error instead of a job that fails a second later."""
    chain = effective_priority(user) or effective_allowed_models(user)[:1]
    if not chain:
        raise HTTPException(status_code=400, detail="No AI model is available on your account — set your model priority in Settings.")
    try:
        check_limit(db, user)
    except LimitExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc


@router.post("/tenants/{slug}/analyze/{task}")
def analyze_kpi(
    task: str,
    tenant: Tenant = Depends(get_tenant_or_404),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    as_of: Optional[date] = Query(default=None),
):
    if task not in _VALID_TASKS:
        raise HTTPException(status_code=404, detail=f"Unknown check '{task}'")
    _preflight(db, user)
    job_id = jobs.start("kpi", user, tenant, task, as_of)
    return {"job_id": job_id, "status": "running"}


@router.post("/tenants/{slug}/analyze")
def analyze_incident(
    tenant: Tenant = Depends(get_tenant_or_404),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    as_of: Optional[date] = Query(default=None),
):
    _preflight(db, user)
    job_id = jobs.start("incident", user, tenant, None, as_of)
    return {"job_id": job_id, "status": "running"}


@router.get("/analysis/{job_id}")
def poll(job_id: str, user: User = Depends(get_current_user)):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No such analysis job (it may have expired)")
    if job.user_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="Not your analysis job")
    return job.public()


@router.get("/tenants/{slug}/dependencies")
def dependencies(tenant: Tenant = Depends(get_tenant_or_404)):
    """The full dependency map — the dashboard uses it to show 'may be affected by
    X' chips on related cards the moment a parent breaches. No AI, instant."""
    return {
        "downstream": {t: [{"affects": e.affects, "why": e.why, "expect": e.expect} for e in downstream_of(t)]
                       for t in _VALID_TASKS},
        "affected_by": {t: affected_by(t) for t in _VALID_TASKS},
    }
