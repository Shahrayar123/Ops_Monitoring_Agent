"""Investigation tools given to the per-KPI and incident agents.

Each tool is a thin, read-only wrapper around code that already exists
(knowledge retrieval, the dependency graph, disk-trend extrapolation) — the
agent decides WHEN to call them and with what query; it never gets to change
anything or invent data outside what these return.

Tools are built per-request via closures bound to the current tenant/report
snapshot, so the same tool names work for both the single-KPI agent (bound to
one breach) and the incident agent (bound to every breaching check).
"""

from agents import function_tool

from . import knowledge
from .prompts import dependency_block, evidence_digest


def _make_search_knowledge(default_task: str):
    @function_tool(
        name_override="search_knowledge",
        description_override=(
            "Search the Ops knowledge base (runbook, actionable known-issues table, "
            "and Cloudera best-practices guide) for remediation guidance. Call this "
            "with a specific query describing the symptom before writing your final "
            "remediation steps — do not rely on general knowledge alone."
        ),
    )
    def search_knowledge(query: str) -> str:
        snippets = knowledge.search(default_task, query, limit=3)
        return knowledge.format_for_prompt(snippets)

    return search_knowledge


def _make_get_dependency_impact(task: str):
    @function_tool(
        name_override="get_dependency_impact",
        description_override=(
            "Get the declared downstream effects if this check keeps breaching — "
            "which OTHER checks may be affected, and why. Use this before claiming "
            "cross-metric impact."
        ),
    )
    def get_dependency_impact() -> str:
        return dependency_block(task)

    return get_dependency_impact


def _make_get_evidence(result: dict):
    @function_tool(
        name_override="get_evidence_detail",
        description_override=(
            "Get the full per-reading evidence behind this breach (which hosts/entities "
            "breached, their values, and the data source) if the summary detail isn't enough."
        ),
    )
    def get_evidence_detail() -> str:
        return evidence_digest(result, max_rows=25)

    return get_evidence_detail


def _make_get_disk_trend(trend_text: str):
    @function_tool(
        name_override="get_disk_trend",
        description_override=(
            "Get the computed disk fill-rate projection (hours-to-full), if one applies. "
            "Only use this for time estimates — never invent a timeline yourself."
        ),
    )
    def get_disk_trend() -> str:
        return trend_text

    return get_disk_trend


def kpi_tools(task: str, result: dict, trend_text: str) -> list:
    """Tools for a single-KPI agent, bound to its one breach."""
    return [
        _make_search_knowledge(task),
        _make_get_dependency_impact(task),
        _make_get_evidence(result),
        _make_get_disk_trend(trend_text),
    ]


def incident_tools(breached: list[dict], trend_text: str) -> list:
    """Tools for the incident (all-breaches) coordinator agent — it can pull
    detail on any of the breaching checks it's told about, not just one."""
    by_task = {r["task"]: r for r in breached}

    @function_tool(
        name_override="get_check_detail",
        description_override=(
            "Get the evidence and dependency impact for one of the currently-breaching "
            "checks by its task name (e.g. 'disk_percent'). Use this to look closer at "
            "any of the breaches listed in your instructions before writing findings."
        ),
    )
    def get_check_detail(task: str) -> str:
        r = by_task.get(task)
        if r is None:
            return f"'{task}' is not one of the currently-breaching checks."
        return (
            f"Detail: {r.get('detail')}\n"
            f"Evidence:\n{evidence_digest(r, max_rows=15)}\n"
            f"Dependencies:\n{dependency_block(task)}"
        )

    @function_tool(
        name_override="search_knowledge",
        description_override=(
            "Search the Ops knowledge base for remediation guidance on a specific "
            "check and symptom, e.g. task='disk_percent', query='/var/log full'."
        ),
    )
    def search_knowledge(task: str, query: str = "") -> str:
        snippets = knowledge.search(task, query, limit=3)
        return knowledge.format_for_prompt(snippets)

    return [get_check_detail, search_knowledge, _make_get_disk_trend(trend_text)]
