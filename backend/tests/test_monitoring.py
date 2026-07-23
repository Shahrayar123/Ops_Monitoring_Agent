"""Phase 3 tests: monitoring reports, thresholds, tenant admin, upload validation.

These drive the real engine against the committed sample data (tests/sample_data),
so they exercise the DB-tenant -> engine bridge end to end without needing the
large bdaktprod export.
"""

import json
from pathlib import Path

import pytest

from backend.app.db.models import Role, User, UserTenant
from backend.app.core.security import hash_password
from .conftest import ADMIN_EMAIL, ADMIN_PASSWORD, auth_header

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_DIR = REPO_ROOT / "tests" / "sample_data"   # committed synthetic export? -> see note


def test_report_runs_all_nine_checks(client, admin_tokens, export_tenant):
    r = client.get(f"/tenants/{export_tenant}/report", params={"as_of": "2026-07-02"}, headers=auth_header(admin_tokens))
    assert r.status_code == 200
    body = r.json()
    assert len(body["results"]) == 9
    assert body["data_source_mode"] == "json"
    assert body["cloudera_version"] == "7.1.9"
    assert set(body["refresh_rates"]) >= {"alerts", "hdfs_health"}
    # evidence flows through
    disk = next(x for x in body["results"] if x["task"] == "disk_percent")
    assert disk["evidence"]["rows"]
    assert disk["evidence"]["source"].endswith("disk.json")


def test_single_check_endpoint(client, admin_tokens, export_tenant):
    r = client.get(f"/tenants/{export_tenant}/report/alerts", params={"as_of": "2026-07-02"}, headers=auth_header(admin_tokens))
    assert r.status_code == 200
    assert r.json()["task"] == "alerts"
    # unknown check -> 404
    assert client.get(f"/tenants/{export_tenant}/report/nope", headers=auth_header(admin_tokens)).status_code == 404


def test_date_filter_changes_results(client, admin_tokens, export_tenant):
    early = client.get(f"/tenants/{export_tenant}/report", params={"as_of": "2026-06-25"}, headers=auth_header(admin_tokens)).json()
    late = client.get(f"/tenants/{export_tenant}/report", params={"as_of": "2026-07-02"}, headers=auth_header(admin_tokens)).json()
    assert early["breach_count"] != late["breach_count"]


def test_thresholds_get_and_update(client, admin_tokens, export_tenant):
    orig = client.get(f"/tenants/{export_tenant}/thresholds", headers=auth_header(admin_tokens)).json()
    assert orig["heartbeat_window_sec"] == 1800

    r = client.put(f"/tenants/{export_tenant}/thresholds", json={"cpu_pct": 42}, headers=auth_header(admin_tokens))
    assert r.status_code == 200 and r.json()["cpu_pct"] == 42
    # persisted + used by the report
    rep = client.get(f"/tenants/{export_tenant}/report", params={"as_of": "2026-07-02"}, headers=auth_header(admin_tokens)).json()
    cpu = next(x for x in rep["results"] if x["task"] == "cpu_percent")
    assert cpu["threshold"] == 42


def test_invalid_threshold_rejected(client, admin_tokens, export_tenant):
    r = client.put(f"/tenants/{export_tenant}/thresholds", json={"cpu_pct": 150}, headers=auth_header(admin_tokens))
    # Rejected either at the request schema (422) or the engine validation (400).
    assert r.status_code in (400, 422)
    assert "error" in r.json()


# ---------- access control ----------


def test_normal_user_cannot_see_unlinked_tenant(client, user_tokens, export_tenant):
    r = client.get(f"/tenants/{export_tenant}/report", headers=auth_header(user_tokens))
    assert r.status_code == 403


def test_unknown_tenant_is_404(client, admin_tokens):
    assert client.get("/tenants/ghost/report", headers=auth_header(admin_tokens)).status_code == 404


# ---------- admin tenant management ----------


