"""Tests for the AI analyst.

The second test talks to a real local Ollama model and takes several minutes on
CPU; it is skipped automatically when Ollama isn't running.
"""

import asyncio
from datetime import datetime, timezone

import httpx
import pytest

from ai_analysis import AiReport, run_ai_analysis
from checks import run_all_checks
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
