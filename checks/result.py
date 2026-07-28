"""The result shape every check returns."""

from typing import Literal, Optional, Union

from pydantic import BaseModel

# OK      = measured and within limits
# BREACH  = measured and something crossed its threshold
# NO_DATA = this check has no data source configured yet (e.g. the services or
#           events export hasn't been provided), so it was not evaluated. It is
#           neither healthy nor breached — the dashboard shows it greyed out.
CheckStatus = Literal["OK", "BREACH", "NO_DATA"]


class EvidenceRow(BaseModel):
    """One reading the check looked at, e.g. one host's CPU or one disk mount.

    This is the raw material behind the OK/BREACH verdict — the dashboard shows
    these rows in an expandable "what was checked" panel so anyone can trace a
    card's status back to the exact values it came from (green = within limits,
    red = the reading that crossed its threshold)."""

    entity: str          # what this reading is about, e.g. "node1:/u01" or "hdfs"
    value: str           # the observed value, formatted for display, e.g. "96.9%"
    breached: bool       # True = this reading crossed its limit (shown red)


class CheckEvidence(BaseModel):
    """The traceable data behind one check's verdict: where it came from, which
    keys were read, and every reading that was compared against the threshold."""

    source: str              # provenance: file name(s) or API endpoint the data came from
    keys_checked: list[str]  # the JSON keys / metric names inspected, e.g. ["cpu_percent"]
    rows: list[EvidenceRow]  # one row per reading examined


class CheckResult(BaseModel):
    task: str                                  # which check, e.g. "cpu_percent"
    status: CheckStatus
    metric: str                                # what was measured
    threshold: Optional[Union[float, int, str]]  # the limit it was compared against
    breached_entities: list[str]               # which hosts/services/files are affected
    detail: str                                # human-readable explanation
    # The per-reading data behind the verdict (for the dashboard's traceability
    # panel). Optional so older callers / NO_DATA checks can leave it unset.
    evidence: Optional[CheckEvidence] = None
