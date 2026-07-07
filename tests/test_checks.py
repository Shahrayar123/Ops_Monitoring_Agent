"""One test per check, using the sample data in data/ — which deliberately
contains a problem for every check so each breach path is exercised."""

from datetime import datetime, timezone

from checks import (
    check_alerts,
    check_cpu_percent,
    check_disk_percent,
    check_hdfs_health,
    check_heartbeat,
    check_host_health,
    check_network,
    check_ram_percent,
    check_service_status,
)

NODE1 = "node1.example-customer.internal"
NODE2 = "node2.example-customer.internal"
NODE3 = "node3.example-customer.internal"

# A fixed "now" close to the sample data's timestamps, so heartbeat ages don't
# depend on when the tests run.
FIXED_NOW = datetime(2026, 7, 1, 17, 40, 30, tzinfo=timezone.utc)


def test_host_health_flags_the_unhealthy_host(source, tenant):
    result = check_host_health(source, tenant)

    assert result.status == "BREACH"
    assert result.breached_entities == [NODE3]


def test_heartbeat_flags_only_the_silent_host(source, tenant):
    result = check_heartbeat(source, tenant, now=FIXED_NOW)

    assert result.status == "BREACH"
    assert result.breached_entities == [NODE3]


def test_cpu_flags_the_host_over_the_limit(source, tenant):
    result = check_cpu_percent(source, tenant)

    assert result.status == "BREACH"
    assert result.threshold == 60.0
    assert result.breached_entities == [NODE2]


def test_ram_flags_the_host_over_the_limit(source, tenant):
    result = check_ram_percent(source, tenant)

    assert result.status == "BREACH"
    assert result.threshold == 60.0
    assert result.breached_entities == [NODE2]


def test_disk_flags_the_full_mount_and_the_big_log(source, tenant):
    result = check_disk_percent(source, tenant)

    assert result.status == "BREACH"
    assert f"{NODE2}:/var" in result.breached_entities
    assert any(e.startswith(f"{NODE2}:log:") for e in result.breached_entities)


def test_hdfs_flags_unusual_storage_growth(source, tenant):
    result = check_hdfs_health(source, tenant)

    assert result.status == "BREACH"
    assert result.breached_entities == ["hdfs"]
    assert "grew" in result.detail


def test_service_status_flags_yarn_but_not_healthy_services(source, tenant):
    result = check_service_status(source, tenant)

    assert result.status == "BREACH"
    assert any(e.startswith("yarn:") for e in result.breached_entities)
    assert not any(e.startswith("hdfs:") for e in result.breached_entities)
    assert not any(e.startswith("hbase:") for e in result.breached_entities)


def test_alerts_flags_the_active_alert_events(source, tenant):
    result = check_alerts(source, tenant)

    assert result.status == "BREACH"
    assert set(result.breached_entities) == {"evt-1", "evt-2"}


def test_network_flags_error_rates_and_unreachable_hosts(source, tenant):
    result = check_network(source, tenant)

    assert result.status == "BREACH"
    assert NODE2 in result.breached_entities
    assert NODE3 in result.breached_entities
    assert NODE1 not in result.breached_entities
