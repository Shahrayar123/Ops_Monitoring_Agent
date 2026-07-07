"""Tests for JsonDataSource — the offline source that reads data/sample_*.json."""

import pytest

from data_sources import JsonDataSource

CLUSTER = "Example-Cluster"


def test_hosts_are_parsed_with_all_fields(source):
    hosts = source.get_hosts()

    assert len(hosts) == 3
    node3 = next(h for h in hosts if h.hostname == "node3.example-customer.internal")
    assert node3.health_summary == "CONCERNING"
    assert node3.num_cores == 16
    assert any(hc.name == "HOST_SCM_HEALTH" for hc in node3.health_checks)


def test_services_are_filtered_by_cluster(source):
    services = source.get_services(CLUSTER)

    assert {s.name for s in services} == {"hdfs", "yarn", "hbase"}
    yarn = next(s for s in services if s.name == "yarn")
    assert yarn.health_summary == "CONCERNING"

    assert source.get_services("some-other-cluster") == []


def test_roles_are_filtered_by_cluster_and_service(source):
    roles = source.get_roles(CLUSTER, "yarn")

    assert {r.type for r in roles} == {"RESOURCEMANAGER", "NODEMANAGER"}
    rm = next(r for r in roles if r.type == "RESOURCEMANAGER")
    assert rm.health_summary == "CONCERNING"

    assert source.get_roles(CLUSTER, "does-not-exist") == []


def test_metrics_are_filtered_by_name(source):
    series = source.get_metrics(["cpu_percent"])

    assert len(series) == 3
    assert all(s.metric_name == "cpu_percent" for s in series)
    node2 = next(s for s in series if s.entity_name == "node2.example-customer.internal")
    assert node2.points[-1].value == 71.2


def test_empty_metric_filter_returns_everything(source):
    series = source.get_metrics([])

    names = {s.metric_name for s in series}
    assert "dfs_capacity" in names
    assert "dfs_capacity_used" in names


def test_storage_growth_is_visible_in_the_sample_data(source):
    series = source.get_metrics(["dfs_capacity_used"])

    assert len(series) == 1
    points = series[0].points
    assert len(points) == 2
    growth_pct = (points[1].value - points[0].value) / points[0].value * 100
    assert growth_pct > 10.0  # the sample data deliberately shows unusual growth


def test_events_default_to_active_alerts_only(source):
    events = source.get_events()

    assert len(events) == 2  # the third sample event is alert=false
    assert all(e.alert for e in events)
    assert all(e.category == "HEALTH_CHECK" for e in events)


def test_events_can_include_non_alerts(source):
    assert len(source.get_events(alert_only=False)) == 3


def test_disk_usage_comes_from_the_ssh_sample_file(source):
    disk_usage = source.get_disk_usage()

    full_disk = next(
        d for d in disk_usage
        if d.hostname == "node2.example-customer.internal" and d.mount_point == "/var"
    )
    assert full_disk.used_percent > 90.0


def test_ping_results_come_from_the_ssh_sample_file(source):
    results = source.ping_hosts()

    node3 = next(r for r in results if r.hostname == "node3.example-customer.internal")
    assert node3.reachable is False
    assert node3.latency_ms is None


def test_log_files_come_from_the_ssh_sample_file(source):
    log_files = source.get_log_files()

    big_logs = [f for f in log_files if f.size_bytes > 1024 * 1024 * 1024]
    assert len(big_logs) == 1
    assert big_logs[0].hostname == "node2.example-customer.internal"


def test_missing_data_file_gives_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="sample_hosts.json"):
        JsonDataSource(tmp_path)
