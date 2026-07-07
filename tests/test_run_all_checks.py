"""Tests for the full monitoring run (run_all_checks -> HealthReport)."""

from datetime import datetime, timezone

from checks import ALL_CHECKS, run_all_checks
from data_sources import (
    DataSource,
    DiskUsage,
    Event,
    HealthCheck,
    Host,
    LogFile,
    MetricPoint,
    MetricSeries,
    PingResult,
    Role,
    Service,
)

FIXED_NOW = datetime(2026, 7, 1, 17, 40, 30, tzinfo=timezone.utc)


class HealthyClusterSource(DataSource):
    """A hand-built, perfectly healthy cluster — proves the report comes back
    all-green when nothing is wrong (the sample data in data/ can't show this,
    because it deliberately contains problems)."""

    def get_hosts(self) -> list[Host]:
        return [
            Host(
                host_id="h1",
                hostname="clean1.internal",
                ip_address="10.0.0.1",
                health_summary="GOOD",
                last_heartbeat=FIXED_NOW,
                health_checks=[HealthCheck(name="HOST_SCM_HEALTH", summary="GOOD")],
                num_cores=8,
                total_phys_mem_bytes=34359738368,
            )
        ]

    def get_services(self, cluster_name: str) -> list[Service]:
        return [
            Service(
                name="hdfs",
                type="HDFS",
                cluster_name=cluster_name,
                service_state="STARTED",
                health_summary="GOOD",
                health_checks=[HealthCheck(name="HDFS_FREE_SPACE_REMAINING", summary="GOOD")],
            )
        ]

    def get_roles(self, cluster_name: str, service_name: str) -> list[Role]:
        return [
            Role(
                name=f"{service_name}-ROLE-1",
                type="ROLE",
                service_name=service_name,
                host_id="h1",
                health_summary="GOOD",
                health_checks=[HealthCheck(name="ROLE_HEALTH", summary="GOOD")],
            )
        ]

    def get_metrics(self, metric_names: list[str]) -> list[MetricSeries]:
        everything = [
            MetricSeries(
                metric_name="cpu_percent", entity_name="clean1.internal", category="HOST",
                attributes={"category": "HOST"},
                points=[MetricPoint(timestamp=FIXED_NOW, value=10.0)],
            ),
            MetricSeries(
                metric_name="physical_memory_used", entity_name="clean1.internal", category="HOST",
                attributes={"category": "HOST"},
                points=[MetricPoint(timestamp=FIXED_NOW, value=1000)],
            ),
            MetricSeries(
                metric_name="physical_memory_total", entity_name="clean1.internal", category="HOST",
                attributes={"category": "HOST"},
                points=[MetricPoint(timestamp=FIXED_NOW, value=10000)],
            ),
            MetricSeries(
                metric_name="fs_bytes_used_percent", entity_name="clean1.internal",
                category="FILESYSTEM",
                attributes={"category": "FILESYSTEM", "mount_point": "/var"},
                points=[MetricPoint(timestamp=FIXED_NOW, value=10.0)],
            ),
            MetricSeries(
                metric_name="dfs_capacity_used", entity_name="hdfs", category="SERVICE",
                attributes={"category": "SERVICE"},
                points=[
                    MetricPoint(timestamp=FIXED_NOW, value=1000),
                    MetricPoint(timestamp=FIXED_NOW, value=1010),
                ],
            ),
            MetricSeries(
                metric_name="host_network_frame_errors_rate", entity_name="clean1.internal",
                category="HOST", attributes={"category": "HOST"},
                points=[MetricPoint(timestamp=FIXED_NOW, value=0.0)],
            ),
        ]
        if not metric_names:
            return everything
        return [s for s in everything if s.metric_name in metric_names]

    def get_events(self, category: str = "HEALTH_CHECK", alert_only: bool = True) -> list[Event]:
        return []

    def get_disk_usage(self) -> list[DiskUsage]:
        return [DiskUsage(hostname="clean1.internal", mount_point="/var", used_percent=10.0)]

    def ping_hosts(self) -> list[PingResult]:
        return [PingResult(hostname="clean1.internal", reachable=True, latency_ms=0.5)]

    def get_log_files(self) -> list[LogFile]:
        return [LogFile(hostname="clean1.internal", path="/var/log/small.log", size_bytes=1024)]


def test_sample_data_produces_a_report_with_all_nine_breaching(source, tenant):
    report = run_all_checks(source, tenant, now=FIXED_NOW)

    assert report.tenant_id == "example-dev"
    assert len(report.results) == len(ALL_CHECKS) == 9
    assert report.has_breaches is True
    assert report.breach_count == 9
    assert {r.task for r in report.breached_results} == {
        "host_health",
        "heartbeat",
        "cpu_percent",
        "ram_percent",
        "disk_percent",
        "hdfs_health",
        "service_status",
        "alerts",
        "network",
    }


def test_a_healthy_cluster_produces_an_all_green_report(tenant):
    report = run_all_checks(HealthyClusterSource(), tenant, now=FIXED_NOW)

    assert report.has_breaches is False
    assert report.breach_count == 0
    assert all(r.status == "OK" for r in report.results)
