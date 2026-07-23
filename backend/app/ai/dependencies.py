"""The cross-metric dependency graph.

Declares, for each check, which OTHER checks are likely to be affected when it
breaches — the Hadoop/Cloudera architecture knowledge behind "Host Health is down,
so also check Heartbeat and Network." Used two ways:

  1. Deterministic UI hints — related cards show a "may be affected by X" chip the
     moment a parent breaches (no AI needed, instant).
  2. AI context — the relevant edges are injected into the analysis prompt so the
     model's cross-metric impact is grounded in declared knowledge, not guesses.

This is intended to be reviewed/edited by Ops — it's plain data. `expect` is a
short, honest phrasing of what degradation to anticipate (qualitative; precise
time-to-failure only comes from computed trends, see trends.py).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Edge:
    affects: str          # the downstream check likely impacted
    why: str              # one-line reason
    expect: str           # what degradation to anticipate (qualitative)


# task -> edges to downstream checks it can degrade.
DEPENDENCIES: dict[str, list[Edge]] = {
    "host_health": [
        Edge("heartbeat", "an unhealthy host often stops heartbeating", "the host may go silent"),
        Edge("network", "host problems frequently present as lost connectivity", "receive throughput may drop"),
        Edge("service_status", "roles on the host inherit its health", "roles hosted here may go unhealthy"),
        Edge("cpu_percent", "resource pressure is a common host-health cause", "CPU may climb"),
        Edge("ram_percent", "memory pressure/swapping degrades host health", "RAM may saturate and swap"),
    ],
    "heartbeat": [
        Edge("host_health", "a silent host is usually an unhealthy or down host", "host health will degrade"),
        Edge("service_status", "roles on a silent host drop out of their services", "dependent services may degrade"),
        Edge("hdfs_health", "a silent DataNode reduces HDFS replicas", "under-replication may appear"),
    ],
    "cpu_percent": [
        Edge("host_health", "sustained CPU saturation trips host health tests", "host health may turn CONCERNING"),
        Edge("service_status", "starved roles miss health checks", "affected service roles may degrade"),
    ],
    "ram_percent": [
        Edge("host_health", "memory pressure and swapping fail host health tests", "host health may degrade"),
        Edge("service_status", "OOM-killed roles go down", "roles may restart or fail"),
        Edge("heartbeat", "heavy swapping can delay the agent heartbeat", "the host may briefly go silent"),
    ],
    "disk_percent": [
        Edge("hdfs_health", "a full DataNode data disk takes storage offline", "HDFS may under-replicate"),
        Edge("service_status", "services fail when their log/data disks fill", "roles on the host may fail"),
        Edge("host_health", "a full disk fails host health tests", "host health may degrade"),
    ],
    "hdfs_health": [
        Edge("service_status", "YARN/HBase/Impala/Hive depend on HDFS", "dependent services may degrade"),
        Edge("alerts", "HDFS problems raise CM alerts", "related CRITICAL alerts may appear"),
    ],
    "service_status": [
        Edge("alerts", "unhealthy roles raise CM alerts", "related alerts may fire"),
        Edge("hdfs_health", "if the unhealthy service is HDFS, storage is affected", "HDFS health may degrade"),
    ],
    "alerts": [
        # Alerts are usually a SYMPTOM; the edges point back to likely sources.
        Edge("service_status", "most CRITICAL alerts originate from a role/service", "check the alerting service"),
        Edge("host_health", "many alerts trace to one unhealthy host", "check the host behind the alerts"),
    ],
    "network": [
        Edge("heartbeat", "network loss makes a host miss heartbeats", "the host may go silent"),
        Edge("hdfs_health", "DataNode network loss reroutes replication", "under-replication may appear"),
        Edge("service_status", "roles lose peer connectivity", "distributed services may degrade"),
    ],
}


def downstream_of(task: str) -> list[Edge]:
    """Edges from `task` to the checks it may affect."""
    return DEPENDENCIES.get(task, [])


def affected_by(task: str) -> list[str]:
    """The reverse view: which parent checks list `task` as something they affect
    (powers the 'may be affected by X' chip on a card)."""
    parents = []
    for parent, edges in DEPENDENCIES.items():
        if parent == task:
            continue
        if any(e.affects == task for e in edges):
            parents.append(parent)
    return parents
