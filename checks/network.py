"""Check 9: Network — machines should be reachable with healthy network traffic.

The exact signals available depend on what the cluster exports:

1. Receive throughput (`total_bytes_receive_rate_across_network_interfaces`):
   a host reporting essentially no network receive activity may have a dead
   interface or be down — flagged.
2. Frame errors (`host_network_frame_errors_rate`): if this metric is exported,
   any rate above the tenant's limit is flagged.
3. Ping (SSH): if the source provides it, any unreachable host is flagged.

A cluster may expose any subset of these; the check uses whatever is present.
"""

from config import TenantConfig
from data_sources import DataSource

from .result import CheckResult

# Below this receive rate (bytes/sec) a host is treated as having no network
# activity — almost certainly a problem on a live cluster node.
NEAR_ZERO_THROUGHPUT = 1.0


def check_network(source: DataSource, tenant: TenantConfig) -> CheckResult:
    threshold = tenant.thresholds.network_error_rate_threshold

    problems: list[str] = []
    details: list[str] = []

    # 1. receive throughput — flag hosts with (near) zero activity
    throughput = source.get_metrics(["total_bytes_receive_rate_across_network_interfaces"])
    for s in throughput:
        if not s.points:
            continue
        rate = s.points[-1].value
        if rate < NEAR_ZERO_THROUGHPUT:
            problems.append(s.entity_name)
            details.append(f"{s.entity_name}: no network receive activity ({rate:.1f} B/s)")

    # 2. frame errors — only if the cluster exports this metric
    errors = source.get_metrics(["host_network_frame_errors_rate"])
    for s in errors:
        if not s.points:
            continue
        rate = s.points[-1].value
        if rate > threshold and s.entity_name not in problems:
            problems.append(s.entity_name)
            details.append(f"{s.entity_name}: frame_error_rate={rate} (> {threshold})")

    # 3. ping reachability — only if the source provides SSH data
    for p in source.ping_hosts():
        if not p.reachable and p.hostname not in problems:
            problems.append(p.hostname)
            details.append(f"{p.hostname}: unreachable via ping")

    if not problems:
        return CheckResult(
            task="network",
            status="OK",
            metric="throughput / frame_errors / ping",
            threshold=threshold,
            breached_entities=[],
            detail="All hosts show healthy network activity.",
        )

    return CheckResult(
        task="network",
        status="BREACH",
        metric="throughput / frame_errors / ping",
        threshold=threshold,
        breached_entities=problems,
        detail="; ".join(details),
    )