def test_admin_creates_tenant_and_uploads_are_validated(client, admin_tokens):
    # create a fresh json-mode tenant
    r = client.post("/admin/tenants", json={
        "slug": "acme-dev", "display_name": "Acme Dev", "cluster_name": "acme", "data_source_mode": "json",
    }, headers=auth_header(admin_tokens))
    assert r.status_code == 201

    # a garbage "hosts" file is rejected with 422 and a clear reason
    bad = client.post(
        "/admin/tenants/acme-dev/files",
        data={"file_type": "hosts"},
        files={"file": ("hosts.json", b'{"not":"a host"}', "application/json")},
        headers=auth_header(admin_tokens),
    )
    assert bad.status_code == 422
    assert "hostname" in bad.json()["error"]["message"].lower() or "shape" in bad.json()["error"]["message"].lower()

    # non-JSON is rejected too
    bad2 = client.post(
        "/admin/tenants/acme-dev/files",
        data={"file_type": "cpu"},
        files={"file": ("cpu.json", b"not json at all", "application/json")},
        headers=auth_header(admin_tokens),
    )
    assert bad2.status_code == 422


def test_admin_upload_accepts_a_real_host_file(client, admin_tokens):
    data_dir = REPO_ROOT / "data" / "bdaktprod" / "hosts"
    if not data_dir.is_dir():
        pytest.skip("bdaktprod host files not present")
    host_file = next(data_dir.glob("*.json"))
    client.post("/admin/tenants", json={
        "slug": "acme2", "display_name": "Acme 2", "cluster_name": "acme2", "data_source_mode": "json",
    }, headers=auth_header(admin_tokens))
    r = client.post(
        "/admin/tenants/acme2/files",
        data={"file_type": "hosts"},
        files={"file": (host_file.name, host_file.read_bytes(), "application/json")},
        headers=auth_header(admin_tokens),
    )
    assert r.status_code == 200
    files = r.json()["files"]
    assert any(f["file_type"] == "hosts" and f["validation_status"] == "ok" for f in files)


def test_tenant_admin_requires_admin(client, user_tokens):
    r = client.post("/admin/tenants", json={
        "slug": "x", "display_name": "X", "cluster_name": "x",
    }, headers=auth_header(user_tokens))
    assert r.status_code == 403


# ---------- user <-> cluster access ----------


def test_normal_user_gains_access_only_after_admin_links_them(client, admin_tokens, user_tokens):
    client.post("/admin/tenants", json={
        "slug": "linktest", "display_name": "Link Test", "cluster_name": "linktest",
    }, headers=auth_header(admin_tokens))

    # not linked yet -> 403 for the normal user
    denied = client.get("/tenants/linktest/report", headers=auth_header(user_tokens))
    assert denied.status_code == 403

    # find the normal user's id
    users = client.get("/admin/users", headers=auth_header(admin_tokens)).json()
    uid = next(u["id"] for u in users if u["email"].startswith("user@"))

    link = client.post(f"/admin/tenants/linktest/link/{uid}", headers=auth_header(admin_tokens))
    assert link.status_code == 204

    # now shows up in both directions
    on_tenant = client.get("/admin/tenants/linktest/users", headers=auth_header(admin_tokens)).json()
    assert any(u["id"] == uid for u in on_tenant)
    on_user = client.get(f"/admin/users/{uid}/clusters", headers=auth_header(admin_tokens)).json()
    assert any(t["slug"] == "linktest" for t in on_user)

    # and the normal user can now see it in their own tenant list
    mine = client.get("/tenants", headers=auth_header(user_tokens)).json()
    assert any(t["slug"] == "linktest" for t in mine)

    # unlink revokes it again
    unlink = client.delete(f"/admin/tenants/linktest/link/{uid}", headers=auth_header(admin_tokens))
    assert unlink.status_code == 204
    mine_after = client.get("/tenants", headers=auth_header(user_tokens)).json()
    assert not any(t["slug"] == "linktest" for t in mine_after)


def test_cluster_access_endpoints_require_admin(client, user_tokens):
    assert client.post("/admin/tenants/linktest/link/1", headers=auth_header(user_tokens)).status_code == 403
    assert client.get("/admin/users/1/clusters", headers=auth_header(user_tokens)).status_code == 403
    assert client.put("/admin/users/1/clusters", json={"tenant_slugs": []}, headers=auth_header(user_tokens)).status_code == 403


