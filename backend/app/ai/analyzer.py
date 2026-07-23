"""Run an AI analysis for a tenant — scoped to one KPI, or across all breaches.

Flow: build the deterministic report (engine) -> compute trends -> hand the
breach to a specialized Agent (one per KPI check, or one Incident Coordinator
for all breaches together) -> the agent investigates with its own tools
(knowledge search, dependency lookup, disk trend) and returns structured
output -> apply the deterministic severity floor -> return.

The model NEVER decides what's broken; it explains the finished breach list.
Agent construction and the per-provider fallback chain live in
agent_runner.py — this file only shapes inputs/outputs around that call.
"""

import logging

from sqlalchemy.orm import Session

from ..db.models import Tenant, User
from ..engine import bridge
from . import agent_runner, models, trends
from .models import AiFinding, IncidentReport, KpiAnalysis

log = logging.getLogger("backend.ai.analyzer")

# CPU-only local models generate slowly, and an agent may take several tool
# turns before its final answer — allow minutes before giving up (the
# analysis runs as a background job, so nobody is blocked waiting).
_ANALYSIS_TIMEOUT = 600.0


class NoBreachError(Exception):
    """Analysis was requested on something that isn't breaching."""


def _disk_trend_text(db_tenant: Tenant, as_of, task: str | None) -> str:
    """Trend context — only meaningful for disk. Empty for other checks."""
    if task not in (None, "disk_percent"):
        return "(No time-to-full projection applies to this check.)"
    cfg = bridge.tenant_to_config(db_tenant)
    source = bridge.get_source(db_tenant)
    if hasattr(source, "as_of"):
        source.as_of = as_of
    return trends.format_for_prompt(trends.disk_projections(source, cfg))


def analyze_kpi(db: Session, user: User, db_tenant: Tenant, task: str, as_of=None) -> KpiAnalysis:
    result = bridge.build_single_check(db_tenant, task, as_of)
    if result.status != "BREACH":
        raise NoBreachError(f"{task} is not currently breaching — nothing to analyze.")

    result_json = result.model_dump(mode="json")
    trend_text = _disk_trend_text(db_tenant, as_of, task)

    outcome = agent_runner.run_kpi_with_fallback(
        db, user, task=task, result=result_json, trend_text=trend_text,
        cluster=db_tenant.cluster_name, version=db_tenant.cloudera_version,
        timeout=_ANALYSIS_TIMEOUT,
    )

    data = outcome.data
    severity = models.apply_floor(str(data.get("severity", "MEDIUM")).upper(), task, result.detail)

    return KpiAnalysis(
        task=task,
        severity=severity,
        summary=str(data.get("summary", "")).strip() or _fallback_summary(data.get("_raw_text", "")),
        remediation=models.coerce_str_list(data.get("remediation")),
        impact=str(data.get("impact", "")).strip(),
        related_tasks=[str(t) for t in (data.get("related_tasks") or [])],
        trend_note=trend_text if trend_text and "No time-to-full" not in trend_text else "",
        sources=[str(s) for s in (data.get("sources") or [])],
        model_used=outcome.model_id,
        attempts=outcome.attempts,
    )


def analyze_incident(db: Session, user: User, db_tenant: Tenant, as_of=None) -> IncidentReport:
    report = bridge.build_report(db_tenant, as_of)
    breached = [r for r in report.results if r.status == "BREACH"]
    if not breached:
        raise NoBreachError("No checks are breaching — the AI only runs when there are problems.")

    by_task = {r.task: r for r in breached}
    breached_json = [r.model_dump(mode="json") for r in breached]
    trend_text = _disk_trend_text(db_tenant, as_of, None)

    outcome = agent_runner.run_incident_with_fallback(
        db, user, breached=breached_json, trend_text=trend_text,
        cluster=db_tenant.cluster_name, version=db_tenant.cloudera_version,
        timeout=_ANALYSIS_TIMEOUT,
    )

    data = outcome.data
    findings: list[AiFinding] = []
    for raw in data.get("findings", []):
        task = str(raw.get("primary_task", "")).strip()
        check = by_task.get(task)
        sev = str(raw.get("severity", "MEDIUM")).upper()
        if check is not None:
            sev = models.apply_floor(sev, task, check.detail)   # floor from real data
        findings.append(AiFinding(
            primary_task=task or "unknown",
            severity=sev if sev in ("LOW", "MEDIUM", "HIGH", "CRITICAL") else "MEDIUM",
            summary=str(raw.get("summary", "")).strip(),
            remediation=models.coerce_str_list(raw.get("remediation")),
            related_tasks=[str(t) for t in (raw.get("related_tasks") or [])],
        ))

    # If the agent returned nothing usable, degrade gracefully to one finding per breach.
    if not findings:
        for r in breached:
            findings.append(AiFinding(
                primary_task=r.task,
                severity=models.apply_floor("MEDIUM", r.task, r.detail),
                summary=r.detail,
            ))

    findings = models.order_findings(findings)
    return IncidentReport(
        overall_summary=str(data.get("overall_summary", "")).strip() or _fallback_summary(data.get("_raw_text", "")),
        findings=findings,
        priority_order=[f.primary_task for f in findings],   # from the ordered cards
        model_used=outcome.model_id,
        attempts=outcome.attempts,
    )


def _fallback_summary(text: str) -> str:
    """If parsing failed (Anthropic direct-call path only), surface the model's
    raw prose rather than nothing. The agentic path always has structured output,
    so this is empty there."""
    text = (text or "").strip()
    return (text[:600] + "…") if len(text) > 600 else (text or "The model returned no analysis.")
