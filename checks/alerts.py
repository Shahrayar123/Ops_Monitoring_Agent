"""Check 8: Cluster alerts — no serious active alerts should exist.

Cloudera Manager raises alert events (query: alert==true). Many of those are
INFORMATIONAL ("health became good", audit entries) and aren't problems — only
CRITICAL and IMPORTANT alerts are surfaced as breaches. The detail summarises the
counts and shows a few example alert summaries rather than dumping all of them.
"""

from config import TenantConfig
from data_sources import DataSource

from .result import CheckResult

# Severities that count as a real problem.
SERIOUS = {"CRITICAL", "IMPORTANT"}
# How many example alerts to spell out in the detail line.
MAX_EXAMPLES = 3


def _summary_of(event) -> str:
    """A short human line for one alert — prefer CM's own ALERT_SUMMARY, else the
    event content, trimmed."""
    summary = event.attributes.get("ALERT_SUMMARY")
    text = summary[0] if summary else event.content
    return text[:160]


def check_alerts(source: DataSource, tenant: TenantConfig) -> CheckResult:
    if not source.has_events():
        return CheckResult(
            task="alerts",
            status="NO_DATA",
            metric="active_alerts",
            threshold="0 critical/important",
            breached_entities=[],
            detail="No alert/events data source configured yet for this cluster.",
        )

    alerts = source.get_events(alert_only=True)          # any category, active alerts
    serious = [a for a in alerts if a.severity in SERIOUS]

    if not serious:
        return CheckResult(
            task="alerts",
            status="OK",
            metric="active_alerts",
            threshold="0 critical/important",
            breached_entities=[],
            detail=f"No critical or important active alerts ({len(alerts)} lower-severity events).",
        )

    critical = sum(1 for a in serious if a.severity == "CRITICAL")
    important = sum(1 for a in serious if a.severity == "IMPORTANT")
    examples = " | ".join(_summary_of(a) for a in serious[:MAX_EXAMPLES])

    return CheckResult(
        task="alerts",
        status="BREACH",
        metric="active_alerts",
        threshold="0 critical/important",
        breached_entities=[a.id for a in serious],
        detail=f"{critical} critical, {important} important active alerts. Examples: {examples}",
    )