def test_admin_sets_users_whole_cluster_set_in_one_save(client, admin_tokens):
    client.post("/admin/tenants", json={
        "slug": "bulk-a", "display_name": "Bulk A", "cluster_name": "bulk-a",
    }, headers=auth_header(admin_tokens))
    client.post("/admin/tenants", json={
        "slug": "bulk-b", "display_name": "Bulk B", "cluster_name": "bulk-b",
    }, headers=auth_header(admin_tokens))

    created = client.post("/admin/users/create", json={
        "email": "bulkset@blutechconsulting.com", "role": "user", "tenant_slugs": ["bulk-a"],
    }, headers=auth_header(admin_tokens))
    uid = created.json()["user_id"]

    # replace the set: drop bulk-a, add bulk-b — both clusters can be assigned
    # to one user at once, and the dashboard's tenant list should pick both up
    r = client.put(f"/admin/users/{uid}/clusters", json={"tenant_slugs": ["bulk-b"]}, headers=auth_header(admin_tokens))
    assert r.status_code == 200
    slugs = {t["slug"] for t in r.json()}
    assert slugs == {"bulk-b"}

    on_user = client.get(f"/admin/users/{uid}/clusters", headers=auth_header(admin_tokens)).json()
    assert {t["slug"] for t in on_user} == {"bulk-b"}

    # multiple clusters at once
    r2 = client.put(f"/admin/users/{uid}/clusters", json={"tenant_slugs": ["bulk-a", "bulk-b"]}, headers=auth_header(admin_tokens))
    assert {t["slug"] for t in r2.json()} == {"bulk-a", "bulk-b"}
    login = client.post("/auth/login", json={"email": "bulkset@blutechconsulting.com", "password": created.json()["temp_password"]})
    token = {"access_token": login.json()["access_token"]}
    mine = {t["slug"] for t in client.get("/tenants", headers=auth_header(token)).json()}
    assert mine == {"bulk-a", "bulk-b"}

    # clearing it out removes all access
    r3 = client.put(f"/admin/users/{uid}/clusters", json={"tenant_slugs": []}, headers=auth_header(admin_tokens))
    assert r3.json() == []
    assert client.get(f"/admin/users/{uid}/clusters", headers=auth_header(admin_tokens)).json() == []


def test_set_clusters_rejects_unknown_slug_and_unknown_user(client, admin_tokens):
    created = client.post("/admin/users/create", json={
        "email": "bulkbad@blutechconsulting.com", "role": "user",
    }, headers=auth_header(admin_tokens))
    uid = created.json()["user_id"]

    r = client.put(f"/admin/users/{uid}/clusters", json={"tenant_slugs": ["ghost-cluster"]}, headers=auth_header(admin_tokens))
    assert r.status_code == 404

    assert client.put("/admin/users/999999/clusters", json={"tenant_slugs": []}, headers=auth_header(admin_tokens)).status_code == 404


def test_admin_can_assign_clusters_at_user_creation_time(client, admin_tokens):
    client.post("/admin/tenants", json={
        "slug": "createtime", "display_name": "Create Time Cluster", "cluster_name": "createtime",
    }, headers=auth_header(admin_tokens))

    created = client.post("/admin/users/create", json={
        "email": "precreated@blutechconsulting.com", "role": "user", "tenant_slugs": ["createtime"],
    }, headers=auth_header(admin_tokens))
    assert created.status_code == 201
    uid = created.json()["user_id"]

    # linked immediately — no separate "assign after creation" step needed
    on_user = client.get(f"/admin/users/{uid}/clusters", headers=auth_header(admin_tokens)).json()
    assert any(t["slug"] == "createtime" for t in on_user)

    login = client.post("/auth/login", json={"email": "precreated@blutechconsulting.com", "password": created.json()["temp_password"]})
    token = {"access_token": login.json()["access_token"]}
    mine = client.get("/tenants", headers=auth_header(token)).json()
    assert any(t["slug"] == "createtime" for t in mine)

    # and the assigned cluster is actually reachable (not a 403) — this tenant
    # has no uploaded data yet, so the report itself may 409 "not ready"; the
    # point here is proving access, not data availability.
    report = client.get("/tenants/createtime/report", headers=auth_header(token))
    assert report.status_code != 403


def test_create_user_rejects_unknown_cluster_slug(client, admin_tokens):
    r = client.post("/admin/users/create", json={
        "email": "badcluster@blutechconsulting.com", "role": "user", "tenant_slugs": ["does-not-exist"],
    }, headers=auth_header(admin_tokens))
    assert r.status_code == 404
    # and no user was created (the failed cluster check happens before insert)
    users = client.get("/admin/users", headers=auth_header(admin_tokens)).json()
    assert not any(u["email"] == "badcluster@blutechconsulting.com" for u in users)
