"""Turns the REAL Cloudera Manager API exports into our simple record types.

This handles the actual shapes seen in a live CM cluster's responses, which
differ from the older hand-made samples in a few ways:

- Host resource is ONE host object per file (not wrapped in {"items": [...]}).
- Disk usage comes as `capacity` and `capacity_used` in BYTES per filesystem;
  we pair them and compute a used-percent, so the disk check sees the same
  `fs_bytes_used_percent` it always did.
- HDFS capacity comes per-DataNode; we sum the DataNodes at each timestamp to
  get the cluster total, so the HDFS check sees one `dfs_capacity_used` series.
- Network comes as receive-throughput per host.

By translating to the metric names the checks already expect, the CPU, RAM,
disk and HDFS checks work without changes.
"""

from collections import defaultdict

from .base import Event, Host, MetricPoint, MetricSeries, Service


def _health_checks(raw: list[dict]):
    from .base import HealthCheck

    return [HealthCheck(name=hc["name"], summary=hc["summary"]) for hc in raw]


def parse_services(raw: dict, cluster_name: str) -> list[Service]:
    """The services list from GET /clusters/{cluster}/services?view=FULL."""
    return [
        Service(
            name=item["name"],
            type=item["type"],
            cluster_name=item["clusterRef"]["clusterName"],
            service_state=item.get("serviceState", ""),
            health_summary=item.get("healthSummary", ""),
            health_checks=_health_checks(item.get("healthChecks", [])),
        )
        for item in raw.get("items", [])
        if item.get("clusterRef", {}).get("clusterName") == cluster_name
    ]


def parse_events(raw: dict, category: str | None, alert_only: bool) -> list[Event]:
    """Alert/health events from GET /events?query=alert==true.

    The real CM `attributes` field is a LIST of {"name": ..., "values": [...]}
    objects; we flatten it to a {name: [values]} dict so the Event model and the
    checks see a simple mapping. `category=None` means keep every category."""
    out: list[Event] = []
    for item in raw.get("items", []):
        if alert_only and not item.get("alert"):
            continue
        if category is not None and item.get("category") != category:
            continue
        attrs: dict[str, list[str]] = {}
        for a in item.get("attributes", []):
            if isinstance(a, dict) and "name" in a:
                attrs[a["name"]] = a.get("values", [])
        out.append(
            Event(
                id=item["id"],
                content=item.get("content", ""),
                time_occurred=item["timeOccurred"],
                category=item.get("category", ""),
                severity=item.get("severity", ""),
                alert=item.get("alert", False),
                attributes=attrs,
            )
        )
    return out


def parse_host_file(item: dict) -> Host:
    """One host resource file (a single host object, view=FULL)."""
    return Host(
        host_id=item["hostId"],
        hostname=item["hostname"],
        ip_address=item.get("ipAddress", ""),
        health_summary=item["healthSummary"],
        last_heartbeat=item["lastHeartbeat"],
        health_checks=_health_checks(item.get("healthChecks", [])),
        num_cores=item.get("numCores", 0),
        total_phys_mem_bytes=item.get("totalPhysMemBytes", 0),
    )


def _timeseries_groups(raw: dict):
    for group in raw.get("items", []):
        for ts in group.get("timeSeries", []):
            yield ts


def _hostname_of(metadata: dict) -> str:
    attrs = metadata.get("attributes", {})
    # attributes.hostname is the clean host name; entityName can be a composite.
    return attrs.get("hostname") or metadata.get("entityName", "")


def _points(ts: dict) -> list[MetricPoint]:
    return [
        MetricPoint(timestamp=p["timestamp"], value=p["value"])
        for p in ts.get("data", [])
        if p.get("value") is not None
    ]


