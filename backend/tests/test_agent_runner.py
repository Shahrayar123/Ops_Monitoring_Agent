"""The agentic KPI/incident analysis path: agent_runner.py's fallback chain,
kpi_agents.py's per-task agent construction, and agent_tools.py's wiring.

Runner.run is mocked (a real run needs a live model) — these tests verify the
plumbing around it: model selection, fallback-on-error, metering, and the
Anthropic direct-call exception path. A genuine end-to-end run against a real
Ollama model is exercised separately, outside the unit suite.
"""

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from backend.app.ai import agent_runner, agent_tools, kpi_agents
from backend.app.ai.models import IncidentAgentOutput, KpiAgentOutput
from backend.app.db.models import ApiUsage, User
from backend.app.llm.providers import LLMError
from .conftest import ADMIN_EMAIL


@dataclass
class _FakeUsage:
    input_tokens: int = 10
    output_tokens: int = 20
    total_tokens: int = 30


@dataclass
class _FakeContextWrapper:
    usage: _FakeUsage


@dataclass
class _FakeRunResult:
    final_output: object
    context_wrapper: _FakeContextWrapper


def _fake_run_result(output):
    return _FakeRunResult(final_output=output, context_wrapper=_FakeContextWrapper(_FakeUsage()))


# ---------- agent construction / tool wiring ----------


def test_build_kpi_agent_has_task_specific_instructions_and_tools():
    result = {"task": "disk_percent", "status": "BREACH", "detail": "/var/log at 95%"}
    agent = kpi_agents.build_kpi_agent("disk_percent", model=None, result=result, trend_text="(none)")
    assert "Disk & Logs" in agent.name
    assert "DISK & LOG" in agent.instructions
    assert agent.output_type is KpiAgentOutput
    tool_names = {t.name for t in agent.tools}
    assert tool_names == {"search_knowledge", "get_dependency_impact", "get_evidence_detail", "get_disk_trend"}


def test_every_check_task_has_a_distinct_agent_brief():
    tasks = ["host_health", "heartbeat", "cpu_percent", "ram_percent", "disk_percent",
              "hdfs_health", "service_status", "alerts", "network"]
    briefs = set()
    for task in tasks:
        agent = kpi_agents.build_kpi_agent(task, model=None, result={"task": task}, trend_text="")
        briefs.add(agent.instructions)
    assert len(briefs) == len(tasks)  # no two tasks share the exact same instructions


def test_build_incident_agent_has_coordinator_tools():
    breached = [{"task": "disk_percent", "detail": "full"}, {"task": "hdfs_health", "detail": "concerning"}]
    agent = kpi_agents.build_incident_agent(model=None, breached=breached, trend_text="(none)")
    assert agent.name == "Incident Coordinator"
    assert agent.output_type is IncidentAgentOutput
    tool_names = {t.name for t in agent.tools}
    assert tool_names == {"get_check_detail", "search_knowledge", "get_disk_trend"}


def test_kpi_tools_and_incident_tools_are_real_function_tools():
    from agents import FunctionTool
    for t in agent_tools.kpi_tools("cpu_percent", {"task": "cpu_percent"}, ""):
        assert isinstance(t, FunctionTool)
    for t in agent_tools.incident_tools([{"task": "cpu_percent"}], ""):
        assert isinstance(t, FunctionTool)


# ---------- fallback chain: KPI ----------


def _admin_in(session):
    return session.query(User).filter(User.email == ADMIN_EMAIL).first()


def test_kpi_agentic_run_meters_usage_and_returns_normalized_data(db_session, monkeypatch):
    called = {}

    async def fake_run(agent, input_text, max_turns=None):
        called["agent_name"] = agent.name
        called["input"] = input_text
        return _fake_run_result(KpiAgentOutput(
            summary="disk is full", severity="HIGH", remediation=["clear /tmp"],
            impact="may affect hdfs_health", related_tasks=["hdfs_health"], sources=["cloudera_best_practices.md"],
        ))

    monkeypatch.setattr(agent_runner.Runner, "run", fake_run)
    session = db_session()
    try:
        user = _admin_in(session)
        outcome = agent_runner.run_kpi_with_fallback(
            session, user, task="disk_percent",
            result={"task": "disk_percent", "status": "BREACH", "detail": "/var/log at 95%"},
            trend_text="(none)", cluster="bdaktprod-cluster", version="7.1.9",
        )
        user_id = user.id
    finally:
        session.close()

    assert outcome.agentic is True
    assert outcome.data["severity"] == "HIGH"
    assert outcome.data["remediation"] == ["clear /tmp"]
    assert "Disk & Logs Analyst" == called["agent_name"]
    assert "CLUSTER: bdaktprod-cluster" in called["input"]
    assert "Cloudera version 7.1.9" in called["input"]

    # usage was actually recorded (metering happens regardless of agentic/direct path)
    session2 = db_session()
    rows = session2.query(ApiUsage).filter(ApiUsage.user_id == user_id).all()
    session2.close()
    assert any(r.total_tokens == 30 and r.success for r in rows)


