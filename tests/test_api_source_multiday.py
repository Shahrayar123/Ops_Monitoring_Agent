"""The live API source pulls several days of history (like the file exports),
so the date picker and day filter work in live mode too. These tests use a mock
transport that returns 3 days of hourly CPU data.
"""

from datetime import date

import httpx
import pytest

from config import load_tenant_config
from data_sources.api_source import ClouderaApiSource


def _cpu_3_days() -> dict:
    """Three days of hourly cpu_percent for one host, shaped like the CM API."""
    data = []
    for day in (25, 26, 27):
        for hour in range(0, 24):
            data.append({"timestamp": f"2026-06-{day:02d}T{hour:02d}:00:00.000Z", "value": 10.0})
    return {
        "items": [
            {
                "timeSeries": [
                    {
                        "metadata": {
                            "metricName": "cpu_percent",
                            "entityName": "host-a",
                            "attributes": {"hostname": "host-a", "category": "HOST"},
                        },
                        "data": data,
                    }
                ]
            }
        ]
    }


_calls = {"count": 0}


def _handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/version":
        return httpx.Response(200, text="v49")
    if request.url.path.endswith("/timeseries") and "cpu_percent" in request.url.params.get("query", ""):
        _calls["count"] += 1
        # confirm we asked for ~7 days of history, not just today
        assert "from" in request.url.params
        return httpx.Response(200, json=_cpu_3_days())
    return httpx.Response(200, json={"items": []})


@pytest.fixture
def api_source(monkeypatch):
    monkeypatch.setenv("EXAMPLE_TENANT_CM_USERNAME", "u")
    monkeypatch.setenv("EXAMPLE_TENANT_CM_PASSWORD", "p")
    monkeypatch.setenv("EXAMPLE_TENANT_SSH_USERNAME", "u")
    monkeypatch.setenv("EXAMPLE_TENANT_SSH_KEY_PATH", "/fake/key")
    tenant = load_tenant_config("config/tenants/example-api.template.yaml")
    _calls["count"] = 0
    return ClouderaApiSource(tenant, transport=httpx.MockTransport(_handler))


def test_tenant_defaults_are_read_from_config(api_source):
    # The template doesn't override them, so the schema defaults apply.
    assert api_source._lookback_days == 3
    assert api_source._cache_ttl_sec == 300


def test_per_tenant_lookback_and_ttl_are_honored(monkeypatch):
    monkeypatch.setenv("EXAMPLE_TENANT_CM_USERNAME", "u")
    monkeypatch.setenv("EXAMPLE_TENANT_CM_PASSWORD", "p")
    monkeypatch.setenv("EXAMPLE_TENANT_SSH_USERNAME", "u")
    monkeypatch.setenv("EXAMPLE_TENANT_SSH_KEY_PATH", "/fake/key")
    tenant = load_tenant_config("config/tenants/example-api.template.yaml")
    # Override the two settings on this tenant's cloudera block.
    tenant = tenant.model_copy(
        update={"cloudera": tenant.cloudera.model_copy(update={"lookback_days": 7, "metrics_cache_ttl_sec": 60})}
    )
    src = ClouderaApiSource(tenant, transport=httpx.MockTransport(_handler))
    assert src._lookback_days == 7
    assert src._cache_ttl_sec == 60


def test_available_dates_lists_every_day_in_the_history(api_source):
    assert api_source.available_dates() == [date(2026, 6, 25), date(2026, 6, 26), date(2026, 6, 27)]


def test_as_of_trims_to_the_selected_day(api_source):
    api_source.as_of = date(2026, 6, 26)
    series = api_source.get_metrics(["cpu_percent"])
    latest_day = max(p.timestamp.date() for s in series for p in s.points)
    assert latest_day == date(2026, 6, 26)  # nothing from the 27th


def test_no_as_of_returns_the_full_history(api_source):
    api_source.as_of = None
    series = api_source.get_metrics(["cpu_percent"])
    assert max(p.timestamp.date() for s in series for p in s.points) == date(2026, 6, 27)


def test_metrics_are_cached_not_refetched_every_call(api_source):
    api_source.get_metrics(["cpu_percent"])
    first = _calls["count"]
    api_source.get_metrics(["cpu_percent"])  # should hit the cache
    assert _calls["count"] == first
