"""Check 1: Host health — every machine should report healthy.

Cloudera Manager already computes a health verdict per machine (GOOD /
CONCERNING / BAD). This check simply flags any machine that isn't GOOD.
"""

from config import TenantConfig
from data_sources import DataSource

from .result import CheckResult


def check_host_health(source: DataSource, tenant: TenantConfig) -> CheckResult:
    hosts = source.get_hosts()
    unhealthy = [h for h in hosts if h.health_summary != "GOOD"]

    if not unhealthy:
        return CheckResult(
            task="host_health",
            status="OK",
            metric="healthSummary",
            threshold="GOOD",
            breached_entities=[],
            detail=f"All {len(hosts)} hosts report healthSummary GOOD.",
        )

    return CheckResult(
        task="host_health",
        status="BREACH",
        metric="healthSummary",
        threshold="GOOD",
        breached_entities=[h.hostname for h in unhealthy],
        detail="; ".join(f"{h.hostname}: healthSummary={h.health_summary}" for h in unhealthy),
    )
