"""Per-user KPI (dashboard metric) access: admin grants a subset of the nine
checks to a user, and that user can only see/query/analyze those KPIs.
"""

from backend.app.engine.kpi_access import ALL_KPI_TASKS
from .conftest import auth_header


def _make_restricted_user(client, admin_tokens, email, allowed_kpis):
    created = client.post("/admin/users/create", json={
        "email": email, "role": "user", "allowed_kpis": allowed_kpis,
    }, headers=auth_header(admin_tokens)).json()
    login = client.post("/auth/login", json={"email": email, "password": created["temp_password"]})
    return created["user_id"], {"access_token": login.json()["access_token"]}


def test_unrestricted_user_sees_all_nine_kpis(client, admin_tokens, user_tokens, export_tenant):
    # a normal user with no allowed_kpis restriction (and access to the tenant)
    users = client.get("/admin/users", headers=auth_header(admin_tokens)).json()
    uid = next(u["id"] for u in users if u["email"].startswith("user@"))
    client.post(f"/admin/tenants/{export_tenant}/link/{uid}", headers=auth_header(admin_tokens))

    r = client.get(f"/tenants/{export_tenant}/report", params={"as_of": "2026-07-02"}, headers=auth_header(user_tokens))
    assert r.status_code == 200
    tasks = {x["task"] for x in r.json()["results"]}
    assert tasks == set(ALL_KPI_TASKS)


def test_restricted_user_report_only_shows_granted_kpis(client, admin_tokens, export_tenant):
    uid, token = _make_restricted_user(client, admin_tokens, "hostonly@blutechconsulting.com", ["host_health"])
    client.post(f"/admin/tenants/{export_tenant}/link/{uid}", headers=auth_header(admin_tokens))

    r = client.get(f"/tenants/{export_tenant}/report", params={"as_of": "2026-07-02"}, headers=auth_header(token))
    assert r.status_code == 200
    body = r.json()
    tasks = {x["task"] for x in body["results"]}
    assert tasks == {"host_health"}
    # breach_count is recomputed over only the visible KPIs, so the ring/counts stay consistent
    assert body["breach_count"] == sum(1 for x in body["results"] if x["status"] == "BREACH")


def test_restricted_user_cannot_query_a_hidden_single_kpi(client, admin_tokens, export_tenant):
    uid, token = _make_restricted_user(client, admin_tokens, "hostonly2@blutechconsulting.com", ["host_health"])
    client.post(f"/admin/tenants/{export_tenant}/link/{uid}", headers=auth_header(admin_tokens))

    # allowed KPI -> 200
    ok = client.get(f"/tenants/{export_tenant}/report/host_health", params={"as_of": "2026-07-02"}, headers=auth_header(token))
    assert ok.status_code == 200
    # hidden KPI -> 403
    denied = client.get(f"/tenants/{export_tenant}/report/disk_percent", params={"as_of": "2026-07-02"}, headers=auth_header(token))
    assert denied.status_code == 403


def test_restricted_user_cannot_analyze_a_hidden_kpi(client, admin_tokens, export_tenant):
    uid, token = _make_restricted_user(client, admin_tokens, "hostonly3@blutechconsulting.com", ["host_health"])
    client.post(f"/admin/tenants/{export_tenant}/link/{uid}", headers=auth_header(admin_tokens))

    denied = client.post(f"/tenants/{export_tenant}/analyze/disk_percent",
                         params={"as_of": "2026-07-02"}, headers=auth_header(token))
    assert denied.status_code == 403


def test_admin_always_sees_all_kpis_even_with_allowed_kpis_set(client, admin_tokens, export_tenant):
    # give the admin account a restrictive allowed_kpis — admins ignore it
    users = client.get("/admin/users", headers=auth_header(admin_tokens)).json()
    admin_id = next(u["id"] for u in users if u["role"] == "admin")
    r = client.patch(f"/admin/users/{admin_id}/access",
                     json={"allowed_models": [], "allowed_kpis": ["host_health"]},
                     headers=auth_header(admin_tokens))
    assert r.status_code == 200
    assert r.json()["allowed_kpis"] == ["host_health"]

    report = client.get(f"/tenants/{export_tenant}/report", params={"as_of": "2026-07-02"}, headers=auth_header(admin_tokens))
    tasks = {x["task"] for x in report.json()["results"]}
    assert tasks == set(ALL_KPI_TASKS)  # admin still sees all nine


def test_set_access_persists_and_validates_allowed_kpis(client, admin_tokens):
    created = client.post("/admin/users/create", json={"email": "kpicfg@blutechconsulting.com", "role": "user"},
                          headers=auth_header(admin_tokens)).json()
    uid = created["user_id"]

    ok = client.patch(f"/admin/users/{uid}/access",
                      json={"allowed_models": [], "allowed_kpis": ["cpu_percent", "ram_percent"]},
                      headers=auth_header(admin_tokens))
    assert ok.status_code == 200
    assert ok.json()["allowed_kpis"] == ["cpu_percent", "ram_percent"]

    # unknown KPI is rejected
    bad = client.patch(f"/admin/users/{uid}/access",
                       json={"allowed_models": [], "allowed_kpis": ["not_a_real_kpi"]},
                       headers=auth_header(admin_tokens))
    assert bad.status_code == 400

    # clearing it (empty) restores full access
    cleared = client.patch(f"/admin/users/{uid}/access",
                           json={"allowed_models": [], "allowed_kpis": []},
                           headers=auth_header(admin_tokens))
    assert cleared.json()["allowed_kpis"] == []


