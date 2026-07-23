"""Data source that reads the sample JSON files in the data/ folder.

Used for development and demos — the whole system runs offline with it. The
files are shaped exactly like real Cloudera Manager API responses, so the same
parsing code (parse_cm_json.py) handles both this source and the live one.

The files are read fresh on every call — NOT cached — so editing a JSON file
shows up on the dashboard's next refresh, just like a real cluster's changing
data would. These files are tiny, so re-reading costs nothing.
"""

import json
from pathlib import Path

from . import parse_cm_json
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

# Project root (two levels up from this file: data_sources/json_source.py ->
# data_sources/ -> project root). A relative data_dir like "data" in a tenant's
# YAML is resolved against THIS, not against whatever folder the app happens
# to be launched from — so it works the same regardless of how the backend
# was started (uvicorn, a desktop shortcut, or a scheduled task).
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Every file a tenant's data folder must contain.
REQUIRED_FILES = [
    "sample_hosts.json",
    "sample_services.json",
    "sample_roles.json",
    "sample_timeseries.json",
    "sample_events.json",
    "sample_ssh_results.json",
]

# Which sample file each logical data kind is read from — powers the dashboard's
# "where did this come from" panel. All time-series metrics share one file here.
_PROVENANCE = {
    "hosts": "sample_hosts.json",
    "services": "sample_services.json",
    "roles": "sample_roles.json",
    "events": "sample_events.json",
    "cpu_percent": "sample_timeseries.json",
    "physical_memory_used": "sample_timeseries.json",
    "physical_memory_total": "sample_timeseries.json",
    "fs_bytes_used_percent": "sample_timeseries.json",
    "dfs_capacity_used": "sample_timeseries.json",
    "total_bytes_receive_rate_across_network_interfaces": "sample_timeseries.json",
    "disk_usage": "sample_ssh_results.json",
    "ping": "sample_ssh_results.json",
    "log_files": "sample_ssh_results.json",
}


class JsonDataSource(DataSource):
    def __init__(self, data_dir: str | Path):
        data_dir = Path(data_dir)
        if not data_dir.is_absolute():
            data_dir = PROJECT_ROOT / data_dir
        self._data_dir = data_dir

        # Check everything exists up front so a missing file fails immediately
        # with a clear message, not later in the middle of a monitoring run.
        for name in REQUIRED_FILES:
            if not (data_dir / name).is_file():
                raise FileNotFoundError(f"Data file not found: {data_dir / name}")

    def _read(self, filename: str) -> dict:
        path = self._data_dir / filename
        if not path.is_file():
            raise FileNotFoundError(f"Data file not found: {path}")
        with path.open(encoding="utf-8") as f:
            return json.load(f)

    # ---- data that would come from the CM API on a real cluster ----

    def get_hosts(self) -> list[Host]:
        return parse_cm_json.parse_hosts(self._read("sample_hosts.json"))

    def get_services(self, cluster_name: str) -> list[Service]:
        return parse_cm_json.parse_services(self._read("sample_services.json"), cluster_name)

    def get_roles(self, cluster_name: str, service_name: str) -> list[Role]:
        return parse_cm_json.parse_roles(
            self._read("sample_roles.json"), cluster_name, service_name
        )

    def get_metrics(self, metric_names: list[str]) -> list[MetricSeries]:
        return parse_cm_json.parse_metrics(self._read("sample_timeseries.json"), metric_names)

    def get_events(self, category: str | None = None, alert_only: bool = True) -> list[Event]:
        return parse_cm_json.parse_events(self._read("sample_events.json"), category, alert_only)

    # ---- data that would come from SSH on a real cluster ----

    def get_disk_usage(self) -> list[DiskUsage]:
        return [DiskUsage(**entry) for entry in self._read("sample_ssh_results.json")["disk_usage"]]

    def ping_hosts(self) -> list[PingResult]:
        return [PingResult(**entry) for entry in self._read("sample_ssh_results.json")["ping_results"]]

    def get_log_files(self) -> list[LogFile]:
        return [LogFile(**entry) for entry in self._read("sample_ssh_results.json")["log_files"]]

    # ---- metadata ----

    def provenance(self, data_kind: str) -> str:
        name = _PROVENANCE.get(data_kind, data_kind)
        try:
            return str((self._data_dir / name).relative_to(PROJECT_ROOT)).replace("\\", "/")
        except ValueError:  # data_dir outside the project — show the folder + file
            return f"{self._data_dir.name}/{name}"
