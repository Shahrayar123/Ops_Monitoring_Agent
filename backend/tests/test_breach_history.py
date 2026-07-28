"""The cross-user breach/AI-analysis corpus written to context/breach_history.csv.

The file is a side effect of every analysis, so the tests that matter most are
the ones proving it can never take an analysis down with it.
"""

import csv

import pytest

from backend.app.ai import breach_history
from backend.app.ai.models import AiFinding, IncidentReport, KpiAnalysis


@pytest.fixture
def history(tmp_path, monkeypatch):
    """Point the module at a throwaway file instead of the real context/ dir."""
    target = tmp_path / "breach_history.csv"
    monkeypatch.setattr(breach_history, "CONTEXT_DIR", tmp_path)
    monkeypatch.setattr(breach_history, "HISTORY_FILE", target)
    return target


def _rows(path):
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _kpi(**over) -> KpiAnalysis:
    base = dict(
        task="disk_percent", severity="HIGH",
        summary="/u01 is 96.9% full on node3.",
        remediation=["Rotate logs in /var/log", "Expand the volume"],
        impact="HDFS writes will fail once the mount is full.",
        related_tasks=["hdfs_health"], trend_note="Full in ~3 days.",
        sources=["cloudera_best_practices.md"], model_used="qwen2.5:7b",
    )
    base.update(over)
    return KpiAnalysis(**base)


def test_kpi_analysis_is_appended_with_a_header(history):
    breach_history.record_kpi(_kpi(), cluster="bdaktprod", version="7.1.7", breach_detail="/u01 at 96.9%")

    rows = _rows(history)
    assert len(rows) == 1
    row = rows[0]
    assert row["analysis_type"] == "kpi"
    assert row["cluster"] == "bdaktprod"
    assert row["task"] == "disk_percent"
    assert row["severity"] == "HIGH"
    assert row["breach_detail"] == "/u01 at 96.9%"          # engine's measurement
    assert "96.9% full" in row["summary"]                    # model's words
    assert row["remediation"] == "Rotate logs in /var/log | Expand the volume"
    assert "HDFS writes" in row["impact"]
    assert row["model_used"] == "qwen2.5:7b"


def test_appends_accumulate_and_the_header_is_written_only_once(history):
    for task in ("disk_percent", "cpu_percent", "hdfs_health"):
        breach_history.record_kpi(_kpi(task=task), cluster="c1", version="7.1.7", breach_detail=f"{task} bad")

    assert len(_rows(history)) == 3
    # one header line + three data lines, and nothing blank in between
    lines = [ln for ln in history.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 4
    assert lines[0].startswith("timestamp,")


def test_incident_report_writes_one_row_per_finding_sharing_the_overall_summary(history):
    report = IncidentReport(
        overall_summary="Disk pressure on node3 is cascading into HDFS.",
        findings=[
            AiFinding(primary_task="disk_percent", severity="CRITICAL", summary="Mount nearly full.",
                      remediation=["Free space"], related_tasks=["hdfs_health"]),
            AiFinding(primary_task="hdfs_health", severity="HIGH", summary="Under-replicated blocks."),
        ],
        model_used="nemotron",
    )
    breach_history.record_incident(
        report, cluster="bdaktprod", version="7.1.7",
        details={"disk_percent": "/u01 at 99%", "hdfs_health": "CONCERNING"},
    )

    rows = _rows(history)
    assert [r["task"] for r in rows] == ["disk_percent", "hdfs_health"]
    assert all(r["analysis_type"] == "incident" for r in rows)
    # the cross-breach narrative rides on every row, so a single row is self-contained
    assert all("cascading into HDFS" in r["overall_summary"] for r in rows)
    # each row keeps its own measured detail next to the model's explanation
    assert rows[0]["breach_detail"] == "/u01 at 99%"
    assert rows[1]["breach_detail"] == "CONCERNING"


def test_multiline_model_output_stays_on_one_line(history):
    """One row == one line, so the file greps cleanly and pastes into an LLM well."""
    breach_history.record_kpi(
        _kpi(summary="Line one.\nLine two.\n\n  Line three.  "),
        cluster="c1", version="7.1.7", breach_detail="detail\nwith a newline",
    )

    lines = [ln for ln in history.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 2   # header + exactly one data line
    row = _rows(history)[0]
    assert row["summary"] == "Line one. Line two. Line three."
    assert row["breach_detail"] == "detail with a newline"


def test_a_broken_history_file_never_breaks_the_analysis(history, monkeypatch):
    """The whole point of the try/except: recording is best-effort, always."""
    def explode(*_a, **_kw):
        raise OSError("disk full / file locked by Excel / permissions")

    monkeypatch.setattr(breach_history, "_append", explode)

    # Neither call may raise — an unwritable corpus is not an analysis failure.
    breach_history.record_kpi(_kpi(), cluster="c1", version="7.1.7", breach_detail="x")
    breach_history.record_incident(
        IncidentReport(overall_summary="s", findings=[AiFinding(primary_task="cpu_percent")]),
        cluster="c1", version="7.1.7",
    )


def test_analyze_kpi_records_to_history(monkeypatch):
    """The hook is actually wired into analyze_kpi — not merely importable.

    No DB needed: everything analyze_kpi does with `db`/`user` is hand off to
    agent_runner, which is faked here.
    """
    from types import SimpleNamespace

    from backend.app.ai import analyzer

    captured = {}
    monkeypatch.setattr(
        analyzer.breach_history, "record_kpi",
        lambda analysis, **kw: captured.update(analysis=analysis, **kw),
    )

    class FakeResult:
        status = "BREACH"
        detail = "/u01 at 96.9%"
        def model_dump(self, **_kw):
            return {"task": "disk_percent", "status": "BREACH", "detail": self.detail}

    outcome = SimpleNamespace(
        model_id="fake", attempts=[],
        data={"summary": "s", "severity": "HIGH", "remediation": ["do a thing"], "impact": "i"},
    )
    monkeypatch.setattr(analyzer.bridge, "build_single_check", lambda *a, **kw: FakeResult())
    monkeypatch.setattr(analyzer.agent_runner, "run_kpi_with_fallback", lambda *a, **kw: outcome)
    monkeypatch.setattr(analyzer, "_disk_trend_text", lambda *a, **kw: "")

    tenant = SimpleNamespace(cluster_name="bdaktprod-cluster", cloudera_version="7.1.9")
    out = analyzer.analyze_kpi(db=None, user=None, db_tenant=tenant, task="disk_percent")

    assert captured["analysis"] is out
    assert captured["breach_detail"] == "/u01 at 96.9%"
    assert captured["cluster"] == "bdaktprod-cluster"
