"""Per-user KPI (dashboard metric) visibility.

A user's `allowed_kpis` (see db.models.User) restricts which of the nine checks
they may see and query on their dashboard:

    EMPTY list -> no restriction, all nine visible (the default; existing users)
    non-empty  -> only those check tasks are shown / queryable / analyzable

Admins always see all nine, regardless of their own allowed_kpis. This is the
one place that rule is defined, imported by the monitoring report endpoints and
the AI-analysis endpoints so a restricted user can neither view nor analyze a
KPI they weren't granted.
"""

from ..db.models import Role, User
from .bridge import DEFAULT_REFRESH_RATES

# The canonical nine check tasks, in dashboard order — the exact set the engine
# runs and refreshes, so this list can't drift from what's actually monitored.
ALL_KPI_TASKS: tuple[str, ...] = tuple(DEFAULT_REFRESH_RATES.keys())


def visible_kpis(user: User) -> set[str]:
    """The check tasks this user may see. Admins and unrestricted users -> all."""
    if user.role == Role.ADMIN or not user.allowed_kpis:
        return set(ALL_KPI_TASKS)
    return {t for t in user.allowed_kpis if t in ALL_KPI_TASKS}


def can_see_kpi(user: User, task: str) -> bool:
    """Whether this user is allowed to see/query a single check task."""
    return task in visible_kpis(user)


# Which check each tunable threshold belongs to. A user who can't see a KPI
# shouldn't see (or be able to edit) the threshold that drives it. Checks that
# are purely status-based — host_health, service_status, alerts — have no
# tunable threshold, so they simply don't appear here.
THRESHOLD_FIELD_TASK: dict[str, str] = {
    "cpu_pct": "cpu_percent",
    "ram_pct": "ram_percent",
    "disk_pct": "disk_percent",
    "disk_mounts": "disk_percent",
    "log_size_mb": "disk_percent",          # the disk check covers "Disk & Logs"
    "heartbeat_window_sec": "heartbeat",
    "hdfs_growth_pct_window_hours": "hdfs_health",
    "hdfs_growth_pct_threshold": "hdfs_health",
    "network_error_rate_threshold": "network",
}


def visible_threshold_fields(user: User) -> set[str]:
    """Threshold field names this user may see/edit, given their KPI access."""
    allowed = visible_kpis(user)
    return {f for f, task in THRESHOLD_FIELD_TASK.items() if task in allowed}
