"""Load and search the Ops knowledge files in knowledge/.

Files (all optional except the committed best-practices fallback):
    knowledge/cloudera_best_practices.md           generic fallback remediation (committed .md)
    knowledge/cloudera_actionalable_known_isssues.xlsx  Ops known-issue -> agent action table (.xlsx)
    knowledge/runbook.md                           Ops team's runbook (added later)
    knowledge/known_issues.md                      known issue -> resolution (added later, .md)

Retrieval is deliberately simple and dependency-free at query time (no
embeddings): split each file into sections, then score sections for a given
check by an explicit check tag plus keyword overlap with the breach detail. Good
enough for a handful of files, fully debuggable, and the interface stays
identical if we later swap in a vector store.

Markdown sections are tagged by a `## check: <task>` heading. Each row of the
known-issues .xlsx becomes its own section, tagged by mapping its Category
column onto the matching check (see _XLSX_CATEGORY_TO_TASK).

Precedence: the runbook and both known-issue sources rank above the generic
best-practices file, so the Ops team's own actionable guidance wins on ties.
"""

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

KNOWLEDGE_DIR = Path(__file__).resolve().parents[3] / "knowledge"

# Higher rank = preferred when scores tie. Ops-authored files beat the fallback.
_SOURCE_RANK = {
    "runbook.md": 3,
    "known_issues.md": 2,
    "cloudera_actionalable_known_isssues.xlsx": 2,   # actionable known issues — as authoritative as known_issues.md
    "cloudera_best_practices.md": 1,
}

# Maps a known-issues .xlsx "Category" cell onto the monitoring check it belongs
# to, so each row gets the same strong tag boost as a `## check:` md section.
# Lowercased, substring-friendly (see _category_to_task).
_XLSX_CATEGORY_TO_TASK = {
    "host health": "host_health",
    "heartbeat": "heartbeat",
    "cpu": "cpu_percent",
    "ram": "ram_percent",
    "memory": "ram_percent",
    "disk space": "disk_percent",
    "disk": "disk_percent",
    "logs": "disk_percent",           # the disk check covers "Disk & Logs"
    "hdfs": "hdfs_health",
    "service status": "service_status",
    "service": "service_status",
    "alerts": "alerts",
    "health checks": "alerts",
    "network": "network",
}


def _category_to_task(category: str) -> str:
    """Best-effort map of a free-text category label onto a check task id."""
    c = (category or "").strip().lower()
    if c in _XLSX_CATEGORY_TO_TASK:
        return _XLSX_CATEGORY_TO_TASK[c]
    for key, task in _XLSX_CATEGORY_TO_TASK.items():
        if key in c:
            return task
    return ""

# Words too common to help scoring.
_STOP = set(
    "the a an and or of to in on is are was were be been being for with at by "
    "this that these those it its as from not no yes any all more most over under "
    "check host hosts service services".split()
)


@dataclass
class Snippet:
    source: str        # file name, e.g. "cloudera_best_practices.md"
    heading: str       # section heading
    text: str          # section body
    score: float


@dataclass
class _Section:
    source: str
    heading: str
    tag: str           # the "check: <task>" tag if the heading has one, else ""
    body: str
    tokens: set[str]


def _tokenize(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9_]+", text.lower()) if w not in _STOP and len(w) > 2}


def _parse_sections(source: str, content: str) -> list[_Section]:
    """Split a markdown file into sections on `##`/`#` headings."""
    sections: list[_Section] = []
    heading = source
    buf: list[str] = []

    def flush():
        if not heading and not buf:
            return
        body = "\n".join(buf).strip()
        if not body and heading == source:
            return
        tag_match = re.search(r"(?:check|general):\s*([a-z_]+)", heading, re.IGNORECASE)
        tag = ""
        # "## check: disk_percent" -> tag "disk_percent"
        m2 = re.match(r"\s*(?:check|general)\s*:\s*(\S+)", heading, re.IGNORECASE)
        if m2:
            tag = m2.group(1).lower()
        sections.append(_Section(source, heading.strip(), tag, body, _tokenize(heading + " " + body)))

    for line in content.splitlines():
        if re.match(r"^#{1,3}\s+", line):
            flush()
            heading = re.sub(r"^#{1,3}\s+", "", line).strip()
            buf = []
        else:
            buf.append(line)
    flush()
    return sections


_XLSX_COLUMN_ROLES = {
    "category": ("category", "check", "kpi", "metric", "area"),
    "issue": ("issue", "problem", "symptom", "condition", "scenario"),
    "impact": ("impact", "effect", "consequence"),
    "resolution": ("resolution", "action", "fix", "remediat", "step", "response"),
}


