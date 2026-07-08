"""Proves the live-API source returns exactly the same records as the JSON
source for the same underlying data — so the checks genuinely can't tell the
difference. Uses a fake HTTP layer and fake SSH (no real cluster exists yet)."""

import json
from pathlib import Path

import httpx
import pytest

from config import load_tenant_config
from data_sources import ClouderaApiSource, JsonDataSource, MissingEnvVarError

DATA_DIR = Path("tests/sample_data")


def _load(name: str) -> dict:
    with (DATA_DIR / name).open(encoding="utf-8") as f:
        return json.load(f)


def _fake_cluster(request: httpx.Request) -> httpx.Response:
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
    return httpx.Response(404, text=f"no fake route for {path}")


class FakeSsh:
    """Answers SSH questions from the sample file instead of real machines."""

    def __init__(self, ssh_results: dict):
        self._data = ssh_results

    def ping_host(self, hostname: str) -> dict:
        return next(e for e in self._data["ping_results"] if e["hostname"] == hostname)

    def get_disk_usage(self, hostname: str, mounts: list[str]) -> list[dict]:
        return [
            e for e in self._data["disk_usage"]
            if e["hostname"] == hostname and e["mount_point"] in mounts
        ]

    def get_log_files(self, hostname: str, log_dirs: list[str]) -> list[dict]:
        return [e for e in self._data["log_files"] if e["hostname"] == hostname]


@pytest.fixture
def api_tenant(monkeypatch):
    monkeypatch.setenv("EXAMPLE_TENANT_CM_USERNAME", "fake-user")
    monkeypatch.setenv("EXAMPLE_TENANT_CM_PASSWORD", "fake-pass")
    monkeypatch.setenv("EXAMPLE_TENANT_SSH_USERNAME", "fake-ssh-user")
    monkeypatch.setenv("EXAMPLE_TENANT_SSH_KEY_PATH", "/fake/key")
    return load_tenant_config("config/tenants/example-api.template.yaml")


@pytest.fixture
def api_source(api_tenant):
    return ClouderaApiSource(
        api_tenant,
        transport=httpx.MockTransport(_fake_cluster),
        ssh=FakeSsh(_load("sample_ssh_results.json")),
    )


@pytest.fixture
def json_source():
    return JsonDataSource("tests/sample_data")


def _sorted(items):
    return sorted(items, key=str)


def test_hosts_match_the_json_source(api_source, json_source):
    assert api_source.get_hosts() == json_source.get_hosts()


def test_services_match_the_json_source(api_source, json_source, api_tenant):
    cluster = api_tenant.cluster_name
    assert api_source.get_services(cluster) == json_source.get_services(cluster)


def test_roles_match_the_json_source(api_source, json_source, api_tenant):
    cluster = api_tenant.cluster_name
    assert api_source.get_roles(cluster, "yarn") == json_source.get_roles(cluster, "yarn")


def test_metrics_match_the_json_source(api_source, json_source):
    assert _sorted(api_source.get_metrics(["cpu_percent"])) == _sorted(
        json_source.get_metrics(["cpu_percent"])
    )


def test_metrics_spanning_two_categories_are_fetched_in_grouped_queries(api_source, json_source):
    # memory metrics are HOST category, dfs_capacity_used is SERVICE — one call
    # must fan out into one query per category and still match.
    metrics = ["physical_memory_used", "physical_memory_total", "dfs_capacity_used"]
    assert _sorted(api_source.get_metrics(metrics)) == _sorted(json_source.get_metrics(metrics))


def test_events_return_the_active_alerts(api_source, json_source):
    # The API parser handles the real list-shaped `attributes`, so records aren't
    # byte-identical to the synthetic JSON source — but the alert events (by id
    # and severity) must match.
    api_events = {(e.id, e.severity) for e in api_source.get_events()}
    json_events = {(e.id, e.severity) for e in json_source.get_events()}
    assert api_events == json_events


def test_disk_usage_matches_the_json_source(api_source, json_source):
    assert _sorted(api_source.get_disk_usage()) == _sorted(json_source.get_disk_usage())


def test_ping_matches_the_json_source(api_source, json_source):
    assert _sorted(api_source.ping_hosts()) == _sorted(json_source.ping_hosts())


def test_log_files_match_the_json_source(api_source, json_source):
    assert _sorted(api_source.get_log_files()) == _sorted(json_source.get_log_files())


def test_a_missing_credential_env_var_fails_with_its_name(monkeypatch):
    monkeypatch.delenv("EXAMPLE_TENANT_CM_USERNAME", raising=False)
    monkeypatch.delenv("EXAMPLE_TENANT_CM_PASSWORD", raising=False)
    tenant = load_tenant_config("config/tenants/example-api.template.yaml")

    with pytest.raises(MissingEnvVarError, match="EXAMPLE_TENANT_CM_USERNAME"):
        ClouderaApiSource(tenant, transport=httpx.MockTransport(_fake_cluster))


def test_ssh_methods_explain_when_ssh_is_not_configured(monkeypatch):
    monkeypatch.setenv("EXAMPLE_TENANT_CM_USERNAME", "fake-user")
    monkeypatch.setenv("EXAMPLE_TENANT_CM_PASSWORD", "fake-pass")
    tenant = load_tenant_config("config/tenants/example-api.template.yaml")
    tenant = tenant.model_copy(update={"ssh": None})

    source = ClouderaApiSource(tenant, transport=httpx.MockTransport(_fake_cluster))

    with pytest.raises(ValueError, match="no SSH settings"):
        source.ping_hosts()
