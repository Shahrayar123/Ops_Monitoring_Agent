"""Tests for the AI analyst.

The second test talks to a real local Ollama model and takes several minutes on
CPU; it is skipped automatically when Ollama isn't running.
"""

import asyncio
from datetime import datetime, timezone

import httpx
import pytest

from ai_analysis import AiReport, order_findings_for_display, priority_labels, run_ai_analysis
from ai_analysis.analyzer import AiFinding, _apply_severity_floor, _severity_floor
from checks import CheckResult, run_all_checks
from checks.run_all_checks import HealthReport
from config import load_llm_config

FIXED_NOW = datetime(2026, 7, 1, 17, 40, 30, tzinfo=timezone.utc)


def _ollama_running(base_url: str) -> bool:
    try:
        httpx.get(base_url.replace("/v1", "/api/tags"), timeout=2.0)
        return True
    except httpx.HTTPError:
        return False


def test_the_ai_refuses_to_run_on_a_healthy_report(source, tenant):
    report = run_all_checks(source, tenant, now=FIXED_NOW)
    # Flip every result to OK to simulate a healthy cluster — proves the
    # "no LLM call when nothing is wrong" rule is enforced in code.
    healthy = report.model_copy(
        update={"results": [r.model_copy(update={"status": "OK"}) for r in report.results]}
    )

    with pytest.raises(ValueError, match="healthy report"):
        asyncio.run(run_ai_analysis(healthy, source, tenant, load_llm_config()))


@pytest.mark.skipif(
    not _ollama_running(load_llm_config().base_url),
    reason="Ollama is not running locally",
)
def test_the_ai_produces_a_structured_report_from_real_breaches(source, tenant):
    report = run_all_checks(source, tenant, now=FIXED_NOW)
    assert report.has_breaches

    ai_report = asyncio.run(run_ai_analysis(report, source, tenant, load_llm_config()))

    assert isinstance(ai_report, AiReport)
    assert ai_report.overall_summary
    assert len(ai_report.findings) > 0
    assert all(f.severity in {"LOW", "MEDIUM", "HIGH", "CRITICAL"} for f in ai_report.findings)
    assert len(ai_report.priority_order) > 0


# --- severity floor: guards against the LLM under-ranking a serious finding ---
# (reported bug: 52 CRITICAL Cloudera alerts got labeled "MEDIUM" by the AI)


def _alerts_check(detail: str, breach_count: int = 1) -> CheckResult:
    return CheckResult(
        task="alerts", status="BREACH", metric="active_alerts",
        threshold="0 critical/important", breached_entities=["e"] * breach_count, detail=detail,
    )


def test_many_critical_alerts_floor_to_critical():
    check = _alerts_check("52 critical, 1 important active alerts. Examples: ...", 53)
    assert _severity_floor(check) == "CRITICAL"


def test_a_few_critical_alerts_floor_to_high():
    check = _alerts_check("2 critical, 0 important active alerts. Examples: ...", 2)
    assert _severity_floor(check) == "HIGH"


def test_important_only_alerts_floor_to_medium():
    check = _alerts_check("0 critical, 3 important active alerts. Examples: ...", 3)
    assert _severity_floor(check) == "MEDIUM"


def test_bad_health_summary_floors_to_critical():
    check = CheckResult(
        task="host_health", status="BREACH", metric="healthSummary", threshold="GOOD",
        breached_entities=["node1"], detail="node1: healthSummary=BAD",
    )
    assert _severity_floor(check) == "CRITICAL"


def test_apply_severity_floor_bumps_an_underranked_finding():
    check = _alerts_check("52 critical, 1 important active alerts. Examples: ...", 53)
    report = HealthReport(
        tenant_id="t", cluster_name="c", timestamp=datetime.now(timezone.utc), results=[check]
    )
    ai_report = AiReport(
        overall_summary="x",
        findings=[AiFinding(
            primary_task="alerts", severity="MEDIUM", summary="s",
            related_tasks=[], recommended_remediation="r",
        )],
        priority_order=["alerts"],
    )

    fixed = _apply_severity_floor(report, ai_report)

    assert fixed.findings[0].severity == "CRITICAL"


# --- display ordering: the finding cards and the priority line must agree ---


def _finding(task: str, severity: str) -> AiFinding:
    return AiFinding(
        primary_task=task, severity=severity, summary="s",
        related_tasks=[], recommended_remediation="r",
    )


def test_findings_are_ordered_by_severity_first():
    ai = AiReport(
        overall_summary="x",
        findings=[  # deliberately NOT in severity order
            _finding("hdfs_health", "MEDIUM"),
            _finding("host_health", "CRITICAL"),
            _finding("disk_percent", "HIGH"),
        ],
        priority_order=["hdfs_health", "host_health", "disk_percent"],
    )
    ordered = order_findings_for_display(ai)
    assert [f.severity for f in ordered] == ["CRITICAL", "HIGH", "MEDIUM"]
    assert [f.primary_task for f in ordered] == ["host_health", "disk_percent", "hdfs_health"]


def test_priority_order_breaks_ties_within_the_same_severity():
    ai = AiReport(
        overall_summary="x",
        findings=[_finding("alerts", "CRITICAL"), _finding("host_health", "CRITICAL")],
        # both CRITICAL — the AI's priority_order decides which comes first
        priority_order=["host_health", "alerts"],
    )
    ordered = order_findings_for_display(ai)
    assert [f.primary_task for f in ordered] == ["host_health", "alerts"]


def test_priority_line_matches_the_card_order():
    ai = AiReport(
        overall_summary="x",
        findings=[
            _finding("host_health", "CRITICAL"),
            _finding("disk_percent", "HIGH"),
            _finding("service_status", "HIGH"),
            _finding("alerts", "CRITICAL"),
        ],
        priority_order=["service_status", "host_health", "alerts", "disk_percent"],
    )
    ordered = order_findings_for_display(ai)
    # The line is built from the ordered cards, so the two can never disagree.
    assert priority_labels(ordered) == [f.primary_task for f in ordered]


def test_apply_severity_floor_never_lowers_a_higher_ai_severity():
    check = _alerts_check("1 critical, 0 important active alerts. Examples: ...", 1)  # floor: HIGH
    report = HealthReport(
        tenant_id="t", cluster_name="c", timestamp=datetime.now(timezone.utc), results=[check]
    )
    ai_report = AiReport(
        overall_summary="x",
        findings=[AiFinding(
            primary_task="alerts", severity="CRITICAL", summary="s",
            related_tasks=[], recommended_remediation="r",
        )],
        priority_order=["alerts"],
    )

    fixed = _apply_severity_floor(report, ai_report)

    assert fixed.findings[0].severity == "CRITICAL"  # unchanged, AI's own call stands
