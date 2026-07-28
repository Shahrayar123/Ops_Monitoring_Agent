"""The monitoring checks — the heart of the product.

Each file in this folder is one check: plain Python that reads cluster data
from a DataSource, compares it against the tenant's configured thresholds, and
returns a CheckResult saying OK or BREACH. No AI is involved at this stage.

run_all_checks.py runs every check in one go and bundles the results into a
HealthReport — that's what the dashboard shows and what the AI analyzes.
"""

from .result import CheckEvidence, CheckResult, EvidenceRow
from .host_health import check_host_health
from .heartbeat import check_heartbeat
from .cpu_percent import check_cpu_percent
from .ram_percent import check_ram_percent
from .disk_percent import check_disk_percent
from .hdfs_health import check_hdfs_health
from .service_status import check_service_status
from .alerts import check_alerts
from .network import check_network
from .run_all_checks import ALL_CHECKS, HealthReport, run_all_checks

__all__ = [
    "CheckResult",
    "CheckEvidence",
    "EvidenceRow",
    "check_host_health",
    "check_heartbeat",
    "check_cpu_percent",
    "check_ram_percent",
    "check_disk_percent",
    "check_hdfs_health",
    "check_service_status",
    "check_alerts",
    "check_network",
    "ALL_CHECKS",
    "HealthReport",
    "run_all_checks",
]
