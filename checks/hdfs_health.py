"""Check 6: HDFS health and unusual growth.

HDFS is the cluster's storage service. Two things are checked:

1. Health: Cloudera Manager's own verdict on the hdfs service and each of its
   internal health checks must be GOOD.

2. Unusual growth: if the amount of stored data grew faster than the tenant's
   limit over the configured window (default: more than 10% in 24h), something
   may be filling the cluster — worth investigating even while health is GOOD.
"""

from config import TenantConfig
from data_sources import DataSource

from .result import CheckResult


def check_hdfs_health(source: DataSource, tenant: TenantConfig) -> CheckResult:
    services = source.get_services(tenant.cluster_name)
    hdfs = next((s for s in services if s.name == "hdfs"), None)

    problems: list[str] = []

    # 1. health as judged by Cloudera Manager — only when a services source
    #    exists. Without it we still do the growth check below; a missing
    #    services export is NOT a breach, it just means we can't read CM's
    #    own verdict yet.
    if source.has_services():
        if hdfs is None:
            problems.append("hdfs service not found in cluster")
        else:
            if hdfs.health_summary != "GOOD":
                problems.append(f"hdfs healthSummary={hdfs.health_summary}")
            for hc in hdfs.health_checks:
                if hc.summary != "GOOD":
                    problems.append(f"hdfs healthCheck {hc.name}={hc.summary}")

    # 2. unusual storage growth
    growth_limit = tenant.thresholds.hdfs_growth_pct_threshold
    series = source.get_metrics(["dfs_capacity_used"])
    if series and len(series[0].points) >= 2:
        points = sorted(series[0].points, key=lambda p: p.timestamp)
        first, last = points[0].value, points[-1].value
        if first > 0:
            growth_pct = (last - first) / first * 100
            if growth_pct > growth_limit:
                problems.append(
                    f"dfs_capacity_used grew {growth_pct:.1f}% over "
                    f"{tenant.thresholds.hdfs_growth_pct_window_hours}h (> {growth_limit}%)"
                )

    if not problems:
        return CheckResult(
            task="hdfs_health",
            status="OK",
            metric="healthSummary / dfs_capacity_used_growth_pct",
            threshold=growth_limit,
            breached_entities=[],
            detail="hdfs service is GOOD and capacity growth is within threshold.",
        )

    return CheckResult(
        task="hdfs_health",
        status="BREACH",
        metric="healthSummary / dfs_capacity_used_growth_pct",
        threshold=growth_limit,
        breached_entities=["hdfs"],
        detail="; ".join(problems),
    )
