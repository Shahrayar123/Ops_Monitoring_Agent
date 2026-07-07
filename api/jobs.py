"""Background AI analysis jobs.

The AI analyst can take several minutes on CPU — far too long for a single HTTP
request to wait. So analysis runs as a background job: the client starts one and
gets a job_id back immediately, then polls until it's done. This is the standard
fix for slow work behind an API, and it means the analysis keeps running even if
the browser disconnects.

Jobs live in memory (a simple dict). That's fine for a single-process demo/
deploy; if this ever scales to multiple worker processes, this is the one piece
that would move to a shared store (Redis/DB).
"""

import asyncio
import logging
import time
import uuid
from datetime import date, datetime
from typing import Optional

from ai_analysis import run_ai_analysis

log = logging.getLogger(__name__)

# job_id -> job dict
_jobs: dict[str, dict] = {}


def _breach_signature(report) -> str:
    """A compact fingerprint of exactly which breaches a report has, so the
    client can tell whether an analysis still matches what's on screen."""
    return "|".join(
        f"{r.task}:{','.join(sorted(r.breached_entities))}" for r in report.breached_results
    )


def _new_job(tenant_id: str, as_of: Optional[date]) -> str:
    job_id = uuid.uuid4().hex[:12]
    _jobs[job_id] = {
        "job_id": job_id,
        "tenant_id": tenant_id,
        "as_of": as_of.isoformat() if as_of else None,  # the day this analysis is about
        "breach_signature": None,                        # set when it runs
        "status": "running",          # running | done | error | no_breaches
        "result": None,               # AiReport (as dict) when done
        "error": None,
        "seconds": None,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    return job_id


def get_job(job_id: str) -> Optional[dict]:
    return _jobs.get(job_id)


async def _run(job_id: str, tenant_id: str, as_of: Optional[date]) -> None:
    # Imported here to avoid a circular import at module load.
    from config import load_llm_config

    from .service import build_fresh_source, build_report_on, get_tenant

    try:
        tenant = get_tenant(tenant_id)
        # Own, uncached source pinned to this day, so the auto-refreshing report
        # requests can't change the day under the AI while it drills into data.
        source = build_fresh_source(tenant_id)
        report = build_report_on(source, tenant, as_of)
        _jobs[job_id]["breach_signature"] = _breach_signature(report)

        if not report.has_breaches:
            _jobs[job_id].update(status="no_breaches", seconds=0)
            return

        start = time.monotonic()
        ai_report = await run_ai_analysis(report, source, tenant, load_llm_config())
        _jobs[job_id].update(
            status="done",
            result=ai_report.model_dump(mode="json"),
            seconds=round(time.monotonic() - start, 1),
        )
    except Exception as exc:  # noqa: BLE001 — report any failure back to the client
        log.exception("AI analysis job %s failed", job_id)
        _jobs[job_id].update(status="error", error=str(exc))


def start_analysis(tenant_id: str, as_of: Optional[date] = None) -> str:
    """Create a job and launch it on the running event loop. Must be called
    from within the async app (FastAPI endpoints are async)."""
    job_id = _new_job(tenant_id, as_of)
    asyncio.create_task(_run(job_id, tenant_id, as_of))
    return job_id
