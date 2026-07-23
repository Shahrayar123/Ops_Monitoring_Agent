"""One specialized Agent per KPI check, plus one coordinator Agent for the
all-breaches incident view.

Each agent gets:
  - task-specific instructions (what this check means, what "wrong" looks like)
  - the shared governance rules (version-aware, ground remediation in tools,
    never fabricate timelines) common to every agent
  - investigation tools (agent_tools.py) it decides when to call
  - a structured output_type (models.py) the SDK enforces

The model itself is NOT fixed here — agent_runner.py builds a fresh Agent per
attempt, swapping in whichever model from the user's fallback chain is being
tried, so the same agent definition runs on Ollama, GPT-4o, Gemini, or Grok.
"""

from agents import Agent, ModelSettings

from . import agent_tools
from .models import IncidentAgentOutput, KpiAgentOutput

_GOVERNANCE = """You never decide what counts as a problem and never invent metrics, hosts,
or thresholds — a deterministic check already found this breach; you explain it,
connect it to related issues, and recommend fixes.

Use your tools to ground every claim: call search_knowledge before writing
remediation, call get_dependency_impact before claiming cross-metric effects,
and call get_disk_trend only for time estimates (never fabricate a timeline).
Prefer knowledge that gives a "Resolution (agent action)" — lead with it.

The only valid check names for related_tasks are: host_health, heartbeat,
cpu_percent, ram_percent, disk_percent, hdfs_health, service_status, alerts,
network. Never put remediation steps or free text in related_tasks.

CLUSTER VERSION: tailor every step to the stated Cloudera version — service
names, Cloudera Manager API paths, and config locations differ across
CDP/CDH releases. Never recommend a step that doesn't apply to that version.

Severity: read the detail carefully, especially counts. Many CRITICAL alerts, a
BAD health summary, or missing HDFS blocks are HIGH or CRITICAL — never LOW."""

# Task-specific framing — what this particular check means and what to focus on.
_TASK_BRIEF = {
    "host_health": "You analyze Cloudera Manager HOST HEALTH breaches — a host's overall healthSummary is CONCERNING or BAD (agent down, clock drift, resource pressure, or a failed health test).",
    "heartbeat": "You analyze HEARTBEAT breaches — a host hasn't reported to Cloudera Manager within its configured window, meaning it's likely down, network-partitioned, or its agent has stopped.",
    "cpu_percent": "You analyze CPU UTILIZATION breaches — sustained high CPU on a host or role, usually a runaway job/container or genuine capacity pressure.",
    "ram_percent": "You analyze MEMORY UTILIZATION breaches — high or leaking memory usage on a role process, risking OOM kills and node instability.",
    "disk_percent": "You analyze DISK & LOG breaches — a watched mount or log directory is over its fullness threshold. Distinguish HDFS data-disk pressure (capacity problem) from log/tmp growth (housekeeping problem) — they need different fixes.",
    "hdfs_health": "You analyze HDFS CAPACITY & HEALTH breaches — NameNode/DataNode issues, under-replicated or missing blocks, or storage pressure that threatens HDFS availability.",
    "service_status": "You analyze SERVICE & ROLE STATUS breaches — a service or role instance is Stopped or reporting BAD/CONCERNING health, which can cascade to dependent services.",
    "alerts": "You analyze CLUSTER ALERTS breaches — active Cloudera Manager alerts/health-check failures. Weight severity heavily by the count of CRITICAL vs IMPORTANT alerts.",
    "network": "You analyze NETWORK & CONNECTIVITY breaches — unreachable hosts, elevated network error rates, or connectivity failures between cluster nodes.",
}

_KPI_INSTRUCTIONS_TEMPLATE = """You are the {label} Analyst for a Cloudera Hadoop cluster monitoring product.

{brief}

{governance}

You will be given the breach's status, detail, and threshold in the user message.
Use your tools, then produce your final structured analysis."""

_INCIDENT_INSTRUCTIONS = f"""You are the Incident Coordinator for a Cloudera Hadoop cluster monitoring product,
synthesizing ALL currently-breaching checks into one incident report.

{_GOVERNANCE}

You will be given the list of breaching checks in the user message. Call
get_check_detail for each one you need more evidence on, and search_knowledge
for remediation guidance, before writing findings. Connect related problems —
a single root cause often explains several breaches — rank each finding by
severity, and note cross-metric impact using get_check_detail's dependency info."""

# Human labels for the per-KPI agent's own instructions (kept separate from
# frontend CHECK_META so this package has no frontend coupling).
_TASK_LABEL = {
    "host_health": "Host Health",
    "heartbeat": "Heartbeat",
    "cpu_percent": "CPU Utilization",
    "ram_percent": "Memory Utilization",
    "disk_percent": "Disk & Logs",
    "hdfs_health": "HDFS Capacity & Health",
    "service_status": "Service & Role Status",
    "alerts": "Cluster Alerts",
    "network": "Network & Connectivity",
}


def build_kpi_agent(task: str, model, result: dict, trend_text: str) -> Agent:
    """A fresh agent for one breaching check, bound to that breach's tools and
    wired to `model` (an agents-SDK Model, chosen per fallback attempt)."""
    label = _TASK_LABEL.get(task, task)
    brief = _TASK_BRIEF.get(task, f"You analyze breaches of the '{task}' check.")
    instructions = _KPI_INSTRUCTIONS_TEMPLATE.format(label=label, brief=brief, governance=_GOVERNANCE)
    return Agent(
        name=f"{label} Analyst",
        instructions=instructions,
        model=model,
        tools=agent_tools.kpi_tools(task, result, trend_text),
        output_type=KpiAgentOutput,
        # Force at least one tool call before the model can finalize — grounding
        # is a governance requirement, not optional, and smaller local models
        # will happily skip straight to an ungrounded answer if given the choice.
        # reset_tool_choice (default True) drops back to "auto" after the first
        # forced call so the model can still choose to stop once it has enough.
        model_settings=ModelSettings(temperature=0.2, max_tokens=900, tool_choice="required"),
    )


def build_incident_agent(model, breached: list[dict], trend_text: str) -> Agent:
    """A fresh coordinator agent for the all-breaches view, wired to `model`."""
    return Agent(
        name="Incident Coordinator",
        instructions=_INCIDENT_INSTRUCTIONS,
        model=model,
        tools=agent_tools.incident_tools(breached, trend_text),
        output_type=IncidentAgentOutput,
        model_settings=ModelSettings(temperature=0.2, max_tokens=1600, tool_choice="required"),
    )
