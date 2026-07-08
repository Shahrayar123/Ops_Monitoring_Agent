"""Data source that reads real Cloudera Manager API exports from a folder.

Folder layout (data/<tenant>/):
    hosts/*.json      one host resource file each (view=FULL)
    metrics/cpu.json
    metrics/ram.json
    metrics/disk.json
    metrics/hdfs.json
    metrics/network.json
    services.json     (optional — not yet provided by Ops)
    events.json       (optional — not yet provided by Ops)

Two production concerns handled here:

1. Speed + freshness: the disk export can be tens of MB. Re-reading it on every
   10-second dashboard refresh would be slow, but never re-reading means edits
   don't show up. So each file is cached and only re-read when its modification
   time changes on disk — fast when nothing changed, live when it does.

2. Date filtering: the exports hold several days of hourly data, but we normally
   care about one day. Set `as_of` to a date and get_metrics() returns each
   series trimmed to that day (its last point becomes the value "as of" that
   day). Leave `as_of` as None to use the most recent data.
"""

import json
from datetime import date, datetime, timezone
from pathlib import Path

from . import day_filter, parse_cm_export as parse
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

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class ClouderaExportSource(DataSource):
    def __init__(self, data_dir: str | Path):
        data_dir = Path(data_dir)
        if not data_dir.is_absolute():
            data_dir = PROJECT_ROOT / data_dir
        self._dir = data_dir
        self._hosts_dir = data_dir / "hosts"
        self._metrics_dir = data_dir / "metrics"

        if not self._hosts_dir.is_dir():
            raise FileNotFoundError(f"Hosts folder not found: {self._hosts_dir}")
        if not self._metrics_dir.is_dir():
            raise FileNotFoundError(f"Metrics folder not found: {self._metrics_dir}")

        # mtime cache: path -> (mtime_when_read, parsed_json)
        self._cache: dict[Path, tuple[float, dict]] = {}

        # Which day to evaluate. None = use the latest data available.
        self.as_of: date | None = None

    # ---- cached file reading ----

    def _read(self, path: Path) -> dict:
        mtime = path.stat().st_mtime
        cached = self._cache.get(path)
        if cached and cached[0] == mtime:
            return cached[1]
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        self._cache[path] = (mtime, data)
        return data

    def _metric_file(self, name: str) -> dict:
        return self._read(self._metrics_dir / name)

    def _trim(self, series: list[MetricSeries]) -> list[MetricSeries]:
        return day_filter.trim_to_day(series, self.as_of)

    # ---- hosts (from the CM API on a real cluster) ----

    def get_hosts(self) -> list[Host]:
        hosts = []
        for path in sorted(self._hosts_dir.glob("*.json")):
            hosts.append(parse.parse_host_file(self._read(path)))
        return hosts

    def get_services(self, cluster_name: str) -> list[Service]:
        if not self.has_services():
            return []
        return parse.parse_services(self._read(self._dir / "services.json"), cluster_name)

    def get_roles(self, cluster_name: str, service_name: str) -> list[Role]:
        # A separate roles export isn't provided; the service-status check works
        # from service-level health checks alone when roles are empty.
        return []

    def get_metrics(self, metric_names: list[str]) -> list[MetricSeries]:
        series: list[MetricSeries] = []
        if not metric_names or "cpu_percent" in metric_names:
            series += parse.parse_host_metric(self._metric_file("cpu.json"), "cpu_percent")
        if not metric_names or "physical_memory_used" in metric_names:
            series += parse.parse_host_metric(self._metric_file("ram.json"), "physical_memory_used")
        if not metric_names or "physical_memory_total" in metric_names:
            series += parse.parse_host_metric(self._metric_file("ram.json"), "physical_memory_total")
        if not metric_names or "fs_bytes_used_percent" in metric_names:
            series += parse.parse_disk_percent(self._metric_file("disk.json"))
        if not metric_names or "dfs_capacity" in metric_names or "dfs_capacity_used" in metric_names:
            series += parse.parse_hdfs_capacity(self._metric_file("hdfs.json"))
        if not metric_names or "total_bytes_receive_rate_across_network_interfaces" in metric_names:
            series += parse.parse_network_throughput(self._metric_file("network.json"))

        if metric_names:
            series = [s for s in series if s.metric_name in metric_names]
        return self._trim(series)

    def get_events(self, category: str | None = None, alert_only: bool = True) -> list[Event]:
        if not self.has_events():
            return []
        return parse.parse_events(self._read(self._dir / "events.json"), category, alert_only)

    # ---- SSH data: not part of an API export ----

    def get_disk_usage(self) -> list[DiskUsage]:
        return []

    def ping_hosts(self) -> list[PingResult]:
        return []

    def get_log_files(self) -> list[LogFile]:
        return []

    # ---- capabilities / metadata ----

    def has_services(self) -> bool:
        return (self._dir / "services.json").is_file()

    def has_events(self) -> bool:
        return (self._dir / "events.json").is_file()

    def available_dates(self) -> list[date]:
        """The distinct days present in the CPU metric (cheap and covers all hosts)."""
        series = parse.parse_host_metric(self._metric_file("cpu.json"), "cpu_percent")
        return day_filter.days_present(series)

    def reference_now(self) -> datetime:
        """The moment this view represents — the newest host heartbeat (so a
        several-days-old view isn't reported as every host being silent)."""
        return day_filter.reference_now(self.get_hosts())