def test_restricted_user_only_sees_thresholds_for_granted_kpis(client, admin_tokens, export_tenant):
    """Regression: the thresholds modal leaked all 9 KPIs' limits to a user who
    could only see some of them."""
    uid, token = _make_restricted_user(client, admin_tokens, "thresh1@blutechconsulting.com", ["host_health", "cpu_percent"])
    client.post(f"/admin/tenants/{export_tenant}/link/{uid}", headers=auth_header(admin_tokens))

    r = client.get(f"/tenants/{export_tenant}/thresholds", headers=auth_header(token))
    assert r.status_code == 200
    # cpu_percent has a tunable limit; host_health has none — so only cpu_pct shows
    assert set(r.json()) == {"cpu_pct"}

    # an unrestricted admin still sees every threshold
    admin_view = client.get(f"/tenants/{export_tenant}/thresholds", headers=auth_header(admin_tokens)).json()
    assert {"cpu_pct", "ram_pct", "disk_pct", "heartbeat_window_sec", "network_error_rate_threshold"} <= set(admin_view)


def test_restricted_user_cannot_edit_a_hidden_threshold(client, admin_tokens, export_tenant):
    uid, token = _make_restricted_user(client, admin_tokens, "thresh2@blutechconsulting.com", ["cpu_percent"])
    client.post(f"/admin/tenants/{export_tenant}/link/{uid}", headers=auth_header(admin_tokens))

    # allowed threshold -> works
    ok = client.put(f"/tenants/{export_tenant}/thresholds", json={"cpu_pct": 55},
                    headers=auth_header(token))
    assert ok.status_code == 200
    # hidden threshold (ram_percent isn't granted) -> 403, not silently applied
    denied = client.put(f"/tenants/{export_tenant}/thresholds", json={"ram_pct": 12},
                        headers=auth_header(token))
    assert denied.status_code == 403


def test_restricted_user_only_sees_refresh_settings_for_granted_kpis(client, admin_tokens):
    """Regression: Settings -> KPI refresh time listed all 9 rows regardless of access."""
    uid, token = _make_restricted_user(client, admin_tokens, "refresh1@blutechconsulting.com", ["host_health", "alerts"])

    r = client.get("/settings/kpi-refresh", headers=auth_header(token))
    assert r.status_code == 200
    assert {row["task"] for row in r.json()} == {"host_health", "alerts"}

    # and can't tune a KPI they can't see
    denied = client.put("/settings/kpi-refresh", json={"task": "disk_percent", "seconds": 60},
                        headers=auth_header(token))
    assert denied.status_code == 403
    assert client.delete("/settings/kpi-refresh/disk_percent", headers=auth_header(token)).status_code == 403


def test_kpi_access_changes_flow_through_to_thresholds_and_refresh(client, admin_tokens, export_tenant):
    """Granting/revoking a KPI later must add/remove its threshold + refresh row."""
    uid, token = _make_restricted_user(client, admin_tokens, "flow@blutechconsulting.com", ["cpu_percent"])
    client.post(f"/admin/tenants/{export_tenant}/link/{uid}", headers=auth_header(admin_tokens))

    assert set(client.get(f"/tenants/{export_tenant}/thresholds", headers=auth_header(token)).json()) == {"cpu_pct"}
    assert {r["task"] for r in client.get("/settings/kpi-refresh", headers=auth_header(token)).json()} == {"cpu_percent"}

    # admin grants network too
    client.patch(f"/admin/users/{uid}/access",
                 json={"allowed_models": [], "allowed_kpis": ["cpu_percent", "network"]},
                 headers=auth_header(admin_tokens))
    assert set(client.get(f"/tenants/{export_tenant}/thresholds", headers=auth_header(token)).json()) == {
        "cpu_pct", "network_error_rate_threshold"}
    assert {r["task"] for r in client.get("/settings/kpi-refresh", headers=auth_header(token)).json()} == {
        "cpu_percent", "network"}

    # admin revokes cpu_percent
    client.patch(f"/admin/users/{uid}/access",
                 json={"allowed_models": [], "allowed_kpis": ["network"]},
                 headers=auth_header(admin_tokens))
    assert set(client.get(f"/tenants/{export_tenant}/thresholds", headers=auth_header(token)).json()) == {
        "network_error_rate_threshold"}
    assert {r["task"] for r in client.get("/settings/kpi-refresh", headers=auth_header(token)).json()} == {"network"}


def test_create_user_with_kpi_subset(client, admin_tokens):
    created = client.post("/admin/users/create", json={
        "email": "kpicreate@blutechconsulting.com", "role": "user", "allowed_kpis": ["alerts", "hdfs_health"],
    }, headers=auth_header(admin_tokens))
    assert created.status_code == 201
    detail = client.get(f"/admin/users/{created.json()['user_id']}/detail", headers=auth_header(admin_tokens)).json()
    assert set(detail["allowed_kpis"]) == {"alerts", "hdfs_health"}
