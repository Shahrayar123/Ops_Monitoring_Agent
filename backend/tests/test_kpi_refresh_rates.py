"""Per-user KPI card refresh-rate overrides: /settings/kpi-refresh."""

from backend.app.engine.bridge import DEFAULT_REFRESH_RATES
from .conftest import auth_header


def test_defaults_with_no_overrides(client, user_tokens):
    r = client.get("/settings/kpi-refresh", headers=auth_header(user_tokens))
    assert r.status_code == 200
    body = {row["task"]: row for row in r.json()}
    assert set(body) == set(DEFAULT_REFRESH_RATES)
    for task, default in DEFAULT_REFRESH_RATES.items():
        assert body[task]["seconds"] == default
        assert body[task]["default_seconds"] == default
        assert body[task]["is_override"] is False


def test_set_and_clear_an_override(client, user_tokens):
    r = client.put("/settings/kpi-refresh", json={"task": "cpu_percent", "seconds": 120}, headers=auth_header(user_tokens))
    assert r.status_code == 200
    body = {row["task"]: row for row in r.json()}
    assert body["cpu_percent"]["seconds"] == 120
    assert body["cpu_percent"]["is_override"] is True
    # everything else stays at default
    assert body["ram_percent"]["seconds"] == DEFAULT_REFRESH_RATES["ram_percent"]
    assert body["ram_percent"]["is_override"] is False

    # persisted — a fresh GET reflects it
    r2 = client.get("/settings/kpi-refresh", headers=auth_header(user_tokens))
    body2 = {row["task"]: row for row in r2.json()}
    assert body2["cpu_percent"]["seconds"] == 120

    # clearing it falls back to the default
    r3 = client.delete("/settings/kpi-refresh/cpu_percent", headers=auth_header(user_tokens))
    body3 = {row["task"]: row for row in r3.json()}
    assert body3["cpu_percent"]["seconds"] == DEFAULT_REFRESH_RATES["cpu_percent"]
    assert body3["cpu_percent"]["is_override"] is False


def test_updating_an_existing_override_replaces_it(client, user_tokens):
    client.put("/settings/kpi-refresh", json={"task": "disk_percent", "seconds": 90}, headers=auth_header(user_tokens))
    r = client.put("/settings/kpi-refresh", json={"task": "disk_percent", "seconds": 45}, headers=auth_header(user_tokens))
    body = {row["task"]: row for row in r.json()}
    assert body["disk_percent"]["seconds"] == 45  # replaced, not duplicated


def test_rejects_unknown_task_and_out_of_range_seconds(client, user_tokens):
    assert client.put("/settings/kpi-refresh", json={"task": "not_a_real_check", "seconds": 30},
                       headers=auth_header(user_tokens)).status_code == 404
    assert client.delete("/settings/kpi-refresh/not_a_real_check", headers=auth_header(user_tokens)).status_code == 404
    # below the 5s floor and above the 3600s ceiling
    assert client.put("/settings/kpi-refresh", json={"task": "cpu_percent", "seconds": 1},
                       headers=auth_header(user_tokens)).status_code == 422
    assert client.put("/settings/kpi-refresh", json={"task": "cpu_percent", "seconds": 999999},
                       headers=auth_header(user_tokens)).status_code == 422


def test_requires_auth(client):
    assert client.get("/settings/kpi-refresh").status_code == 401


def test_override_is_isolated_per_user(client, admin_tokens, user_tokens):
    client.put("/settings/kpi-refresh", json={"task": "alerts", "seconds": 300}, headers=auth_header(user_tokens))
    admin_view = {row["task"]: row for row in client.get("/settings/kpi-refresh", headers=auth_header(admin_tokens)).json()}
    assert admin_view["alerts"]["seconds"] == DEFAULT_REFRESH_RATES["alerts"]  # unaffected by the other user's override
    assert admin_view["alerts"]["is_override"] is False


def test_report_and_refresh_rates_endpoints_apply_the_users_override(client, admin_tokens, user_tokens, export_tenant):
    client.post(f"/admin/tenants/{export_tenant}/link/1", headers=auth_header(admin_tokens))  # ensure admin path unaffected
    client.put("/settings/kpi-refresh", json={"task": "heartbeat", "seconds": 222}, headers=auth_header(admin_tokens))

    rates = client.get(f"/tenants/{export_tenant}/refresh-rates", headers=auth_header(admin_tokens)).json()
    assert rates["heartbeat"] == 222

    report = client.get(f"/tenants/{export_tenant}/report", params={"as_of": "2026-07-02"}, headers=auth_header(admin_tokens)).json()
    assert report["refresh_rates"]["heartbeat"] == 222
    # a check this admin never overrode still reports the cluster/engine default
    assert report["refresh_rates"]["disk_percent"] == DEFAULT_REFRESH_RATES["disk_percent"]