def _classify_header(cells: list[str]) -> dict[str, int]:
    """Map header labels to column roles by substring, so minor renames still work."""
    roles: dict[str, int] = {}
    for idx, raw in enumerate(cells):
        label = (raw or "").strip().lower()
        if not label:
            continue
        for role, needles in _XLSX_COLUMN_ROLES.items():
            if role in roles:
                continue
            if any(n in label for n in needles):
                roles[role] = idx
                break
    return roles


def _parse_xlsx(source: str, path: Path) -> list[_Section]:
    """One section per known-issue row: tagged by its Category -> check mapping,
    body = the issue's impact + the actionable resolution the agent should take."""
    try:
        import openpyxl
    except ImportError:  # dependency missing — skip xlsx rather than crash retrieval
        return []
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception:
        return []

    sections: list[_Section] = []
    for ws in wb.worksheets:
        rows = ws.iter_rows(values_only=True)
        header = None
        roles: dict[str, int] = {}
        last_category = ""
        for raw_cells in rows:
            cells = ["" if c is None else str(c).strip() for c in raw_cells]
            if not any(cells):
                continue
            if header is None:
                header = cells
                roles = _classify_header(cells)
                continue
            if not roles:  # no recognizable header — treat whole row as free text
                sections.append(_row_section(source, "", " | ".join(c for c in cells if c)))
                continue

            def cell(role: str) -> str:
                i = roles.get(role)
                return cells[i] if i is not None and i < len(cells) else ""

            category = cell("category") or last_category
            last_category = category or last_category
            issue, impact, resolution = cell("issue"), cell("impact"), cell("resolution")
            if not any((issue, impact, resolution)):
                continue
            heading = f"{category} — {issue}".strip(" —") or category or "Known issue"
            body_parts = []
            if impact:
                body_parts.append(f"Impact: {impact}")
            if resolution:
                body_parts.append(f"Resolution (agent action): {resolution}")
            body = "\n".join(body_parts)
            task = _category_to_task(category)
            sections.append(
                _Section(source, heading, task, body, _tokenize(f"{heading} {body}"))
            )
    wb.close()
    return sections


def _row_section(source: str, category: str, text: str) -> _Section:
    task = _category_to_task(category)
    return _Section(source, text[:80], task, text, _tokenize(text))


@lru_cache(maxsize=1)
def _load_sections_cached(signature: str) -> tuple[_Section, ...]:
    sections: list[_Section] = []
    if not KNOWLEDGE_DIR.is_dir():
        return tuple()
    for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        sections.extend(_parse_sections(path.name, content))
    for path in sorted(KNOWLEDGE_DIR.glob("*.xlsx")):
        if path.name.startswith("~$"):  # skip Excel lock/temp files
            continue
        sections.extend(_parse_xlsx(path.name, path))
    return tuple(sections)


def _dir_signature() -> str:
    """Cheap fingerprint of the knowledge dir so edits/new files bust the cache."""
    if not KNOWLEDGE_DIR.is_dir():
        return "none"
    files = sorted([*KNOWLEDGE_DIR.glob("*.md"), *KNOWLEDGE_DIR.glob("*.xlsx")], key=lambda p: p.name)
    parts = [f"{p.name}:{p.stat().st_mtime_ns}" for p in files if not p.name.startswith("~$")]
    return "|".join(parts) or "empty"


def available_sources() -> list[str]:
    return sorted({s.source for s in _load_sections_cached(_dir_signature())})


def search(task: str, query: str = "", limit: int = 3) -> list[Snippet]:
    """The best knowledge sections for a check (`task`) and optional breach text.

    Scoring: a section tagged for this exact check gets a strong boost; on top of
    that, keyword overlap with the breach detail and the source's precedence rank
    break ties. Returns at most `limit` snippets, best first."""
    sections = _load_sections_cached(_dir_signature())
    if not sections:
        return []

    q_tokens = _tokenize(f"{task} {query}")
    scored: list[Snippet] = []
    for sec in sections:
        score = 0.0
        if sec.tag == task:
            score += 10.0                       # explicit check tag — strongest signal
        elif sec.tag in ("dependencies", "safety", ""):
            score += 0.0                         # general sections stay eligible via keywords
        overlap = len(q_tokens & sec.tokens)
        score += overlap
        score += 0.1 * _SOURCE_RANK.get(sec.source, 0)  # precedence tie-breaker
        if score > 0:
            scored.append(Snippet(sec.source, sec.heading, sec.body, score))

    scored.sort(key=lambda s: s.score, reverse=True)
    return scored[:limit]


def format_for_prompt(snippets: list[Snippet]) -> str:
    """Render snippets as a citable context block for the model prompt."""
    if not snippets:
        return "(No matching entries in the knowledge base.)"
    blocks = []
    for s in snippets:
        blocks.append(f"[{s.source} — {s.heading}]\n{s.text}")
    return "\n\n".join(blocks)
