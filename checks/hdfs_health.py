"""Check 6: HDFS health and unusual growth.

HDFS is the cluster's storage service. Two independent things are checked, from
two different data sources, and the detail line always shows BOTH clearly
labelled so it's obvious which one caused a breach:

1. Health — Cloudera Manager's own verdict on the hdfs service (from the
   services list: healthSummary + healthChecks). Must be GOOD.

2. Growth — whether the amount of stored data grew faster than the tenant's
   limit over the configured window (from the dfs_capacity_used time series;
   default: more than 10% in 24h). Worth investigating even while Health is
   GOOD, since a runaway write job doesn't always show up as unhealthy yet.
"""

from config import TenantConfig
from data_sources import DataSource

from .result import CheckResult


def _health_part(source: DataSource, tenant: TenantConfig) -> tuple[bool, str, list[str]]:
    """Returns (breached, label, problems) for the CM health verdict."""
    if not source.has_services():
        return False, "Health: no data source configured yet", []

    services = source.get_services(tenant.cluster_name)
    hdfs = next((s for s in services if s.name == "hdfs"), None)

    if hdfs is None:
        return True, "Health: hdfs service not found in cluster", ["hdfs service not found in cluster"]

    problems = []
    if hdfs.health_summary != "GOOD":
        problems.append(f"hdfs healthSummary={hdfs.health_summary}")
    for hc in hdfs.health_checks:
        if hc.summary != "GOOD":
            problems.append(f"hdfs healthCheck {hc.name}={hc.summary}")

    breached = bool(problems)
    label = f"Health: {hdfs.health_summary}" + (" (BREACH)" if breached else " (OK)")
    return breached, label, problems


def _growth_part(source: DataSource, tenant: TenantConfig) -> tuple[bool, str, list[str]]:
    """Returns (breached, label, problems) for the storage-growth trend."""
    growth_limit = tenant.thresholds.hdfs_growth_pct_threshold
    window_hours = tenant.thresholds.hdfs_growth_pct_window_hours
    series = source.get_metrics(["dfs_capacity_used"])

    if not series or len(series[0].points) < 2:
        return False, "Growth: no data for this period", []

    points = sorted(series[0].points, key=lambda p: p.timestamp)
    first, last = points[0].value, points[-1].value
    if first <= 0:
        return False, "Growth: no data for this period", []

    growth_pct = (last - first) / first * 100
    breached = growth_pct > growth_limit
    label = (
        f"Growth: {growth_pct:.1f}% over {window_hours}h "
        f"(limit {growth_limit}%, {'BREACH' if breached else 'OK'})"
    )
    problems = (
        [f"dfs_capacity_used grew {growth_pct:.1f}% over {window_hours}h (> {growth_limit}%)"]
        if breached else []
    )
    return breached, label, problems


def check_hdfs_health(source: DataSource, tenant: TenantConfig) -> CheckResult:
    health_breach, health_label, health_problems = _health_part(source, tenant)
    growth_breach, growth_label, growth_problems = _growth_part(source, tenant)

    breached = health_breach or growth_breach
    detail = f"{health_label} · {growth_label}"
    if breached:
        detail += "  —  " + "; ".join(health_problems + growth_problems)

    return CheckResult(
        task="hdfs_health",
        status="BREACH" if breached else "OK",
        metric="healthSummary / dfs_capacity_used_growth_pct",
        threshold=tenant.thresholds.hdfs_growth_pct_threshold,
        breached_entities=["hdfs"] if breached else [],
        detail=detail,
    )
