"""FastAPI backend for the Cloudera Ops monitoring product.

Exposes the deterministic checks and the AI analysis over HTTP so any frontend
(the bundled Streamlit dashboard, or a team's own UI) can consume them.

Endpoints:
    GET  /health                          liveness check for the API itself
    GET  /tenants                         list tenants + their data source kind
    GET  /tenants/{id}/dates              days available for the date filter
    GET  /tenants/{id}/report?as_of=...   run all checks, return the HealthReport
    POST /tenants/{id}/analyze?as_of=...  start a background AI analysis -> job_id
    GET  /analysis/{job_id}               poll an AI analysis job

The report endpoint is fast (deterministic Python); the analyze endpoint returns
immediately and the real work happens in the background (see jobs.py).
"""

import logging
import sys
from datetime import date
from pathlib import Path
from typing import Optional

# Make the API importable no matter where uvicorn is launched from — if the
# project root isn't on the path (e.g. `uvicorn main:app` run inside api/),
# add it so the top-level packages (config, checks, app_logging, ...) resolve.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from fastapi import Body, FastAPI, HTTPException, Query

from app_logging import setup_logging
from config import ThresholdUpdateError
from data_sources import DataSourceError

from api import jobs, service

setup_logging()
log = logging.getLogger("api")

app = FastAPI(
    title="Cloudera Ops Automation API",
    version="1.0",
    description="Deterministic cluster checks + on-demand AI incident analysis.",
)


@app.get("/health")
def health() -> dict:
    return {"status": "Service is Up and Running"}


@app.get("/tenants")
def list_tenants() -> list[dict]:
    return [service.tenant_summary(t) for t in service.list_tenants()]


@app.get("/tenants/{tenant_id}/thresholds")
def get_thresholds(tenant_id: str) -> dict:
    _require_tenant(tenant_id)
    return service.get_thresholds(tenant_id)


@app.put("/tenants/{tenant_id}/thresholds")
def put_thresholds(tenant_id: str, new_values: dict = Body(...)) -> dict:
    _require_tenant(tenant_id)
    try:
        return service.set_thresholds(tenant_id, new_values)
    except ThresholdUpdateError as exc:
        # invalid value or write failure — client's problem to fix
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/tenants/{tenant_id}/dates")
def tenant_dates(tenant_id: str) -> dict:
    _require_tenant(tenant_id)
    try:
        dates = service.available_dates(tenant_id)
    except DataSourceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"dates": [d.isoformat() for d in dates]}


@app.get("/tenants/{tenant_id}/report")
def tenant_report(tenant_id: str, as_of: Optional[date] = Query(default=None)) -> dict:
    _require_tenant(tenant_id)
    try:
        report = service.build_report(tenant_id, as_of)
    except DataSourceError as exc:
        # The tenant's data source isn't usable yet (e.g. live API not wired up).
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return report.model_dump(mode="json")


@app.post("/tenants/{tenant_id}/analyze")
async def start_analysis(tenant_id: str, as_of: Optional[date] = Query(default=None)) -> dict:
    _require_tenant(tenant_id)
    # Fail early with a clear reason if the source can't be built.
    try:
        service.get_source(tenant_id)
    except DataSourceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    job_id = jobs.start_analysis(tenant_id, as_of)
    return {"job_id": job_id, "status": "running"}


@app.get("/analysis/{job_id}")
def analysis_status(job_id: str) -> dict:
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No analysis job '{job_id}'")
    return job


def _require_tenant(tenant_id: str) -> None:
    try:
        service.get_tenant(tenant_id)
    except service.TenantNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
