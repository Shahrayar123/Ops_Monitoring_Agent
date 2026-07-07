"""Data source that talks to a real Cloudera cluster (production).

Combines the CM REST API (cloudera/api_client.py) for health and metrics with
SSH (cloudera/ssh_commands.py) for the two things the API doesn't offer: disk
fullness cross-checks / log file sizes and ping.

Returns exactly the same record types as JsonDataSource, so the checks can't
tell the difference.

Credentials are never written in config files. The tenant config only names
environment variables (e.g. "ACME_CM_USERNAME"); the real values are read from
the environment here, when the source is built — and it fails with a clear
message if one is missing.
"""

import os
import time
from datetime import date
from typing import Optional

import httpx

from cloudera import ClouderaApiClient, SshCommands
from config import TenantConfig

from . import day_filter, parse_cm_export, parse_cm_json
from .base import (
    DataSource,
    DiskUsage,
    Event,
    Host,
    LogFile,
    MetricSeries,
    PingResult,
    Role,
    Service,
)

# How each metric the checks ask for maps to a REAL Cloudera Manager metrics
# query and the parser that shapes the response. Mirrors exactly what the
# offline export source reads, so live and offline behave identically.
#   provides     : the logical metric names this query yields to the checks
#   query        : the CM tsquery string (from the real cluster's CURL commands)
#   parser       : function(raw_json) -> list[MetricSeries]
_METRIC_PLAN = [
    {
        "provides": {"cpu_percent"},
        "query": "select cpu_percent where category=HOST",
        "parser": lambda raw: parse_cm_export.parse_host_metric(raw, "cpu_percent"),
    },
    {
        "provides": {"physical_memory_used", "physical_memory_total"},
        "query": "select physical_memory_used, physical_memory_total where category=HOST",
        "parser": lambda raw: (
            parse_cm_export.parse_host_metric(raw, "physical_memory_used")
            + parse_cm_export.parse_host_metric(raw, "physical_memory_total")
        ),
    },
    {
        "provides": {"fs_bytes_used_percent"},
        "query": "select capacity_used, capacity where category=FILESYSTEM",
        "parser": lambda raw: parse_cm_export.parse_disk_percent(raw),
    },
    {
        "provides": {"dfs_capacity", "dfs_capacity_used"},
        "query": "select dfs_capacity, dfs_capacity_used where serviceType=HDFS",
        "parser": lambda raw: parse_cm_export.parse_hdfs_capacity(raw),
    },
    {
        "provides": {"total_bytes_receive_rate_across_network_interfaces"},
        "query": "select total_bytes_receive_rate_across_network_interfaces where category=HOST",
        "parser": lambda raw: parse_cm_export.parse_network_throughput(raw),
    },
]


# Defaults used when a tenant's YAML doesn't set them (see ClouderaConfig).
DEFAULT_LOOKBACK_DAYS = 3
DEFAULT_METRICS_CACHE_TTL_SEC = 300


def _lookback_start_utc(lookback_days: int) -> str:
    """ISO timestamp for 00:00 UTC, `lookback_days` ago."""
    from datetime import datetime, time, timedelta, timezone

    start_day = datetime.now(timezone.utc).date() - timedelta(days=lookback_days - 1)
    return datetime.combine(start_day, time.min, tzinfo=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )


class MissingEnvVarError(Exception):
    """A tenant config referenced an environment variable that isn't set."""


def _read_env(var_name: str) -> str:
    value = os.environ.get(var_name)
    if not value:
        raise MissingEnvVarError(
            f"Environment variable '{var_name}' is not set (referenced by tenant config)."
        )
    return value


