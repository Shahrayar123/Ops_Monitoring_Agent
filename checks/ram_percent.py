"""Check 4: Memory usage — no machine should use more RAM than the threshold.

The cluster reports memory as two numbers per machine (bytes used, bytes
total); this check turns them into a percentage and flags machines above the
tenant's limit (default 60%).
"""

from config import TenantConfig
from data_sources import DataSource

from .result import CheckEvidence, CheckResult, EvidenceRow


def check_ram_percent(source: DataSource, tenant: TenantConfig) -> CheckResult:
    threshold = tenant.thresholds.ram_pct
    series = source.get_metrics(["physical_memory_used", "physical_memory_total"])

    used = {
        s.entity_name: s.points[-1].value
        for s in series
        if s.metric_name == "physical_memory_used" and s.points
    }
    total = {
        s.entity_name: s.points[-1].value
        for s in series
        if s.metric_name == "physical_memory_total" and s.points
    }

    percent_by_host = {
        host: used[host] / total[host] * 100
        for host in used
        if host in total and total[host] > 0
    }
    over_limit = {host: pct for host, pct in percent_by_host.items() if pct > threshold}

    evidence = CheckEvidence(
        source=source.provenance("physical_memory_used"),
        keys_checked=["physical_memory_used", "physical_memory_total"],
        rows=[
            EvidenceRow(entity=host, value=f"{pct:.1f}%", breached=pct > threshold)
            for host, pct in percent_by_host.items()
        ],
    )

    if not over_limit:
        return CheckResult(
            task="ram_percent",
            status="OK",
            metric="ram_percent",
            threshold=threshold,
            breached_entities=[],
            detail=f"All {len(percent_by_host)} hosts under {threshold}% RAM used.",
            evidence=evidence,
        )

    return CheckResult(
        task="ram_percent",
        status="BREACH",
        metric="ram_percent",
        threshold=threshold,
        breached_entities=list(over_limit.keys()),
        detail="; ".join(f"{host}: {pct:.1f}% (> {threshold}%)" for host, pct in over_limit.items()),
        evidence=evidence,
    )
