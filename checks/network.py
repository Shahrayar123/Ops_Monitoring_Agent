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

from .result import CheckEvidence, CheckResult, EvidenceRow

# Below this receive rate (bytes/sec) a host is treated as having no network
# activity — almost certainly a problem on a live cluster node.
NEAR_ZERO_THROUGHPUT = 1.0


def check_network(source: DataSource, tenant: TenantConfig) -> CheckResult:
    threshold = tenant.thresholds.network_error_rate_threshold

    problems: list[str] = []
    details: list[str] = []
    rows: list[EvidenceRow] = []

    # 1. receive throughput — flag hosts with (near) zero activity
    throughput = source.get_metrics(["total_bytes_receive_rate_across_network_interfaces"])
    for s in throughput:
        if not s.points:
            continue
        rate = s.points[-1].value
        dead = rate < NEAR_ZERO_THROUGHPUT
        rows.append(EvidenceRow(entity=s.entity_name, value=f"{rate:.1f} B/s recv", breached=dead))
        if dead:
            problems.append(s.entity_name)
            details.append(f"{s.entity_name}: no network receive activity ({rate:.1f} B/s)")

    # 2. frame errors — only if the cluster exports this metric
    errors = source.get_metrics(["host_network_frame_errors_rate"])
    for s in errors:
        if not s.points:
            continue
        rate = s.points[-1].value
        over = rate > threshold
        rows.append(
            EvidenceRow(entity=f"{s.entity_name} frame errors", value=str(rate), breached=over)
        )
        if over and s.entity_name not in problems:
            problems.append(s.entity_name)
            details.append(f"{s.entity_name}: frame_error_rate={rate} (> {threshold})")

    # 3. ping reachability — only if the source provides SSH data
    for p in source.ping_hosts():
        rows.append(
            EvidenceRow(
                entity=f"{p.hostname} ping",
                value="reachable" if p.reachable else "unreachable",
                breached=not p.reachable,
            )
        )
        if not p.reachable and p.hostname not in problems:
            problems.append(p.hostname)
            details.append(f"{p.hostname}: unreachable via ping")

    evidence = CheckEvidence(
        source=source.provenance("total_bytes_receive_rate_across_network_interfaces"),
        keys_checked=[
            "total_bytes_receive_rate_across_network_interfaces",
            "host_network_frame_errors_rate",
            "ping",
        ],
        rows=rows,
    )

    if not problems:
        return CheckResult(
            task="network",
            status="OK",
            metric="throughput / frame_errors / ping",
            threshold=threshold,
            breached_entities=[],
            detail="All hosts show healthy network activity.",
            evidence=evidence,
        )

    return CheckResult(
        task="network",
        status="BREACH",
        metric="throughput / frame_errors / ping",
        threshold=threshold,
        breached_entities=problems,
        detail="; ".join(details),
        evidence=evidence,
    )