def test_kpi_run_falls_back_to_next_model_on_agent_failure(db_session, monkeypatch):
    calls = []

    async def failing_run(agent, input_text, max_turns=None):
        calls.append(1)
        raise RuntimeError("tool blew up")

    monkeypatch.setattr(agent_runner.Runner, "run", failing_run)

    # give the user a two-model chain so there's a second attempt to fall through to
    session = db_session()
    user = _admin_in(session)
    user.model_priority = ["qwen2.5:7b", "gpt-4o-mini"]
    session.commit()
    session.close()

    session = db_session()
    try:
        user = _admin_in(session)
        with pytest.raises(LLMError, match="All models failed"):
            agent_runner.run_kpi_with_fallback(
                session, user, task="cpu_percent",
                result={"task": "cpu_percent", "status": "BREACH", "detail": "high cpu"},
                trend_text="(none)", cluster="c", version="7.1.9",
            )
    finally:
        session.close()
    # gpt-4o-mini has no API key configured -> it never reaches Runner.run, only qwen does
    assert len(calls) == 1


def test_kpi_anthropic_model_uses_direct_call_not_the_agent(db_session, monkeypatch):
    """Anthropic can't run through the Agents SDK in this environment (see
    agent_runner.py's module docstring) — verify it takes the direct-call
    fallback branch instead of ever touching Runner.run."""
    from backend.app.ai import agent_runner as ar

    def fake_direct_chat(spec, messages, *, api_key=None, system=None, max_tokens=900, timeout=60.0, **kw):
        return SimpleNamespace(
            text='{"summary": "s", "severity": "CRITICAL", "remediation": ["r1"], "impact": "i", "related_tasks": [], "sources": []}',
            prompt_tokens=5, completion_tokens=5, total_tokens=10, latency_ms=1,
        )

    async def run_should_not_be_called(*a, **kw):
        raise AssertionError("Runner.run should not be called for an Anthropic model")

    monkeypatch.setattr(ar, "direct_chat", fake_direct_chat)
    monkeypatch.setattr(ar.Runner, "run", run_should_not_be_called)

    session = db_session()
    user = _admin_in(session)
    user.allowed_models = ["claude-sonnet-5"]  # per-user override so it survives effective_priority's allow-list filter
    user.model_priority = ["claude-sonnet-5"]
    session.commit()
    user_id = user.id
    session.close()

    # give this user an anthropic key so the attempt isn't skipped for lacking one
    from backend.app.llm import settings as llm_settings
    session = db_session()
    llm_settings.set_api_key(session, user_id, "anthropic", "sk-fake-key-1234567890")
    session.commit()
    session.close()

    session = db_session()
    try:
        user = _admin_in(session)
        outcome = agent_runner.run_kpi_with_fallback(
            session, user, task="alerts",
            result={"task": "alerts", "status": "BREACH", "detail": "10 critical active alerts"},
            trend_text="(none)", cluster="c", version="7.1.9",
        )
    finally:
        session.close()

    assert outcome.agentic is False
    assert outcome.data["severity"] == "CRITICAL"
    assert outcome.model_id == "claude-sonnet-5"


# ---------- fallback chain: incident ----------


def test_incident_agentic_run_returns_findings(db_session, monkeypatch):
    async def fake_run(agent, input_text, max_turns=None):
        assert agent.name == "Incident Coordinator"
        return _fake_run_result(IncidentAgentOutput(
            overall_summary="multiple issues",
            findings=[{"primary_task": "disk_percent", "severity": "HIGH", "summary": "full disk", "remediation": ["clean up"], "related_tasks": []}],
            priority_order=["disk_percent"],
        ))

    monkeypatch.setattr(agent_runner.Runner, "run", fake_run)
    session = db_session()
    try:
        user = _admin_in(session)
        outcome = agent_runner.run_incident_with_fallback(
            session, user, breached=[{"task": "disk_percent", "status": "BREACH", "detail": "full"}],
            trend_text="(none)", cluster="c", version="7.1.9",
        )
    finally:
        session.close()

    assert outcome.data["overall_summary"] == "multiple issues"
    assert outcome.data["findings"][0]["primary_task"] == "disk_percent"