def parse_host_metric(raw: dict, wanted_metric: str) -> list[MetricSeries]:
    """Per-host metrics like cpu_percent or physical_memory_used — one series
    per host, keyed by the clean hostname."""
    out: list[MetricSeries] = []
    for ts in _timeseries_groups(raw):
        md = ts["metadata"]
        if md["metricName"] != wanted_metric:
            continue
        hostname = _hostname_of(md)
        out.append(
            MetricSeries(
                metric_name=wanted_metric,
                entity_name=hostname,
                category="HOST",
                attributes={"hostname": hostname, "category": "HOST"},
                points=_points(ts),
            )
        )
    return out


def parse_disk_percent(raw: dict) -> list[MetricSeries]:
    """Pairs `capacity_used` and `capacity` (both in bytes) per filesystem and
    emits `fs_bytes_used_percent` — the metric the disk check expects."""
    used: dict[str, dict] = {}
    total: dict[str, dict] = {}

    for ts in _timeseries_groups(raw):
        md = ts["metadata"]
        attrs = md.get("attributes", {})
        key = attrs.get("entityName") or md.get("entityName")  # hostId:mountpoint, unique
        record = {
            "hostname": _hostname_of(md),
            "mount_point": attrs.get("mountpoint", ""),
            "points": {p["timestamp"]: p["value"] for p in ts.get("data", []) if p.get("value") is not None},
        }
        if md["metricName"] == "capacity_used":
            used[key] = record
        elif md["metricName"] == "capacity":
            total[key] = record

    out: list[MetricSeries] = []
    for key, used_rec in used.items():
        total_rec = total.get(key)
        if not total_rec:
            continue
        percent_points: list[MetricPoint] = []
        for ts_str, used_val in used_rec["points"].items():
            total_val = total_rec["points"].get(ts_str)
            if total_val and total_val > 0:
                percent_points.append(
                    MetricPoint(timestamp=ts_str, value=used_val / total_val * 100)
                )
        if not percent_points:
            continue
        percent_points.sort(key=lambda p: p.timestamp)
        out.append(
            MetricSeries(
                metric_name="fs_bytes_used_percent",
                entity_name=used_rec["hostname"],
                category="FILESYSTEM",
                attributes={
                    "hostname": used_rec["hostname"],
                    "mount_point": used_rec["mount_point"],
                    "category": "FILESYSTEM",
                },
                points=percent_points,
            )
        )
    return out


def parse_hdfs_capacity(raw: dict) -> list[MetricSeries]:
    """HDFS capacity comes per-DataNode; sum the DataNodes at each timestamp to
    get the cluster total, and emit one `dfs_capacity` and one
    `dfs_capacity_used` series (what the HDFS check expects)."""
    totals: dict[str, dict[str, float]] = {
        "dfs_capacity": defaultdict(float),
        "dfs_capacity_used": defaultdict(float),
    }
    for ts in _timeseries_groups(raw):
        md = ts["metadata"]
        name = md["metricName"]
        if name not in totals:
            continue
        for p in ts.get("data", []):
            if p.get("value") is not None:
                totals[name][p["timestamp"]] += p["value"]

    out: list[MetricSeries] = []
    for name, per_ts in totals.items():
        if not per_ts:
            continue
        points = [MetricPoint(timestamp=t, value=v) for t, v in sorted(per_ts.items())]
        out.append(
            MetricSeries(
                metric_name=name,
                entity_name="hdfs",
                category="SERVICE",
                attributes={"serviceName": "hdfs", "category": "SERVICE"},
                points=points,
            )
        )
    return out


def parse_network_throughput(raw: dict) -> list[MetricSeries]:
    """Receive-throughput per host, kept under its real metric name."""
    metric = "total_bytes_receive_rate_across_network_interfaces"
    out: list[MetricSeries] = []
    for ts in _timeseries_groups(raw):
        md = ts["metadata"]
        if md["metricName"] != metric:
            continue
        hostname = _hostname_of(md)
        out.append(
            MetricSeries(
                metric_name=metric,
                entity_name=hostname,
                category="HOST",
                attributes={"hostname": hostname, "category": "HOST"},
                points=_points(ts),
            )
        )
    return out
