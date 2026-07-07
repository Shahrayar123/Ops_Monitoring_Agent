"""Turns raw Cloudera Manager JSON into our simple record types.

The JSON sample files in data/ and the live CM API return the same JSON shapes,
so both data sources share this one parsing module instead of duplicating it.
If the real cluster's JSON ever differs slightly from our samples, this file is
the only place that needs adjusting.
"""

from .base import Event, HealthCheck, Host, MetricPoint, MetricSeries, Role, Service


def _health_checks(raw: list[dict]) -> list[HealthCheck]:
    return [HealthCheck(name=hc["name"], summary=hc["summary"]) for hc in raw]


def parse_hosts(raw: dict) -> list[Host]:
    return [
        Host(
            host_id=item["hostId"],
            hostname=item["hostname"],
            ip_address=item["ipAddress"],
            health_summary=item["healthSummary"],
            last_heartbeat=item["lastHeartbeat"],
            health_checks=_health_checks(item.get("healthChecks", [])),
            num_cores=item["numCores"],
            total_phys_mem_bytes=item["totalPhysMemBytes"],
        )
        for item in raw["items"]
    ]


def parse_services(raw: dict, cluster_name: str) -> list[Service]:
    return [
        Service(
            name=item["name"],
            type=item["type"],
            cluster_name=item["clusterRef"]["clusterName"],
            service_state=item["serviceState"],
            health_summary=item["healthSummary"],
            health_checks=_health_checks(item.get("healthChecks", [])),
        )
        for item in raw["items"]
        if item["clusterRef"]["clusterName"] == cluster_name
    ]


def parse_roles(raw: dict, cluster_name: str, service_name: str) -> list[Role]:
    return [
        Role(
            name=item["name"],
            type=item["type"],
            service_name=item["serviceRef"]["serviceName"],
            host_id=item["hostRef"]["hostId"],
            health_summary=item["healthSummary"],
            health_checks=_health_checks(item.get("healthChecks", [])),
        )
        for item in raw["items"]
        if item["serviceRef"]["clusterName"] == cluster_name
        and item["serviceRef"]["serviceName"] == service_name
    ]


def parse_metrics(raw: dict, metric_names: list[str]) -> list[MetricSeries]:
    """metric_names filters the result; an empty list means keep everything."""
    series: list[MetricSeries] = []
    for group in raw["items"]:
        for ts in group["timeSeries"]:
            metadata = ts["metadata"]
            if metric_names and metadata["metricName"] not in metric_names:
                continue
            series.append(
                MetricSeries(
                    metric_name=metadata["metricName"],
                    entity_name=metadata["entityName"],
                    category=metadata["attributes"]["category"],
                    attributes=metadata["attributes"],
                    points=[
                        MetricPoint(timestamp=p["timestamp"], value=p["value"])
                        for p in ts["data"]
                    ],
                )
            )
    return series


def parse_events(raw: dict, category: str, alert_only: bool) -> list[Event]:
    return [
        Event(
            id=item["id"],
            content=item["content"],
            time_occurred=item["timeOccurred"],
            category=item["category"],
            severity=item["severity"],
            alert=item["alert"],
            attributes=item.get("attributes", {}),
        )
        for item in raw["items"]
        if item["category"] == category and (not alert_only or item["alert"])
    ]
