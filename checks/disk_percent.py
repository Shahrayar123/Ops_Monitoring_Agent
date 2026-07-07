"""Check 5: Disk space and log sizes — storage shouldn't fill up.

Two related storage problems are covered by this one check:

1. Disk fullness: each configured mount (like /var, /opt) must stay under the
   tenant's limit (default 90%). The main reading comes from the cluster's
   metrics; the SSH `df` reading is compared against it, and a note is added
   when the two disagree by more than a few percentage points.

2. Runaway log files: any single log file bigger than the configured limit
   (default 1024 MB) is flagged, since a runaway log can quietly fill a disk.
"""

from config import TenantConfig
from data_sources import DataSource

from .result import CheckResult

# If the metric and SSH `df` disagree by more than this many percentage points,
# mention it in the detail (the metric reading still decides OK/BREACH).
ALLOWED_DISAGREEMENT_PP = 5.0


def check_disk_percent(source: DataSource, tenant: TenantConfig) -> CheckResult:
    disk_limit = tenant.thresholds.disk_pct
    watched_mounts = set(tenant.thresholds.disk_mounts)
    log_limit_mb = tenant.thresholds.log_size_mb

    series = source.get_metrics(["fs_bytes_used_percent"])
    ssh_readings = {(d.hostname, d.mount_point): d.used_percent for d in source.get_disk_usage()}

    metric_readings = {
        (s.entity_name, s.attributes["mount_point"]): s.points[-1].value
        for s in series
        if s.points and s.attributes.get("mount_point") in watched_mounts
    }

    problems: list[str] = []
    details: list[str] = []

    # 1. disks over the limit
    for (hostname, mount), metric_value in metric_readings.items():
        note = ""
        ssh_value = ssh_readings.get((hostname, mount))
        if ssh_value is not None and abs(ssh_value - metric_value) > ALLOWED_DISAGREEMENT_PP:
            note = f" (SSH df reads {ssh_value:.1f}%)"

        if metric_value > disk_limit:
            problems.append(f"{hostname}:{mount}")
            details.append(f"{hostname}:{mount}: {metric_value:.1f}% (> {disk_limit}%){note}")

    # 2. oversized log files
    for log_file in source.get_log_files():
        size_mb = log_file.size_bytes / (1024 * 1024)
        if size_mb > log_limit_mb:
            problems.append(f"{log_file.hostname}:log:{log_file.path}")
            details.append(
                f"{log_file.hostname}:{log_file.path}: {size_mb:.0f}MB (> {log_limit_mb}MB)"
            )

    if not problems:
        return CheckResult(
            task="disk_percent",
            status="OK",
            metric="fs_bytes_used_percent / log_file_size_mb",
            threshold=disk_limit,
            breached_entities=[],
            detail=(
                f"All {len(metric_readings)} watched mounts under {disk_limit}% "
                f"and all log files under {log_limit_mb}MB."
            ),
        )

    return CheckResult(
        task="disk_percent",
        status="BREACH",
        metric="fs_bytes_used_percent / log_file_size_mb",
        threshold=disk_limit,
        breached_entities=problems,
        detail="; ".join(details),
    )
