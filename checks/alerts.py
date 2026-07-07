"""Check 8: Cluster alerts — no active alert events should exist.

Cloudera Manager raises alert events on health problems. This check simply
surfaces any active ones; a healthy cluster has none.
"""

from config import TenantConfig
from data_sources import DataSource

from .result import CheckResult


def check_alerts(source: DataSource, tenant: TenantConfig) -> CheckResult:
    if not source.has_events():
        return CheckResult(
            task="alerts",
            status="NO_DATA",
            metric="alert_count",
            threshold=0,
            breached_entities=[],
            detail="No alert/events data source configured yet for this cluster.",
        )

    alerts = source.get_events(category="HEALTH_CHECK", alert_only=True)

    if not alerts:
        return CheckResult(
            task="alerts",
            status="OK",
            metric="alert_count",
            threshold=0,
            breached_entities=[],
            detail="No active alert/health-check events.",
        )

    return CheckResult(
        task="alerts",
        status="BREACH",
        metric="alert_count",
        threshold=0,
        breached_entities=[a.id for a in alerts],
        detail="; ".join(f"{a.id} ({a.severity}): {a.content}" for a in alerts),
    )