class ClouderaApiSource(DataSource):
    def __init__(
        self,
        tenant: TenantConfig,
        transport: Optional[httpx.BaseTransport] = None,
        ssh: Optional[SshCommands] = None,
    ):
        if tenant.cloudera is None or tenant.credentials is None:
            raise ValueError(
                "ClouderaApiSource needs the tenant's cloudera and credentials settings"
            )

        self._tenant = tenant
        self._api = ClouderaApiClient(
            cm_host=tenant.cloudera.cm_host,
            port=tenant.cloudera.port,
            username=_read_env(tenant.credentials.username_env),
            password=_read_env(tenant.credentials.password_env),
            use_tls=tenant.cloudera.use_tls,
            tls_cert_path=tenant.cloudera.tls_cert_path,
            api_version=tenant.cloudera.api_version,
            transport=transport,
        )

        # SSH is optional: only set up when the tenant config provides it.
        self._ssh = ssh
        if self._ssh is None and tenant.ssh and tenant.ssh.username_env and tenant.ssh.key_path_env:
            self._ssh = SshCommands(
                username=_read_env(tenant.ssh.username_env),
                key_path=_read_env(tenant.ssh.key_path_env),
                port=tenant.ssh.port,
            )

        # How much history to pull and how long to cache it — per-tenant, from
        # the cloudera block, falling back to sensible defaults.
        self._lookback_days = tenant.cloudera.lookback_days
        self._cache_ttl_sec = tenant.cloudera.metrics_cache_ttl_sec

        # Which day to view (None = most recent), same as the export source.
        self.as_of: Optional["date"] = None
        # Short-lived cache of fetched metric series, keyed by the plan query.
        self._metrics_cache: dict[str, tuple[float, list]] = {}

    def close(self) -> None:
        self._api.close()

    def check_connection(self) -> str:
        """Confirm the cluster is reachable; returns the API version it speaks."""
        return self._api.resolve_version()

    # ---- from the CM REST API ----

    def get_hosts(self) -> list[Host]:
        raw = self._api.get_hosts()
        return [parse_cm_export.parse_host_file(item) for item in raw.get("items", [])]

    def get_services(self, cluster_name: str) -> list[Service]:
        return parse_cm_json.parse_services(self._api.get_services(cluster_name), cluster_name)

    def get_roles(self, cluster_name: str, service_name: str) -> list[Role]:
        return parse_cm_json.parse_roles(
            self._api.get_roles(cluster_name, service_name), cluster_name, service_name
        )

    def get_metrics(self, metric_names: list[str]) -> list[MetricSeries]:
        wanted = set(metric_names)

        series: list[MetricSeries] = []
        for plan in _METRIC_PLAN:
            # Run a plan if the caller wants any metric it provides (or wants all).
            if wanted and not (plan["provides"] & wanted):
                continue
            series.extend(self._fetch_plan(plan))

        if wanted:
            series = [s for s in series if s.metric_name in wanted]
        # Trim to the selected day so `points[-1]` is the value "as of" that day.
        return day_filter.trim_to_day(series, self.as_of)

    def _fetch_plan(self, plan: dict) -> list[MetricSeries]:
        """Fetch (and briefly cache) this tenant's history for one query."""
        query = plan["query"]
        cached = self._metrics_cache.get(query)
        if cached and (time.monotonic() - cached[0]) < self._cache_ttl_sec:
            return cached[1]

        raw = self._api.query_metrics(query, from_time=_lookback_start_utc(self._lookback_days))
        parsed = plan["parser"](raw)
        self._metrics_cache[query] = (time.monotonic(), parsed)
        return parsed

    def get_events(self, category: str = "HEALTH_CHECK", alert_only: bool = True) -> list[Event]:
        query = f"category=={category}"
        if alert_only:
            query = f"alert==true;{query}"
        return parse_cm_json.parse_events(self._api.get_events(query), category, alert_only)

    # ---- over SSH ----

    def get_disk_usage(self) -> list[DiskUsage]:
        ssh = self._require_ssh()
        mounts = self._tenant.thresholds.disk_mounts
        results: list[DiskUsage] = []
        for host in self.get_hosts():
            for entry in ssh.get_disk_usage(host.hostname, mounts):
                results.append(DiskUsage(**entry))
        return results

    def ping_hosts(self) -> list[PingResult]:
        ssh = self._require_ssh()
        return [PingResult(**ssh.ping_host(host.hostname)) for host in self.get_hosts()]

    def get_log_files(self) -> list[LogFile]:
        ssh = self._require_ssh()
        log_dirs = self._tenant.ssh.log_dirs if self._tenant.ssh else []
        results: list[LogFile] = []
        for host in self.get_hosts():
            for entry in ssh.get_log_files(host.hostname, log_dirs):
                results.append(LogFile(**entry))
        return results

    def _require_ssh(self) -> SshCommands:
        if self._ssh is None:
            raise ValueError(
                "This tenant has no SSH settings (username_env/key_path_env) — "
                "disk usage, ping, and log file checks need SSH access."
            )
        return self._ssh

    # ---- day filter (same behavior as the export source) ----

    def available_dates(self) -> list["date"]:
        """The days present in the fetched CPU history — powers the dashboard's
        date picker in live mode too. Uses the untrimmed (full-range) series."""
        cpu_plan = next(p for p in _METRIC_PLAN if "cpu_percent" in p["provides"])
        full_series = self._fetch_plan(cpu_plan)  # NOT trimmed to as_of
        return day_filter.days_present(full_series)

    def reference_now(self):
        """Judge heartbeats against the newest host heartbeat (consistent with
        the export source)."""
        return day_filter.reference_now(self.get_hosts())
