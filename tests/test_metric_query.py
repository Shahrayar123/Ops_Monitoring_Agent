import pytest

from cloudera import build_metric_query


def test_single_metric():
    assert build_metric_query(["cpu_percent"], "HOST") == "select cpu_percent where category=HOST"


def test_multiple_metrics():
    query = build_metric_query(["physical_memory_used", "physical_memory_total"], "HOST")
    assert query == "select physical_memory_used, physical_memory_total where category=HOST"


def test_extra_filter_is_appended():
    query = build_metric_query(["dfs_capacity_used"], "SERVICE", extra_filter="serviceName=hdfs")
    assert query == "select dfs_capacity_used where category=SERVICE and serviceName=hdfs"


def test_at_least_one_metric_is_required():
    with pytest.raises(ValueError):
        build_metric_query([], "HOST")
