"""Check 7: Service and role status — every service should be running and healthy.

A service is treated as healthy only when it is running AND nothing about it is
CONCERNING or BAD. "Nothing about it" means the worst of three signals from
Cloudera Manager, so a problem shows up no matter which one CM records it in:

- healthSummary  — CM's own rolled-up verdict for the whole service. (CM can set
  this to CONCERNING while exporting no individual healthChecks — e.g. the issue
  is a specific role — so we must honour it directly, not just the checks below.)
- service-level healthChecks — the named checks CM lists on the service itself.
- role-level healthChecks — one part of a service on one machine (e.g. the YARN
  ResourceManager on host-1). Only available when a roles source is configured.

The card's status is the WORST of those three, so the value shown ("STARTED ·
CONCERNING") always matches the green/red flag, and the detail names exactly
which signal tripped it. This mirrors host_health and hdfs_health, which also
key off healthSummary.

Two Cloudera-isms handled so they don't cause false alarms:
- serviceState "NA" is normal for config-only services (CORE_SETTINGS, TEZ, ...)
  that have no running daemons — not a problem.
- health summaries other than GOOD/CONCERNING/BAD (DISABLED, NOT_AVAILABLE, ...)
  mean "not measured", not "unhealthy" — only CONCERNING/BAD are real problems.
"""

from config import TenantConfig
from data_sources import DataSource

from .result import CheckEvidence, CheckResult, EvidenceRow

# States that are fine: running, or "not applicable" (config-only services).
HEALTHY_STATES = {"STARTED", "NA"}
# Health summaries that actually indicate a problem.
BAD_SUMMARIES = {"CONCERNING", "BAD"}


def _worst(summaries: list[str]) -> str:
    """The most severe verdict among the given summaries (BAD > CONCERNING > GOOD)."""
    if "BAD" in summaries:
        return "BAD"
    if "CONCERNING" in summaries:
        return "CONCERNING"
    return "GOOD"


def check_service_status(source: DataSource, tenant: TenantConfig) -> CheckResult:
    if not source.has_services():
        return CheckResult(
            task="service_status",
            status="NO_DATA",
            metric="serviceState / healthSummary / healthChecks",
            threshold="running / no CONCERNING or BAD signals",
            breached_entities=[],
            detail="No services data source configured yet for this cluster.",
        )

    services = source.get_services(tenant.cluster_name)

    problems: list[str] = []
    details: list[str] = []
    rows: list[EvidenceRow] = []

    for svc in services:
        state_bad = svc.service_state not in HEALTHY_STATES
        summary_bad = svc.health_summary in BAD_SUMMARIES
        svc_bad_hcs = [hc for hc in svc.health_checks if hc.summary in BAD_SUMMARIES]
        role_bad = [
            (role, hc)
            for role in source.get_roles(tenant.cluster_name, svc.name)
            for hc in role.health_checks
            if hc.summary in BAD_SUMMARIES
        ]

        breached = state_bad or summary_bad or bool(svc_bad_hcs) or bool(role_bad)

        if breached:
            # Record every specific reason so the detail explains the flag.
            if state_bad:
                problems.append(svc.name)
                details.append(f"{svc.name}: serviceState={svc.service_state}")
            for hc in svc_bad_hcs:
                problems.append(f"{svc.name}:{hc.name}")
                details.append(f"{svc.name} healthCheck {hc.name}={hc.summary}")
            for role, hc in role_bad:
                problems.append(f"{svc.name}:{role.name}:{hc.name}")
                details.append(
                    f"{svc.name} role {role.name} ({role.type}) healthCheck "
                    f"{hc.name}={hc.summary}"
                )
            # CM's rollup is CONCERNING/BAD but no individual check explains it
            # (e.g. hdfs with an empty healthChecks list) — the summary itself is
            # the reason, so surface it explicitly.
            if summary_bad and not svc_bad_hcs and not role_bad and not state_bad:
                problems.append(svc.name)
                details.append(f"{svc.name}: healthSummary={svc.health_summary}")

        # The value shown is the effective (worst) verdict, so it always agrees
        # with the green/red flag. When healthy, show CM's own summary verbatim.
        if breached:
            effective = _worst(
                [svc.health_summary]
                + [hc.summary for hc in svc_bad_hcs]
                + [hc.summary for _, hc in role_bad]
            )
        else:
            effective = svc.health_summary
        rows.append(
            EvidenceRow(
                entity=svc.name,
                value=f"{svc.service_state} · {effective}",
                breached=breached,
            )
        )

    evidence = CheckEvidence(
        source=source.provenance("services"),
        keys_checked=["serviceState", "healthSummary", "healthChecks"],
        rows=rows,
    )

    if not problems:
        return CheckResult(
            task="service_status",
            status="OK",
            metric="serviceState / healthSummary / healthChecks",
            threshold="running / no CONCERNING or BAD signals",
            breached_entities=[],
            detail=f"All {len(services)} services and their roles are healthy.",
            evidence=evidence,
        )

    return CheckResult(
        task="service_status",
        status="BREACH",
        metric="serviceState / healthSummary / healthChecks",
        threshold="running / no CONCERNING or BAD signals",
        breached_entities=problems,
        detail="; ".join(details),
        evidence=evidence,
    )
