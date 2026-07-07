"""Tests for reading the real Cloudera Manager API exports (data/bdaktprod/)."""

from datetime import date

import pytest

from checks import run_all_checks
from config import load_tenant_config
from data_sources import ClouderaExportSource

EXPORT_DIR = "data/bdaktprod"


@pytest.fixture
def export_tenant():
    return load_tenant_config("config/tenants/bdaktprod.yaml")


@pytest.fixture
def export_source():
    return ClouderaExportSource(EXPORT_DIR)


def test_reads_all_hosts_from_the_host_files(export_source):
    hosts = export_source.get_hosts()
    assert len(hosts) == 3
    assert all(h.hostname.startswith("bdaktprod-") for h in hosts)


def test_cpu_covers_all_fourteen_hosts(export_source):
    cpu = export_source.get_metrics(["cpu_percent"])
    assert len(cpu) == 14
    assert all(s.metric_name == "cpu_percent" for s in cpu)


def test_disk_capacity_is_turned_into_a_used_percent(export_source):
    disk = export_source.get_metrics(["fs_bytes_used_percent"])
    assert disk, "expected filesystem series"
    # every point should be a sensible percentage
    for s in disk:
        for p in s.points:
            assert 0.0 <= p.value <= 100.0
        assert "mount_point" in s.attributes


def test_hdfs_capacity_is_summed_into_one_cluster_series(export_source):
    hdfs = export_source.get_metrics(["dfs_capacity_used"])
    assert len(hdfs) == 1
    assert hdfs[0].entity_name == "hdfs"
    assert len(hdfs[0].points) >= 2


def test_services_and_events_report_as_unavailable(export_source):
    assert export_source.has_services() is False
    assert export_source.has_events() is False


def test_available_dates_span_the_exported_range(export_source):
    dates = export_source.available_dates()
    assert dates == sorted(dates)
    assert all(isinstance(d, date) for d in dates)
    assert len(dates) >= 2


def test_as_of_filters_metrics_to_that_day(export_source):
    dates = export_source.available_dates()
    earliest, latest = dates[0], dates[-1]

    export_source.as_of = earliest
    early = export_source.get_metrics(["cpu_percent"])
    latest_ts_early = max(p.timestamp.date() for s in early for p in s.points)
    assert latest_ts_early <= earliest

    export_source.as_of = latest
    full = export_source.get_metrics(["cpu_percent"])
    assert max(p.timestamp.date() for s in full for p in s.points) == latest


def test_full_run_on_real_data_gives_a_sensible_report(export_source, export_tenant):
    export_source.as_of = export_source.available_dates()[-1]
    report = run_all_checks(export_source, export_tenant, now=export_source.reference_now())

    by_task = {r.task: r.status for r in report.results}
    # services/alerts have no source yet
    assert by_task["service_status"] == "NO_DATA"
    assert by_task["alerts"] == "NO_DATA"
    # these have real data and must have actually run
    for task in ("cpu_percent", "ram_percent", "disk_percent", "hdfs_health", "network"):
        assert by_task[task] in ("OK", "BREACH")
    assert report.no_data_count == 2
