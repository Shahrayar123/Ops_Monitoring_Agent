"""Phase 5 tests: knowledge retrieval, dependency graph, disk trends, the
severity floor + JSON parsing, and the analysis endpoints/job flow.

The real model is never called: pure logic is tested directly, and the endpoint
tests monkeypatch the analyzer to return an instant fake.
"""

import time
from datetime import date
from pathlib import Path

import pytest

from backend.app.ai import dependencies, knowledge, models
from backend.app.ai.models import AiFinding, KpiAnalysis
from backend.app.db.models import Tenant, UserTenant
from .conftest import auth_header

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------- knowledge ----------


def test_knowledge_returns_the_check_section_for_a_task():
    hits = knowledge.search("disk_percent", "/u01 at 96.9% full")
    assert hits, "expected at least one snippet"
    top = hits[0]
    assert "cloudera_best_practices.md" in top.source
    assert "disk" in top.heading.lower()


def test_knowledge_search_is_task_specific():
    disk = knowledge.search("disk_percent")[0].heading
    alerts = knowledge.search("alerts")[0].heading
    assert disk != alerts


def test_known_issues_xlsx_is_loaded_and_searchable():
    # the actionable known-issues spreadsheet is parsed alongside the .md files
    assert "cloudera_actionalable_known_isssues.xlsx" in knowledge.available_sources()
    hits = knowledge.search("hdfs_health", "NameNode down")
    xlsx = [h for h in hits if h.source.endswith(".xlsx")]
    assert xlsx, "expected a known-issues row for hdfs_health"
    # each row carries its actionable resolution, not just the symptom
    assert any("Resolution (agent action):" in h.text for h in xlsx)


def test_xlsx_rows_are_tagged_to_the_right_check():
    # a "Service Status" category row surfaces for the service_status check
    hits = knowledge.search("service_status")
    top_xlsx = next((h for h in hits if h.source.endswith(".xlsx")), None)
    assert top_xlsx is not None
    assert "service" in top_xlsx.heading.lower()


def test_prompt_includes_version_and_both_knowledge_sources():
    from backend.app.ai import prompts

    result = {
        "task": "disk_percent", "status": "BREACH",
        "detail": "/var/log at 95% full", "threshold": "85%",
        "evidence": {"source": "disk.json", "rows": [{"entity": "h1:/var/log", "value": "95%", "breached": True}]},
    }
    system, user, snips = prompts.build_kpi_prompt(
        cluster="bdaktprod-cluster", version="7.1.9", result=result,
        trend_text="(No time-to-full projection applies to this check.)",
    )
    # the Cloudera version is prominent context for the model
    assert "Cloudera version 7.1.9" in user
    assert "version" in system.lower()
    # both the best-practices guide and the actionable known-issues table are cited
    sources = {s.source for s in snips}
    assert "cloudera_best_practices.md" in sources
    assert "cloudera_actionalable_known_isssues.xlsx" in sources


# ---------- dependency graph ----------


def test_dependency_downstream_and_reverse():
    downs = [e.affects for e in dependencies.downstream_of("host_health")]
    assert "heartbeat" in downs and "network" in downs
    # reverse lookup: heartbeat is affected by host_health
    assert "host_health" in dependencies.affected_by("heartbeat")


def test_disk_percent_is_a_root_cause_not_an_effect():
    # nothing in the graph lists disk_percent as a downstream effect
    assert dependencies.affected_by("disk_percent") == []


# ---------- severity floor + parsing ----------


def test_severity_floor_bumps_many_critical_alerts_to_critical():
    assert models.severity_floor("alerts", "28 critical, 0 important active alerts") == "CRITICAL"
    assert models.apply_floor("MEDIUM", "alerts", "28 critical active alerts") == "CRITICAL"


def test_severity_floor_never_lowers_a_higher_model_severity():
    # model said CRITICAL, floor is HIGH -> stays CRITICAL
    assert models.apply_floor("CRITICAL", "hdfs_health", "healthSummary=CONCERNING") == "CRITICAL"


def test_findings_order_most_severe_first():
    findings = [
        AiFinding(primary_task="a", severity="MEDIUM"),
        AiFinding(primary_task="b", severity="CRITICAL"),
        AiFinding(primary_task="c", severity="HIGH"),
    ]
    ordered = [f.severity for f in models.order_findings(findings)]
    assert ordered == ["CRITICAL", "HIGH", "MEDIUM"]


def test_extract_json_tolerates_fences_and_prose():
    text = 'Here is the analysis:\n```json\n{"severity": "HIGH", "summary": "x"}\n```\nDone.'
    data = models.extract_json(text)
    assert data["severity"] == "HIGH"


def test_coerce_str_list_handles_string_or_list():
    assert models.coerce_str_list(["a", "b"]) == ["a", "b"]
    assert models.coerce_str_list("1. first\n2. second") == ["first", "second"]


# ---------- disk trend extrapolation ----------


