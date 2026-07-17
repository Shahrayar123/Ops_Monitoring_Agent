"""Check 3: CPU usage — no machine should run hotter than the threshold.

Reads the latest cpu_percent measurement per machine and flags any machine
above the tenant's limit (default 60%).
"""

from config import TenantConfig
from data_sources import DataSource

from .result import CheckEvidence, CheckResult, EvidenceRow


def check_cpu_percent(source: DataSource, tenant: TenantConfig) -> CheckResult:
    threshold = tenant.thresholds.cpu_pct
    series = source.get_metrics(["cpu_percent"])

    latest_by_host = {s.entity_name: s.points[-1].value for s in series if s.points}
    over_limit = {host: value for host, value in latest_by_host.items() if value > threshold}

    evidence = CheckEvidence(
        source=source.provenance("cpu_percent"),
        keys_checked=["cpu_percent"],
        rows=[
            EvidenceRow(entity=host, value=f"{value:.1f}%", breached=value > threshold)
            for host, value in latest_by_host.items()
        ],
    )

    if not over_limit:
        return CheckResult(
            task="cpu_percent",
            status="OK",
            metric="cpu_percent",
            threshold=threshold,
            breached_entities=[],
            detail=f"All {len(latest_by_host)} hosts under {threshold}% CPU.",
            evidence=evidence,
        )

    return CheckResult(
        task="cpu_percent",
        status="BREACH",
        metric="cpu_percent",
        threshold=threshold,
        breached_entities=list(over_limit.keys()),
        detail="; ".join(f"{host}: {value:.1f}% (> {threshold}%)" for host, value in over_limit.items()),
        evidence=evidence,
    )
