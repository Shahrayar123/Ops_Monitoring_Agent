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

The evidence panel additionally shows the current capacity used vs total (the
"Capacity" the card name promises) and, when CM provides them, the individual
non-GOOD health checks — so it's always clear which signal the verdict came from.
"""

from config import TenantConfig
from data_sources import DataSource

from .result import CheckEvidence, CheckResult, EvidenceRow

_TB = 1024 ** 4  # bytes per terabyte, for human-readable capacity


def _health_part(source: DataSource, tenant: TenantConfig) -> dict:
    """The CM health verdict for the hdfs service. Returns a dict with:
    breached, value (the healthSummary), label + problems (for the detail line),
    and checks (the individual non-GOOD health checks, if the export lists any)."""
    if not source.has_services():
        return {"breached": False, "value": "no data",
                "label": "Health: no data source configured yet", "problems": [], "checks": []}

    services = source.get_services(tenant.cluster_name)
    hdfs = next((s for s in services if s.name == "hdfs"), None)

    if hdfs is None:
        return {"breached": True, "value": "not found",
                "label": "Health: hdfs service not found in cluster",
                "problems": ["hdfs service not found in cluster"], "checks": []}

    checks = [(hc.name, hc.summary) for hc in hdfs.health_checks if hc.summary != "GOOD"]
    problems = []
    if hdfs.health_summary != "GOOD":
        problems.append(f"hdfs healthSummary={hdfs.health_summary}")
    for name, summary in checks:
        problems.append(f"hdfs healthCheck {name}={summary}")

    breached = bool(problems)
    label = f"Health: {hdfs.health_summary}" + (" (BREACH)" if breached else " (OK)")
    return {"breached": breached, "value": hdfs.health_summary,
            "label": label, "problems": problems, "checks": checks}


def _growth_part(source: DataSource, tenant: TenantConfig) -> dict:
    """The storage-growth trend and the underlying capacity figures. Returns a
    dict with: breached, value + label + problems (growth), and the raw
    used_first / used_last / total bytes for the capacity row."""
    growth_limit = tenant.thresholds.hdfs_growth_pct_threshold
    window_hours = tenant.thresholds.hdfs_growth_pct_window_hours

    used = source.get_metrics(["dfs_capacity_used"])
    total = source.get_metrics(["dfs_capacity"])
    total_last = None
    if total and total[0].points:
        total_last = sorted(total[0].points, key=lambda p: p.timestamp)[-1].value

    base = {"total_last": total_last, "used_first": None, "used_last": None,
            "growth_limit": growth_limit, "window_hours": window_hours}

    if not used or len(used[0].points) < 2:
        return {**base, "breached": False,
                "label": "Growth: no data for this period", "value": "no data", "problems": []}

    points = sorted(used[0].points, key=lambda p: p.timestamp)
    first, last = points[0].value, points[-1].value
    if first <= 0:
        return {**base, "breached": False,
                "label": "Growth: no data for this period", "value": "no data", "problems": []}

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
    return {**base, "breached": breached, "used_first": first, "used_last": last,
            "label": label, "value": f"{growth_pct:.1f}% over {window_hours}h", "problems": problems}


def _evidence_rows(health: dict, growth: dict) -> list[EvidenceRow]:
    rows = [
        # The CM verdict, labelled with the exact field it comes from, so it's
        # unambiguous which of the file's many CONCERNING values this is.
        EvidenceRow(
            entity="Service health (healthSummary)",
            value=health["value"],
            breached=health["breached"],
        )
    ]
    # Any individual non-GOOD health checks CM listed (empty for this export —
    # hdfs's CONCERNING is the service-level rollup only — but populated for
    # clusters/live data that do provide per-check detail).
    for name, summary in health["checks"]:
        rows.append(EvidenceRow(entity=f"check: {name}", value=summary, breached=summary != "GOOD"))

    # Capacity ("… of … TB, % full") — informational context, not a threshold.
    used_last, total_last = growth["used_last"], growth["total_last"]
    if used_last is not None and total_last:
        pct_full = used_last / total_last * 100
        rows.append(EvidenceRow(
            entity="Capacity used",
            value=f"{used_last / _TB:.1f} TB of {total_last / _TB:.1f} TB ({pct_full:.1f}% full)",
            breached=False,
        ))

    # Growth, spelled out with the underlying reading and the limit.
    growth_value = growth["value"]
    if growth["used_first"] is not None and growth["used_last"] is not None:
        growth_value = (
            f"{growth['value']} "
            f"({growth['used_first'] / _TB:.1f} -> {growth['used_last'] / _TB:.1f} TB, "
            f"limit {growth['growth_limit']}%)"
        )
    rows.append(EvidenceRow(entity="Storage growth", value=growth_value, breached=growth["breached"]))
    return rows


def check_hdfs_health(source: DataSource, tenant: TenantConfig) -> CheckResult:
    health = _health_part(source, tenant)
    growth = _growth_part(source, tenant)

    breached = health["breached"] or growth["breached"]
    detail = f"{health['label']} · {growth['label']}"
    if breached:
        detail += "  —  " + "; ".join(health["problems"] + growth["problems"])

    evidence = CheckEvidence(
        source=f'{source.provenance("services")} · {source.provenance("dfs_capacity_used")}',
        keys_checked=["healthSummary", "healthChecks", "dfs_capacity_used", "dfs_capacity"],
        rows=_evidence_rows(health, growth),
    )

    return CheckResult(
        task="hdfs_health",
        status="BREACH" if breached else "OK",
        metric="healthSummary / dfs_capacity_used_growth_pct",
        threshold=tenant.thresholds.hdfs_growth_pct_threshold,
        breached_entities=["hdfs"] if breached else [],
        detail=detail,
        evidence=evidence,
    )
