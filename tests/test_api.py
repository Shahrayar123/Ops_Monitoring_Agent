"""Tests for the FastAPI backend.

The endpoints just wrap the same backend the checks use, so these tests confirm
the HTTP surface: right status codes, right JSON shape, date filtering, and the
friendly 409 when a tenant's live source isn't set up yet.
"""

import pytest
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert "status" in resp.json()


def test_list_tenants_includes_the_export_tenant():
    resp = client.get("/tenants")
    assert resp.status_code == 200
    tenants = {t["tenant_id"]: t for t in resp.json()}
    assert "bdaktprod" in tenants
    assert tenants["bdaktprod"]["source_kind"] == "export"


def test_dates_for_the_export_tenant():
    resp = client.get("/tenants/bdaktprod/dates")
    assert resp.status_code == 200
    dates = resp.json()["dates"]
    assert len(dates) >= 2
    assert dates == sorted(dates)


def test_report_runs_all_checks():
    resp = client.get("/tenants/bdaktprod/report", params={"as_of": "2026-07-02"})
    assert resp.status_code == 200
    report = resp.json()
    tasks = {r["task"]: r["status"] for r in report["results"]}
    assert len(report["results"]) == 9
    # bdaktprod now has services + events exports, so every check runs (no NO_DATA).
    assert report["no_data_count"] == 0
    assert tasks["service_status"] in ("OK", "BREACH")
    assert tasks["alerts"] in ("OK", "BREACH")


def test_report_date_filter_changes_the_result():
    early = client.get("/tenants/bdaktprod/report", params={"as_of": "2026-06-25"}).json()
    late = client.get("/tenants/bdaktprod/report", params={"as_of": "2026-07-02"}).json()
    # disk fills up between the two days, so the breach count differs
    assert early["breach_count"] != late["breach_count"]


def test_unknown_tenant_is_404():
    assert client.get("/tenants/does-not-exist/report").status_code == 404


def test_live_api_tenant_without_credentials_is_409():
    # example-api-tenant is configured for the live API but has no reachable
    # cluster, so building its data source fails with a clear 409.
    resp = client.get("/tenants/example-api-tenant/report")
    assert resp.status_code == 409
    assert "detail" in resp.json()


def test_polling_an_unknown_job_is_404():
    assert client.get("/analysis/nope").status_code == 404


def test_get_and_update_thresholds_round_trip():
    original = client.get("/tenants/example-dev/thresholds").json()
    assert "cpu_pct" in original
    try:
        # update one value
        resp = client.put("/tenants/example-dev/thresholds", json={"cpu_pct": 72.0})
        assert resp.status_code == 200
        assert resp.json()["cpu_pct"] == 72.0
        # persisted: a fresh GET reflects it, and the report uses it
        assert client.get("/tenants/example-dev/thresholds").json()["cpu_pct"] == 72.0
        report = client.get("/tenants/example-dev/report").json()
        cpu = next(r for r in report["results"] if r["task"] == "cpu_percent")
        assert cpu["threshold"] == 72.0
    finally:
        client.put("/tenants/example-dev/thresholds", json={"cpu_pct": original["cpu_pct"]})


def test_invalid_threshold_is_rejected():
    resp = client.put("/tenants/example-dev/thresholds", json={"cpu_pct": 150})
    assert resp.status_code == 400
    assert "detail" in resp.json()


def test_thresholds_for_unknown_tenant_is_404():
    assert client.get("/tenants/nope/thresholds").status_code == 404
    assert client.put("/tenants/nope/thresholds", json={"cpu_pct": 50}).status_code == 404


def test_start_analysis_returns_a_running_job(monkeypatch):
    # Replace the (slow, real) AI call with an instant fake so the test is fast.
    from ai_analysis import AiReport
    import api.jobs as jobs_module

    async def fake_ai(report, source, tenant, llm):
        return AiReport(overall_summary="fake", findings=[], priority_order=[])

    monkeypatch.setattr(jobs_module, "run_ai_analysis", fake_ai)

    start = client.post("/tenants/example-dev/analyze")
    assert start.status_code == 200
    job_id = start.json()["job_id"]

    # Poll a few times for the background task to finish.
    import time

    for _ in range(20):
        job = client.get(f"/analysis/{job_id}").json()
        if job["status"] in ("done", "error", "no_breaches"):
            break
        time.sleep(0.1)
    assert job["status"] == "done"
    assert job["result"]["overall_summary"] == "fake"
