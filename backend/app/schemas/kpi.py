"""Request/response shapes for per-user KPI refresh-rate settings."""

from pydantic import BaseModel, Field


class KpiRefreshRateOut(BaseModel):
    task: str
    default_seconds: int
    seconds: int          # effective value: the user's override, or default_seconds
    is_override: bool      # whether `seconds` came from an override or the default


class SetKpiRefreshRateRequest(BaseModel):
    task: str
    seconds: int = Field(ge=5, le=3600)
