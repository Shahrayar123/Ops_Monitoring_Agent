"""Tests for the per-check evidence (the dashboard's "what was checked" panel).

Every evaluated check should attach a CheckEvidence: where the data came from,
which keys were read, and one row per reading with a green/red (breached) flag.
The rows must agree with the check's own verdict — a BREACH has at least one
red row, an OK check has none.
"""

from datetime import datetime, timezone

from checks import CheckEvidence, run_all_checks
from checks.run_all_checks import ALL_CHECKS

FIXED_NOW = datetime(2026, 7, 1, 17, 40, 30, tzinfo=timezone.utc)


def test_every_evaluated_check_attaches_evidence(source, tenant):
    report = run_all_checks(source, tenant, now=FIXED_NOW)
    for r in report.results:
        if r.status == "NO_DATA":
            continue
        assert isinstance(r.evidence, CheckEvidence), f"{r.task} has no evidence"
        assert r.evidence.source, f"{r.task} evidence has no source/provenance"
        assert r.evidence.keys_checked, f"{r.task} evidence lists no keys checked"


def test_evidence_rows_agree_with_the_verdict(source, tenant):
    report = run_all_checks(source, tenant, now=FIXED_NOW)
    for r in report.results:
        if r.status == "NO_DATA" or not r.evidence:
            continue
        any_red = any(row.breached for row in r.evidence.rows)
        if r.status == "BREACH":
            assert any_red, f"{r.task} is a BREACH but no evidence row is flagged"
        else:  # OK
            assert not any_red, f"{r.task} is OK but an evidence row is flagged breached"


def test_provenance_names_the_source_file_for_the_json_source(source, tenant):
    # The offline sample tenant reads JSON files — provenance should name one.
    report = run_all_checks(source, tenant, now=FIXED_NOW)
    cpu = next(r for r in report.results if r.task == "cpu_percent")
    assert cpu.evidence.source.endswith(".json")
    assert "cpu_percent" in cpu.evidence.keys_checked


def test_evidence_survives_json_round_trip(source, tenant):
    # The API serializes the report to JSON and the dashboard validates it back;
    # the nested evidence must round-trip intact.
    from checks import HealthReport

    report = run_all_checks(source, tenant, now=FIXED_NOW)
    restored = HealthReport.model_validate(report.model_dump(mode="json"))
    original = next(r for r in report.results if r.task == "host_health")
    round_tripped = next(r for r in restored.results if r.task == "host_health")
    assert round_tripped.evidence == original.evidence


def test_all_checks_are_covered():
    # Guard: if a tenth check is added, this suite should be revisited.
    assert len(ALL_CHECKS) == 9
