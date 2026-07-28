"""The AI analysis output shapes + the deterministic severity floor.

Two result shapes:
  - KpiAnalysis   : one breaching KPI (the per-card "AI Analyzer" page)
  - IncidentReport: all breaches together (the dashboard-bottom section)

The severity floor is the governance guardrail (slide 8): a minimum severity
computed straight from the check's own data, so the model can never under-rate a
finding the numbers clearly show is serious. The model can rank higher; it can't
go below the floor.
"""

import json
import re
from typing import Literal, Optional

from pydantic import BaseModel, Field

Severity = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
_ORDER = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]


class AiFinding(BaseModel):
    primary_task: str
    severity: Severity = "MEDIUM"
    summary: str = ""
    remediation: list[str] = Field(default_factory=list)
    related_tasks: list[str] = Field(default_factory=list)


class KpiAnalysis(BaseModel):
    task: str
    severity: Severity = "MEDIUM"
    summary: str = ""
    remediation: list[str] = Field(default_factory=list)
    impact: str = ""                       # cross-metric effects, in prose
    related_tasks: list[str] = Field(default_factory=list)
    trend_note: str = ""                   # computed projection, if any
    sources: list[str] = Field(default_factory=list)   # knowledge files cited
    model_used: str = ""
    attempts: list[dict] = Field(default_factory=list)


class IncidentReport(BaseModel):
    overall_summary: str = ""
    findings: list[AiFinding] = Field(default_factory=list)
    priority_order: list[str] = Field(default_factory=list)
    model_used: str = ""
    attempts: list[dict] = Field(default_factory=list)


# ---------- agent output schemas (agents SDK `output_type`) ----------
#
# The Agents SDK enforces these shapes at the model layer (structured output),
# so — unlike the direct-call path — there's no free-text JSON to parse or
# tolerate here. analyzer.py maps these onto KpiAnalysis/IncidentReport above,
# same as it does for the direct-call path, so nothing downstream cares which
# path produced the result.


class KpiAgentOutput(BaseModel):
    summary: str = Field(description="2-3 sentences: what is wrong and why it matters")
    severity: Severity = "MEDIUM"
    remediation: list[str] = Field(default_factory=list, description="Ordered, concrete steps grounded in tool results")
    impact: str = Field(default="", description="Expected effect on OTHER checks, from dependency + trend context")
    related_tasks: list[str] = Field(
        default_factory=list,
        description="ONLY monitoring check names likely affected, e.g. 'hdfs_health', 'service_status' — "
        "never remediation steps or free text",
    )
    sources: list[str] = Field(default_factory=list, description="Knowledge file names the remediation was drawn from")


class IncidentAgentFinding(BaseModel):
    primary_task: str
    severity: Severity = "MEDIUM"
    summary: str = ""
    remediation: list[str] = Field(default_factory=list)
    related_tasks: list[str] = Field(default_factory=list)


class IncidentAgentOutput(BaseModel):
    overall_summary: str = Field(description="3-4 sentences across all findings, calling out the likely root cause")
    findings: list[IncidentAgentFinding] = Field(default_factory=list)
    priority_order: list[str] = Field(default_factory=list, description="Check names, most urgent first")


# ---------- deterministic severity floor ----------


def severity_floor(task: str, detail: str) -> Optional[str]:
    """The minimum severity implied by a check's own data. None = no floor."""
    if task == "alerts":
        m = re.search(r"(\d+)\s+critical", detail, re.IGNORECASE)
        critical = int(m.group(1)) if m else 0
        if critical >= 10:
            return "CRITICAL"
        if critical >= 1:
            return "HIGH"
        if "important" in detail.lower():
            return "MEDIUM"
        return None
    if "healthSummary=BAD" in detail or "=BAD" in detail:
        return "CRITICAL"
    if task == "hdfs_health" and "CONCERNING" in detail:
        return "HIGH"
    if task in ("host_health", "service_status") and "CONCERNING" in detail:
        return "MEDIUM"
    if task == "network" and "unreachable" in detail.lower():
        return "HIGH"
    return None


def apply_floor(severity: str, task: str, detail: str) -> str:
    floor = severity_floor(task, detail)
    if severity not in _ORDER:
        severity = "MEDIUM"
    if floor and _ORDER.index(floor) > _ORDER.index(severity):
        return floor
    return severity


def order_findings(findings: list[AiFinding]) -> list[AiFinding]:
    """Most-urgent first: severity desc, then original order (stable)."""
    return sorted(
        findings,
        key=lambda f: -_ORDER.index(f.severity if f.severity in _ORDER else "MEDIUM"),
    )


# ---------- lenient JSON extraction from model output ----------


def extract_json(text: str) -> Optional[dict]:
    """Pull the first JSON object out of a model's reply, tolerating code fences
    and surrounding prose. Returns None if nothing parseable is found."""
    if not text:
        return None
    # strip ```json ... ``` fences
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        # first balanced-looking {...} block
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            candidate = text[start : end + 1]
    if candidate is None:
        return None
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None


def coerce_str_list(value) -> list[str]:
    """Model remediation may come back as a list, a string, or newline text.
    Splits on newlines and strips any leading list marker (1. / 2) / - / •)."""
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        out = []
        for line in re.split(r"\n+", value):
            cleaned = re.sub(r"^\s*(?:\d+[.)]|[-*•])\s*", "", line).strip()
            if cleaned:
                out.append(cleaned)
        return out
    return []
