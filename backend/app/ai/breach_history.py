"""Append every completed AI analysis to a shared, cross-user breach history.

    context/breach_history.csv

One row per finding: what breached (deterministic detail from the engine), and
what the AI said about it (summary, remediation, impact). It accumulates across
ALL users and clusters — this is a corpus, not a per-user view — so you can look
back and ask "what keeps breaking, and what did we tell people to do about it?",
and later feed the file to an LLM as retrieval context.

CSV rather than .xlsx on purpose: this file is append-only and written from
concurrent background job threads. A CSV append is one line, opened and closed;
an .xlsx would mean reading, mutating and rewriting the whole workbook on every
analysis, and would break if anyone had it open in Excel at the time. CSV opens
in Excel directly anyway, so nothing is lost.

Nothing here may ever fail an analysis: `record_*` swallows every exception and
logs it. A history-file problem is worth knowing about, but it is not worth
turning a successful analysis into a failed job.
"""

from __future__ import annotations

import csv
import logging
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # imported for types only — avoids a circular import at runtime
    from .models import IncidentReport, KpiAnalysis

log = logging.getLogger("backend.ai.breach_history")

REPO_ROOT = Path(__file__).resolve().parents[3]
CONTEXT_DIR = REPO_ROOT / "context"
HISTORY_FILE = CONTEXT_DIR / "breach_history.csv"

# Appends come from background analysis threads (ai/jobs.py), which can overlap.
# One lock around the open-append-close keeps rows from interleaving mid-line.
_LOCK = threading.Lock()

COLUMNS = [
    "timestamp",          # UTC ISO-8601, when the analysis completed
    "analysis_type",      # "kpi" (one card) | "incident" (all breaches together)
    "cluster",
    "cloudera_version",
    "task",               # the monitoring check that breached
    "severity",           # AFTER the deterministic floor — the governed value
    "breach_detail",      # what the engine actually measured (not model output)
    "summary",            # ---- everything below is model output ----
    "remediation",        # steps joined with " | ", in order
    "impact",             # effect on other metrics
    "related_tasks",
    "trend_note",
    "sources",            # knowledge files cited
    "overall_summary",    # incident rows only: the cross-breach narrative
    "model_used",
]


def _clean(value) -> str:
    """Flatten to a single line so one row == one line in the file.

    The csv module would happily quote embedded newlines, but a multi-line row
    is miserable to grep and confusing when the file is pasted to an LLM later.
    """
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        value = " | ".join(str(v).strip() for v in value if str(v).strip())
    return re.sub(r"\s+", " ", str(value)).strip()


def _append(rows: list[dict]) -> None:
    """Write rows, creating the file with a header the first time."""
    if not rows:
        return
    with _LOCK:
        CONTEXT_DIR.mkdir(parents=True, exist_ok=True)
        is_new = not HISTORY_FILE.exists() or HISTORY_FILE.stat().st_size == 0
        # newline="" is required by the csv module on Windows, or every row is
        # written with a blank line between it and the next.
        with HISTORY_FILE.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
            if is_new:
                writer.writeheader()
            for row in rows:
                writer.writerow({col: _clean(row.get(col)) for col in COLUMNS})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def record_kpi(analysis: "KpiAnalysis", *, cluster: str, version: str, breach_detail: str) -> None:
    """One row for a single-KPI analysis. Never raises."""
    try:
        _append([{
            "timestamp": _now(),
            "analysis_type": "kpi",
            "cluster": cluster,
            "cloudera_version": version,
            "task": analysis.task,
            "severity": analysis.severity,
            "breach_detail": breach_detail,
            "summary": analysis.summary,
            "remediation": analysis.remediation,
            "impact": analysis.impact,
            "related_tasks": analysis.related_tasks,
            "trend_note": analysis.trend_note,
            "sources": analysis.sources,
            "model_used": analysis.model_used,
        }])
    except Exception:
        log.exception("Could not append KPI analysis to %s", HISTORY_FILE)


def record_incident(
    report: "IncidentReport", *, cluster: str, version: str, details: Optional[dict] = None
) -> None:
    """One row per finding in an incident report. Never raises.

    `details` maps task -> the engine's breach detail, so each row keeps the
    measured fact next to the model's explanation of it.
    """
    try:
        details = details or {}
        _append([{
            "timestamp": _now(),
            "analysis_type": "incident",
            "cluster": cluster,
            "cloudera_version": version,
            "task": f.primary_task,
            "severity": f.severity,
            "breach_detail": details.get(f.primary_task, ""),
            "summary": f.summary,
            "remediation": f.remediation,
            "related_tasks": f.related_tasks,
            "overall_summary": report.overall_summary,
            "model_used": report.model_used,
        } for f in report.findings])
    except Exception:
        log.exception("Could not append incident analysis to %s", HISTORY_FILE)
