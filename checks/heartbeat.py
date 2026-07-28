"""Check 2: Heartbeat — every machine should have reported in recently.

Each machine sends Cloudera Manager a "heartbeat" signal regularly. If a
machine hasn't heartbeated within the configured window (default 60 seconds),
it may be down or cut off from the network.

`now` can be passed in by tests to get repeatable results; in normal use it
defaults to the current time.
"""

from datetime import datetime, timezone
from typing import Optional

from config import TenantConfig
from data_sources import DataSource

from .result import CheckEvidence, CheckResult, EvidenceRow


def check_heartbeat(
    source: DataSource, tenant: TenantConfig, now: Optional[datetime] = None
) -> CheckResult:
    now = now or datetime.now(timezone.utc)
    window_sec = tenant.thresholds.heartbeat_window_sec
    hosts = source.get_hosts()

    silent_hosts = []
    age_by_host = {}
    for host in hosts:
        age_sec = (now - host.last_heartbeat).total_seconds()
        age_by_host[host.hostname] = age_sec
        if age_sec > window_sec:
            silent_hosts.append(host)

    evidence = CheckEvidence(
        source=source.provenance("hosts"),
        keys_checked=["lastHeartbeat"],
        rows=[
            EvidenceRow(
                entity=h.hostname,
                value=f"{age_by_host[h.hostname]:.0f}s ago",
                breached=age_by_host[h.hostname] > window_sec,
            )
            for h in hosts
        ],
    )

    if not silent_hosts:
        return CheckResult(
            task="heartbeat",
            status="OK",
            metric="heartbeat_age_sec",
            threshold=window_sec,
            breached_entities=[],
            detail=f"All {len(hosts)} hosts heartbeated within {window_sec}s.",
            evidence=evidence,
        )

    return CheckResult(
        task="heartbeat",
        status="BREACH",
        metric="heartbeat_age_sec",
        threshold=window_sec,
        breached_entities=[h.hostname for h in silent_hosts],
        detail="; ".join(
            f"{h.hostname}: {age_by_host[h.hostname]:.0f}s since last heartbeat (> {window_sec}s)"
            for h in silent_hosts
        ),
        evidence=evidence,
    )
