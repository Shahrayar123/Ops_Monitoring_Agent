"""The AI analyst — the only place in the product that uses an LLM.

The checks in checks/ decide WHAT is wrong (deterministic Python, thresholds).
The AI's job is to make sense of it: connect related problems ("the full disk
on node2 also explains the HDFS alert"), rank them by severity, write a short
incident summary a human can act on, and suggest fixes.

Rules the design enforces:
- The AI runs ONLY when the health report contains breaches. On a healthy
  cluster no LLM call is ever made (run_ai_analysis raises if you try).
- The AI never decides what counts as a problem — it receives the finished
  breach list and reasons about it.
- It can re-run any of the nine checks as a tool if it wants fresh data while
  reasoning (e.g. "is that host's disk also full?"). Same functions the
  monitoring loop runs — the logic is never duplicated.

The model is served by Ollama (or any OpenAI-compatible endpoint); which model
and where come from .env (see config/llm_config.py).
"""

import json
import logging
import time
from typing import Literal

from agents import Agent, OpenAIChatCompletionsModel, Runner, function_tool

log = logging.getLogger(__name__)
from openai import AsyncOpenAI
from pydantic import BaseModel

from checks import (
    HealthReport,
    check_alerts,
    check_cpu_percent,
    check_disk_percent,
    check_hdfs_health,
    check_heartbeat,
    check_host_health,
    check_network,
    check_ram_percent,
    check_service_status,
)
from config import LLMConfig, TenantConfig
from data_sources import DataSource

INSTRUCTIONS = """You are the operations analyst for a Cloudera cluster monitoring product.

You receive a list of problems already detected by deterministic threshold checks —
you never decide what counts as a problem, and you never invent metrics or thresholds.
Your job is purely to make sense of what was found:

1. Connect related problems across areas (e.g. a full disk on a host that also
   explains a storage alert; a silent heartbeat that explains an unhealthy service).
2. Rank each finding by severity.
3. Write a short, human-readable incident summary.
4. Recommend concrete remediation steps for each finding.

You have tools to re-run any check for fresh data if it helps you connect issues.
Only call a tool when it would change your analysis — don't call tools speculatively.
"""


class AiFinding(BaseModel):
    """One issue (or group of connected issues) in the AI's report."""

    primary_task: str
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    summary: str
    related_tasks: list[str]
    recommended_remediation: str


class AiReport(BaseModel):
    """The AI's full analysis of one health report."""

    overall_summary: str
    findings: list[AiFinding]
    priority_order: list[str]


def _check_tools(source: DataSource, tenant: TenantConfig) -> list:
    """Wrap each check as a no-argument tool bound to this cluster's data, so
    the AI can pull fresh readings while it reasons."""

    @function_tool
    def get_host_health() -> str:
        """Re-run the host health check (health verdict per machine)."""
        return check_host_health(source, tenant).model_dump_json()

    @function_tool
    def get_heartbeat() -> str:
        """Re-run the heartbeat check (time since each machine last reported)."""
        return check_heartbeat(source, tenant).model_dump_json()

    @function_tool
    def get_cpu_percent() -> str:
        """Re-run the CPU usage check per machine."""
        return check_cpu_percent(source, tenant).model_dump_json()

    @function_tool
    def get_ram_percent() -> str:
        """Re-run the memory usage check per machine."""
        return check_ram_percent(source, tenant).model_dump_json()

    @function_tool
    def get_disk_percent() -> str:
        """Re-run the disk fullness / log size check per machine and mount."""
        return check_disk_percent(source, tenant).model_dump_json()

    @function_tool
    def get_hdfs_health() -> str:
        """Re-run the HDFS health and storage-growth check."""
        return check_hdfs_health(source, tenant).model_dump_json()

    @function_tool
    def get_service_status() -> str:
        """Re-run the service and role status check for every service."""
        return check_service_status(source, tenant).model_dump_json()

    @function_tool
    def get_alerts() -> str:
        """Re-run the cluster alerts check."""
        return check_alerts(source, tenant).model_dump_json()

    @function_tool
    def get_network() -> str:
        """Re-run the network errors and reachability check."""
        return check_network(source, tenant).model_dump_json()

    return [
        get_host_health,
        get_heartbeat,
        get_cpu_percent,
        get_ram_percent,
        get_disk_percent,
        get_hdfs_health,
        get_service_status,
        get_alerts,
        get_network,
    ]


def build_analyst(source: DataSource, tenant: TenantConfig, llm: LLMConfig) -> Agent:
    client = AsyncOpenAI(base_url=llm.base_url, api_key=llm.api_key)
    model = OpenAIChatCompletionsModel(model=llm.model, openai_client=client)

    return Agent(
        name="Cloudera Ops Analyst",
        instructions=INSTRUCTIONS,
        model=model,
        tools=_check_tools(source, tenant),
        output_type=AiReport,
    )


async def run_ai_analysis(
    report: HealthReport,
    source: DataSource,
    tenant: TenantConfig,
    llm: LLMConfig,
) -> AiReport:
    if not report.has_breaches:
        raise ValueError(
            "run_ai_analysis was called on a healthy report — the AI must only run "
            "when there are breaches (on a healthy cluster no LLM call is made)."
        )

    analyst = build_analyst(source, tenant, llm)

    problems_json = json.dumps(
        [r.model_dump(mode="json") for r in report.breached_results], indent=2
    )
    prompt = (
        f"Tenant: {tenant.display_name} (cluster: {tenant.cluster_name})\n"
        f"Checked at: {report.timestamp.isoformat()}\n\n"
        f"The monitoring run detected {report.breach_count} problem(s):\n\n"
        f"{problems_json}\n\n"
        "Connect related problems, rank severity, write the incident summary, "
        "and recommend remediation."
    )

    log.info(
        "AI analysis started for tenant '%s' (%d breached checks, model %s)",
        tenant.tenant_id, report.breach_count, llm.model,
    )
    started = time.monotonic()
    try:
        result = await Runner.run(analyst, input=prompt)
    except Exception:
        log.exception(
            "AI analysis FAILED for tenant '%s' after %.0fs",
            tenant.tenant_id, time.monotonic() - started,
        )
        raise

    ai_report = result.final_output_as(AiReport)
    log.info(
        "AI analysis finished for tenant '%s' in %.0fs: %d findings (%s); priority: %s",
        tenant.tenant_id,
        time.monotonic() - started,
        len(ai_report.findings),
        ", ".join(f"{f.primary_task}={f.severity}" for f in ai_report.findings) or "-",
        " > ".join(ai_report.priority_order) or "-",
    )
    return ai_report
