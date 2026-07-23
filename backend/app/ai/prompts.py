"""Build the analysis prompts.

Everything the model reasons over is assembled here — the breach data, the
cluster's Cloudera version, the declared dependency edges, retrieved knowledge
snippets, and computed disk trends. The remediation knowledge is INJECTED as
retrieved context (from knowledge/), never baked into these strings, so Ops can
change guidance by editing files, not code.

Two callers:
  - agent_runner.py's Anthropic path: Claude isn't run through the Agents SDK in
    this environment (see agent_runner.py's module docstring for why), so it
    still gets one fully-assembled prompt via build_kpi_prompt/build_incident_prompt.
  - agent_tools.py: reuses evidence_digest()/dependency_block() as the building
    blocks behind the agentic tools' outputs, so both paths report identically.
"""

from . import dependencies, knowledge
from .knowledge import Snippet

SYSTEM = """You are the operations analyst for a Cloudera Hadoop cluster monitoring product.

You receive problems already detected by deterministic threshold checks. You never
decide what counts as a problem and never invent metrics, hosts, or thresholds —
you explain what was found, connect related issues, and recommend fixes.

Ground every remediation in the provided KNOWLEDGE context (the Ops team's runbook,
the actionable known-issues table, and the Cloudera best-practices guide). Prefer
that guidance over your own general knowledge. When a KNOWLEDGE entry gives a
"Resolution (agent action)", lead your remediation with that concrete action.

CLUSTER VERSION: the cluster's Cloudera version is stated in the CLUSTER line of
each request. Tailor every step to THAT version — service names, Cloudera Manager
API paths, and config locations differ across CDP/CDH releases. Never recommend a
step that does not apply to the stated version.

Severity: read the detail carefully, especially counts. Many CRITICAL alerts, a
BAD health summary, or missing HDFS blocks are HIGH or CRITICAL — never LOW. Do not
soften severity because other findings look worse; judge each on its own evidence.

For cross-metric impact, use ONLY the provided DEPENDENCY context and computed
TRENDS. State expected knock-on effects qualitatively; give a concrete time
estimate only where a TREND provides one. Do not fabricate timelines.

Reply with ONLY a JSON object — no prose outside it."""


def evidence_digest(result: dict, max_rows: int = 12) -> str:
    """A compact view of a check's evidence: counts + the breaching readings."""
    ev = result.get("evidence") or {}
    rows = ev.get("rows") or []
    breached = [r for r in rows if r.get("breached")]
    lines = [f"total readings: {len(rows)}, over limit: {len(breached)}"]
    for r in breached[:max_rows]:
        lines.append(f"  - {r.get('entity')}: {r.get('value')}")
    if len(breached) > max_rows:
        lines.append(f"  … and {len(breached) - max_rows} more")
    if ev.get("source"):
        lines.append(f"data source: {ev['source']}")
    return "\n".join(lines)


def dependency_block(task: str) -> str:
    edges = dependencies.downstream_of(task)
    if not edges:
        return "(No downstream dependencies declared for this check.)"
    return "\n".join(f"- may affect {e.affects}: {e.why}; expect {e.expect}" for e in edges)


def build_kpi_prompt(
    *, cluster: str, version: str, result: dict, trend_text: str
) -> tuple[str, str, list[Snippet]]:
    """Prompt for a single breaching KPI. Returns (system, user, snippets_used)."""
    task = result["task"]
    snippets = knowledge.search(task, result.get("detail", ""), limit=3)

    user = f"""CLUSTER: {cluster} — Cloudera version {version or 'UNSPECIFIED (assume a recent CDP release)'}

CHECK IN FOCUS: {task}
Status: {result.get('status')}
Detail: {result.get('detail')}
Threshold: {result.get('threshold')}
Evidence:
{evidence_digest(result)}

DEPENDENCY CONTEXT (declared knock-on effects if this check is breaching):
{dependency_block(task)}

COMPUTED TRENDS (use only these for time estimates):
{trend_text}

KNOWLEDGE (cite the file names you use):
{knowledge.format_for_prompt(snippets)}

Return JSON with exactly these keys:
{{
  "summary": "2-3 sentences: what is wrong and why it matters",
  "severity": "LOW | MEDIUM | HIGH | CRITICAL",
  "remediation": ["ordered, concrete steps grounded in the knowledge above"],
  "impact": "expected effect on OTHER checks, from the dependency + trend context",
  "related_tasks": ["check names likely affected"],
  "sources": ["knowledge file names you drew remediation from"]
}}"""
    return SYSTEM, user, snippets


def build_incident_prompt(
    *, cluster: str, version: str, breached: list[dict], trend_text: str
) -> tuple[str, str, list[Snippet]]:
    """Prompt for ALL breaches together. Returns (system, user, snippets_used)."""
    all_snippets: list[Snippet] = []
    blocks = []
    for r in breached:
        task = r["task"]
        snips = knowledge.search(task, r.get("detail", ""), limit=2)
        all_snippets.extend(snips)
        blocks.append(
            f"### {task} ({r.get('status')})\n"
            f"Detail: {r.get('detail')}\n"
            f"Evidence: {evidence_digest(r, max_rows=6)}\n"
            f"Dependencies: {dependency_block(task)}"
        )
    tasks = [r["task"] for r in breached]

    user = f"""CLUSTER: {cluster} — Cloudera version {version or 'UNSPECIFIED (assume a recent CDP release)'}

{len(breached)} checks are breaching: {', '.join(tasks)}

{chr(10).join(blocks)}

COMPUTED TRENDS (use only these for time estimates):
{trend_text}

KNOWLEDGE (cite file names you use):
{knowledge.format_for_prompt(_dedupe(all_snippets))}

Connect related problems (a single root cause often explains several), rank each by
severity, and note cross-metric impact from the dependency context. Return JSON:
{{
  "overall_summary": "3-4 sentences across all findings, calling out the likely root cause",
  "findings": [
    {{"primary_task": "check name", "severity": "LOW|MEDIUM|HIGH|CRITICAL",
      "summary": "what's wrong", "remediation": ["steps"], "related_tasks": ["affected checks"]}}
  ],
  "priority_order": ["check names, most urgent first"]
}}"""
    return SYSTEM, user, _dedupe(all_snippets)


def _dedupe(snippets: list[Snippet]) -> list[Snippet]:
    seen = set()
    out = []
    for s in snippets:
        key = (s.source, s.heading)
        if key not in seen:
            seen.add(key)
            out.append(s)
    return out
