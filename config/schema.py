"""What a tenant's configuration looks like.

One tenant = one customer's cluster. Everything customer-specific (addresses,
thresholds, credentials) lives in a YAML file per tenant under config/tenants/
— never in code. Secrets are referenced by environment-variable NAME only; the
actual values live in .env or the real process environment.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


class DataSourceConfig(BaseModel):
    """Where this tenant's monitoring data comes from.

    type "json"   reads the older hand-made sample files from `data_dir`;
    type "export" reads real Cloudera Manager API exports from `data_dir`
                  (a folder with hosts/ and metrics/ subfolders);
    type "api"    calls the tenant's real Cloudera cluster live.

    "json" and "export" are both offline/file-based; the difference is only the
    on-disk layout each expects.
    """

    type: Literal["json", "export", "api"]
    data_dir: Optional[str] = None


class ClouderaConfig(BaseModel):
    """How to reach this tenant's Cloudera Manager (only needed for type "api")."""

    cm_host: str
    port: int = 7183
    use_tls: bool = True
    api_version: str = "auto"          # "auto" = ask the cluster at startup
    tls_cert_path: Optional[str] = None

    # How many days of metric history to fetch (powers the date picker). Fewer
    # days = smaller, faster responses; more = longer look-back.
    lookback_days: int = Field(default=3, ge=1)
    # How long fetched metrics are cached before re-querying the cluster. Metrics
    # are HOURLY, so a few minutes loses nothing and protects CM from the ~10s
    # auto-refresh. Lower it only if you want the numbers to update more often.
    metrics_cache_ttl_sec: int = Field(default=300, ge=0)


class CredentialsConfig(BaseModel):
    """Names of the environment variables holding the Cloudera login.
    The values themselves are never written in config files."""

    username_env: str
    password_env: str


class SSHConfig(BaseModel):
    """How to SSH into this tenant's machines (for disk/log/ping checks)."""

    host: Optional[str] = None
    port: int = 22
    username_env: Optional[str] = None
    key_path_env: Optional[str] = None   # env var holding the PATH to the key file
    log_dirs: list[str] = Field(default_factory=lambda: ["/var/log"])


class ThresholdsConfig(BaseModel):
    """The limits the checks compare against. Every tenant can tune these;
    the defaults below apply when a tenant's YAML doesn't set them."""

    cpu_pct: float = Field(default=60.0, ge=0, le=100)
    ram_pct: float = Field(default=60.0, ge=0, le=100)
    disk_pct: float = Field(default=90.0, ge=0, le=100)
    disk_mounts: list[str] = Field(default_factory=lambda: ["/var", "/opt", "/home", "/tmp"])
    heartbeat_window_sec: int = Field(default=60, ge=1)
    log_size_mb: float = Field(default=1024.0, ge=0)
    hdfs_growth_pct_window_hours: int = Field(default=24, ge=1)
    hdfs_growth_pct_threshold: float = Field(default=10.0, ge=0)
    network_error_rate_threshold: float = Field(default=0.0, ge=0)


class RedisConfig(BaseModel):
    """Optional Redis for caching/history — off by default."""

    enabled: bool = False
    url: Optional[str] = None


class TenantConfig(BaseModel):
    tenant_id: str
    display_name: str
    cluster_name: str
    data_source: DataSourceConfig
    cloudera: Optional[ClouderaConfig] = None
    credentials: Optional[CredentialsConfig] = None
    ssh: Optional[SSHConfig] = None
    thresholds: ThresholdsConfig = Field(default_factory=ThresholdsConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)

    @model_validator(mode="after")
    def _require_settings_for_chosen_source(self) -> "TenantConfig":
        """Fail loudly at load time if the chosen data source is missing the
        settings it needs — better than a confusing error later."""
        missing: list[str] = []

        if self.data_source.type in ("json", "export"):
            if not self.data_source.data_dir:
                missing.append(
                    f"data_source.data_dir is required when data_source.type == '{self.data_source.type}'"
                )
        elif self.data_source.type == "api":
            if self.cloudera is None:
                missing.append("cloudera settings are required when data_source.type == 'api'")
            if self.credentials is None:
                missing.append("credentials settings are required when data_source.type == 'api'")

        if missing:
            raise ValueError("; ".join(missing))

        return self
