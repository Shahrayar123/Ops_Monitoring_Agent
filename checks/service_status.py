"""Check 7: Service and role status — every service should be running and healthy.

Goes through every service in the cluster (HDFS, YARN, HBase, ...) and flags:
- any service that isn't in the STARTED state,
- any service-level health check that isn't GOOD,
- any role-level health check that isn't GOOD (a "role" is one part of a
  service on one machine, e.g. the YARN ResourceManager on host-1) — so the
  result says exactly which part on which machine has the problem.
"""

from config import TenantConfig
from data_sources import DataSource

from .result import CheckResult


def check_service_status(source: DataSource, tenant: TenantConfig) -> CheckResult:
    if not source.has_services():
        return CheckResult(
            task="service_status",
            status="NO_DATA",
            metric="serviceState / healthChecks",
            threshold="STARTED / GOOD",
            breached_entities=[],
            detail="No services data source configured yet for this cluster.",
        )

    services = source.get_services(tenant.cluster_name)

    problems: list[str] = []
    details: list[str] = []

    for svc in services:
        if svc.service_state != "STARTED":
            problems.append(svc.name)
            details.append(f"{svc.name}: serviceState={svc.service_state}")

        for hc in svc.health_checks:
            if hc.summary != "GOOD":
                problems.append(f"{svc.name}:{hc.name}")
                details.append(f"{svc.name} healthCheck {hc.name}={hc.summary}")

        for role in source.get_roles(tenant.cluster_name, svc.name):
            for hc in role.health_checks:
                if hc.summary != "GOOD":
                    problems.append(f"{svc.name}:{role.name}:{hc.name}")
                    details.append(
                        f"{svc.name} role {role.name} ({role.type}) healthCheck "
                        f"{hc.name}={hc.summary}"
                    )

    if not problems:
        return CheckResult(
            task="service_status",
            status="OK",
            metric="serviceState / healthChecks",
            threshold="STARTED / GOOD",
            breached_entities=[],
            detail=f"All {len(services)} services and their roles are healthy.",
        )

    return CheckResult(
        task="service_status",
        status="BREACH",
        metric="serviceState / healthChecks",
        threshold="STARTED / GOOD",
        breached_entities=problems,
        detail="; ".join(details),
    )
