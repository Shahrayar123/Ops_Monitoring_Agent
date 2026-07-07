"""The result shape every check returns."""

from typing import Literal, Optional, Union

from pydantic import BaseModel

# OK      = measured and within limits
# BREACH  = measured and something crossed its threshold
# NO_DATA = this check has no data source configured yet (e.g. the services or
#           events export hasn't been provided), so it was not evaluated. It is
#           neither healthy nor breached — the dashboard shows it greyed out.
CheckStatus = Literal["OK", "BREACH", "NO_DATA"]


class CheckResult(BaseModel):
    task: str                                  # which check, e.g. "cpu_percent"
    status: CheckStatus
    metric: str                                # what was measured
    threshold: Optional[Union[float, int, str]]  # the limit it was compared against
    breached_entities: list[str]               # which hosts/services/files are affected
    detail: str                                # human-readable explanation
