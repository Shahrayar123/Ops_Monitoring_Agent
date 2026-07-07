"""Tests for the Cloudera Manager API client, using a fake HTTP layer — there
is no real cluster to test against yet."""

import json
from pathlib import Path

import httpx
import pytest

from cloudera import ClouderaApiClient, ClouderaApiError

DATA_DIR = Path("tests/sample_data")


def _load(name: str) -> dict:
    with (DATA_DIR / name).open(encoding="utf-8") as f:
        return json.load(f)


def _fake_cluster(request: httpx.Request) -> httpx.Response:
    """Answers like a real Cloudera Manager would, using the sample data."""
    path = request.url.path

    if path == "/api/version":
        return httpx.Response(200, text="v51")
    if path == "/api/v51/hosts":
        return httpx.Response(200, json=_load("sample_hosts.json"))
    if path == "/api/v51/clusters/Example-Cluster/services":
        return httpx.Response(200, json=_load("sample_services.json"))
    if path == "/api/v51/clusters/Example-Cluster/services/yarn/roles":
        return httpx.Response(200, json=_load("sample_roles.json"))
    if path == "/api/v51/timeseries":
        return httpx.Response(200, json=_load("sample_timeseries.json"))
    if path == "/api/v51/events":
        return httpx.Response(200, json=_load("sample_events.json"))
    if path == "/api/v51/broken":
        return httpx.Response(500, text="boom")

    return httpx.Response(404, text=f"no fake route for {path}")


@pytest.fixture
def client():
    return ClouderaApiClient(
        cm_host="cm.fake.internal",
        port=7183,
        username="fake-user",
        password="fake-pass",
        transport=httpx.MockTransport(_fake_cluster),
    )


def test_resolve_version_asks_the_cluster(client):
    assert client.resolve_version() == "v51"


def test_get_hosts_uses_the_resolved_version_in_the_url(client):
    raw = client.get_hosts()
    assert raw["items"][0]["hostname"] == "node1.example-customer.internal"


def test_get_services_uses_the_cluster_scoped_path(client):
    raw = client.get_services("Example-Cluster")
    assert {s["name"] for s in raw["items"]} == {"hdfs", "yarn", "hbase"}


def test_get_roles_uses_the_service_scoped_path(client):
    # The fake only answers on the yarn-scoped path, so getting a non-404
    # response already proves the URL was built correctly.
    raw = client.get_roles("Example-Cluster", "yarn")
    assert "items" in raw
    assert any(item["serviceRef"]["serviceName"] == "yarn" for item in raw["items"])


def test_query_metrics(client):
    raw = client.query_metrics("select cpu_percent where category=HOST")
    assert "items" in raw


def test_get_events(client):
    raw = client.get_events("alert==true;category==HEALTH_CHECK")
    assert len(raw["items"]) == 3


def test_an_error_response_raises_cloudera_api_error(client):
    with pytest.raises(ClouderaApiError):
        client._get("/broken")
