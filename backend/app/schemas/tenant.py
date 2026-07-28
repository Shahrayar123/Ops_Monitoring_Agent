"""Request/response shapes for tenants, thresholds, files, and connections."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class TenantSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    display_name: str
    cluster_name: str
    cloudera_version: str
    data_source_mode: str
    is_active: bool


class FileInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    file_type: str
    original_name: str
    size_bytes: int
    validation_status: str
    validation_detail: str
    uploaded_at: datetime


class TenantDetail(TenantSummary):
    data_dir: str
    cm_host: str
    cm_port: int
    cm_use_tls: bool
    cm_username: str
    has_cm_password: bool = False
    thresholds: dict
    refresh_rates: dict
    files: list[FileInfo] = []
    coverage: Optional[dict] = None


class TenantCreate(BaseModel):
    slug: str = Field(min_length=2, max_length=100, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    display_name: str = Field(min_length=1, max_length=255)
    cluster_name: str = Field(min_length=1, max_length=255)
    cloudera_version: str = Field(default="", max_length=50)
    data_source_mode: str = Field(default="json", pattern=r"^(json|api)$")


class TenantUpdate(BaseModel):
    display_name: Optional[str] = None
    cluster_name: Optional[str] = None
    cloudera_version: Optional[str] = None
    data_source_mode: Optional[str] = Field(default=None, pattern=r"^(json|api)$")
    is_active: Optional[bool] = None


class CmConnection(BaseModel):
    cm_host: str = Field(min_length=1)
    cm_port: int = Field(default=7183, ge=1, le=65535)
    cm_use_tls: bool = True
    cm_username: str = Field(min_length=1)
    cm_password: Optional[str] = None  # write-only; omit to keep the stored one


class ThresholdsUpdate(BaseModel):
    # All optional — send only what changed. Ranges mirror the engine's schema.
    cpu_pct: Optional[float] = Field(default=None, ge=0, le=100)
    ram_pct: Optional[float] = Field(default=None, ge=0, le=100)
    disk_pct: Optional[float] = Field(default=None, ge=0, le=100)
    disk_mounts: Optional[list[str]] = None
    heartbeat_window_sec: Optional[int] = Field(default=None, ge=1)
    log_size_mb: Optional[float] = Field(default=None, ge=0)
    hdfs_growth_pct_window_hours: Optional[int] = Field(default=None, ge=1)
    hdfs_growth_pct_threshold: Optional[float] = Field(default=None, ge=0)
    network_error_rate_threshold: Optional[float] = Field(default=None, ge=0)


class RefreshRatesUpdate(BaseModel):
    # task -> seconds; only provided tasks are overridden.
    rates: dict[str, int]
