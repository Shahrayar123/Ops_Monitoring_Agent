"""Runs every check and bundles the results into one HealthReport.

This is plain deterministic Python — no AI anywhere in this file. The backend
calls run_all_checks() on every refresh; the AI (backend/app/ai/) is only
invoked afterwards, and only if the report contains breaches.
"""

import logging
from datetime import datetime, timezone
from typing import Callable, Optional

from pydantic import BaseModel, computed_field

from config import TenantConfig
from data_sources import DataSource

log = logging.getLogger(__name__)

from .alerts import check_alerts
from .cpu_percent import check_cpu_percent
from .disk_percent import check_disk_percent
from .hdfs_health import check_hdfs_health
from .heartbeat import check_heartbeat
from .host_health import check_host_health
from .network import check_network
from .ram_percent import check_ram_percent
from .result import CheckResult
from .service_status import check_service_status

# The full list of checks, run in this order on every refresh. The AI analyst
# gets these same functions as tools, so it can re-run any of them on demand.
ALL_CHECKS: list[Callable[[DataSource, TenantConfig], CheckResult]] = [
    check_host_health,
    check_heartbeat,
    check_cpu_percent,
    check_ram_percent,
    check_disk_percent,
    check_hdfs_health,
    check_service_status,
    check_alerts,
    check_network,
]


class HealthReport(BaseModel):
    """The outcome of running every check once."""

    tenant_id: str
    cluster_name: str
    timestamp: datetime
    results: list[CheckResult]

    @computed_field
    @property
    def has_breaches(self) -> bool:
        return any(r.status == "BREACH" for r in self.results)

    @computed_field
    @property
    def breach_count(self) -> int:
        return sum(1 for r in self.results if r.status == "BREACH")

    @property
    def breached_results(self) -> list[CheckResult]:
        return [r for r in self.results if r.status == "BREACH"]

    @computed_field
    @property
    def ok_count(self) -> int:
        return sum(1 for r in self.results if r.status == "OK")

    @computed_field
    @property
    def no_data_count(self) -> int:
        return sum(1 for r in self.results if r.status == "NO_DATA")

    @computed_field
    @property
    def evaluated_count(self) -> int:
        """Checks that actually ran (OK or BREACH) — excludes NO_DATA ones."""
        return sum(1 for r in self.results if r.status in ("OK", "BREACH"))


def run_all_checks(
    source: DataSource, tenant: TenantConfig, now: Optional[datetime] = None
) -> HealthReport:
    now = now or datetime.now(timezone.utc)

    results = []
    for check in ALL_CHECKS:
        if check is check_heartbeat:
            # heartbeat compares against "now", so pass it in for repeatability
            results.append(check_heartbeat(source, tenant, now=now))
        else:
            results.append(check(source, tenant))

    report = HealthReport(
        tenant_id=tenant.tenant_id,
        cluster_name=tenant.cluster_name,
        timestamp=now,
        results=results,
    )

    _log_report(report)
    return report


# The dashboard re-runs checks every few seconds, so logging full detail every
# time would fill the log with identical lines. Instead: one compact line per
# run, and full breach details only when the situation CHANGES (a check starts
# or stops breaching, or different entities are affected).
_last_logged_situation: dict[str, str] = {}


def _log_report(report: HealthReport) -> None:
    situation = "; ".join(
        f"{r.task}[{','.join(sorted(r.breached_entities))}]" for r in report.breached_results
    )
    changed = _last_logged_situation.get(report.tenant_id) != situation
    _last_logged_situation[report.tenant_id] = situation

    if not report.has_breaches:
        if changed:
            log.info("Tenant '%s': all %d checks OK (recovered)", report.tenant_id, len(report.results))
        else:
            log.debug("Tenant '%s': all checks OK (no change)", report.tenant_id)
        return

    if changed:
        log.warning(
            "Tenant '%s': %d of %d checks BREACHED (situation changed)",
            report.tenant_id, report.breach_count, len(report.results),
        )
        for r in report.breached_results:
            log.warning(
                "  breach | %s | affected: %s | %s",
                r.task, ", ".join(r.breached_entities) or "-", r.detail,
            )
    else:
        log.debug(
            "Tenant '%s': %d of %d checks still breaching (no change)",
            report.tenant_id, report.breach_count, len(report.results),
        )