def test_disk_projection_math():
    from backend.app.ai import trends

    # a mount at 90% rising 1%/h -> 10h to full
    class P:
        def __init__(self, ts, v):
            self.timestamp, self.value = ts, v

    from datetime import datetime, timezone

    class S:
        entity_name = "h1"
        attributes = {"mount_point": "/u01"}
        points = [
            P(datetime(2026, 7, 2, 0, tzinfo=timezone.utc), 85.0),
            P(datetime(2026, 7, 2, 5, tzinfo=timezone.utc), 90.0),
        ]

    class Src:
        def get_metrics(self, names):
            return [S()]

    class Cfg:
        class thresholds:
            disk_mounts = ["/u01"]

    proj = trends.disk_projections(Src(), Cfg())
    assert len(proj) == 1
    assert proj[0].rate_pct_per_hour == 1.0
    assert proj[0].hours_to_full == 10.0


# ---------- endpoints + job flow ----------


@pytest.fixture()
def export_tenant(db_session):
    data_dir = REPO_ROOT / "data" / "bdaktprod"
    if not (data_dir / "hosts").is_dir():
        pytest.skip("bdaktprod export data not present")
    s = db_session()
    t = Tenant(slug="bdaktprod", display_name="BDA", cluster_name="bdaktprod-cluster",
               cloudera_version="7.1.9", data_source_mode="json", data_dir=str(data_dir),
               thresholds={"disk_mounts": [f"/u{n:02d}" for n in range(1, 17)] + ["/var", "/opt", "/home", "/tmp"],
                           "heartbeat_window_sec": 1800})
    s.add(t); s.commit(); s.close()
    return "bdaktprod"


def _poll(client, tokens, job_id, timeout=10):
    for _ in range(int(timeout / 0.2)):
        r = client.get(f"/analysis/{job_id}", headers=auth_header(tokens))
        if r.json()["status"] != "running":
            return r.json()
        time.sleep(0.2)
    raise AssertionError("job did not finish")


def test_analyze_unknown_task_is_404(client, admin_tokens, export_tenant):
    r = client.post(f"/tenants/{export_tenant}/analyze/nope", headers=auth_header(admin_tokens))
    assert r.status_code == 404


def test_kpi_analysis_job_flow(client, admin_tokens, export_tenant, monkeypatch, db_session):
    # Fake the analyzer so no real model runs, and point the background job's
    # session factory at the test database (it defaults to the real Postgres one).
    from backend.app.ai import analyzer, jobs

    monkeypatch.setattr(jobs, "SessionLocal", db_session)

    def fake_kpi(db, user, tenant, task, as_of=None):
        return KpiAnalysis(task=task, severity="CRITICAL", summary="fake",
                           remediation=["do x"], impact="affects hdfs", model_used="qwen2.5:7b")
    monkeypatch.setattr(analyzer, "analyze_kpi", fake_kpi)

    start = client.post(f"/tenants/{export_tenant}/analyze/disk_percent", headers=auth_header(admin_tokens))
    assert start.status_code == 200
    job = _poll(client, admin_tokens, start.json()["job_id"])
    assert job["status"] == "done"
    assert job["result"]["severity"] == "CRITICAL"
    assert job["result"]["summary"] == "fake"


def test_analyze_non_breaching_task_reports_no_breach(client, admin_tokens, export_tenant, monkeypatch, db_session):
    # heartbeat is OK on bdaktprod; the real analyzer raises NoBreach BEFORE any
    # model call, so this is safe and fast.
    from backend.app.ai import jobs

    monkeypatch.setattr(jobs, "SessionLocal", db_session)
    start = client.post(f"/tenants/{export_tenant}/analyze/heartbeat",
                        params={"as_of": "2026-07-02"}, headers=auth_header(admin_tokens))
    assert start.status_code == 200
    job = _poll(client, admin_tokens, start.json()["job_id"])
    assert job["status"] == "no_breach"


def test_dependencies_endpoint(client, admin_tokens, export_tenant):
    r = client.get(f"/tenants/{export_tenant}/dependencies", headers=auth_header(admin_tokens))
    assert r.status_code == 200
    body = r.json()
    assert "host_health" in body["downstream"]
    assert "host_health" in body["affected_by"]["heartbeat"]


def test_analyze_blocked_when_over_limit(client, admin_tokens, export_tenant, db_session):
    # Fill the admin's plan daily limit so preflight rejects with 429.
    from backend.app.db.models import ApiUsage, User
    from sqlalchemy import select
    s = db_session()
    admin = s.scalar(select(User).where(User.email.like("admin@%")))
    limit = admin.plan.daily_api_limit
    for _ in range(limit):
        s.add(ApiUsage(user_id=admin.id, model_id="qwen2.5:7b", provider="ollama", kind="analysis", total_tokens=6, success=True))
    s.commit(); s.close()

    r = client.post(f"/tenants/{export_tenant}/analyze/disk_percent", headers=auth_header(admin_tokens))
    assert r.status_code == 429
