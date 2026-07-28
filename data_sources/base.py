"""The DataSource interface and the simple record types it returns.

Every check reads cluster data through these records only. Both the JSON source
and the live API source return exactly these shapes, so the checks never know
(or care) which one is active.
"""

from abc import ABC, abstractmethod
from datetime import date, datetime

from pydantic import BaseModel


# ---------- record types (what the data looks like) ----------


class HealthCheck(BaseModel):
    """One named health verdict computed by Cloudera Manager itself,
    e.g. name='HOST_SCM_HEALTH', summary='GOOD' (or 'CONCERNING'/'BAD')."""

    name: str
    summary: str


class Host(BaseModel):
    """One machine in the cluster."""

    host_id: str
    hostname: str
    ip_address: str
    health_summary: str          # GOOD / CONCERNING / BAD, decided by CM
    last_heartbeat: datetime     # when this machine last reported in
    health_checks: list[HealthCheck]
    num_cores: int
    total_phys_mem_bytes: int


class Service(BaseModel):
    """One cluster service, e.g. HDFS (storage) or YARN (job scheduling)."""

    name: str
    type: str
    cluster_name: str
    service_state: str           # STARTED / STOPPED / ...
    health_summary: str
    health_checks: list[HealthCheck]


class Role(BaseModel):
    """One part of a service running on one machine,
    e.g. the HDFS NameNode on host-1."""

    name: str
    type: str
    service_name: str
    host_id: str
    health_summary: str
    health_checks: list[HealthCheck]


class MetricPoint(BaseModel):
    """One measured value at one moment in time."""

    timestamp: datetime
    value: float


class MetricSeries(BaseModel):
    """One metric measured over time for one thing (a host, a disk, a service).
    Example: cpu_percent for node1 = [(10:00, 42.5), (10:01, 43.1), ...]"""

    metric_name: str
    entity_name: str             # which host/disk/service this is about
    category: str                # HOST / FILESYSTEM / SERVICE
    attributes: dict[str, str]
    points: list[MetricPoint]


class Event(BaseModel):
    """One alert or warning raised by Cloudera Manager."""

    id: str
    content: str
    time_occurred: datetime
    category: str
    severity: str
    alert: bool
    attributes: dict[str, list[str]]


class DiskUsage(BaseModel):
    """How full one disk mount on one machine is (from SSH `df`)."""

    hostname: str
    mount_point: str
    used_percent: float


class PingResult(BaseModel):
    """Whether one machine answered, and how fast (from SSH)."""

    hostname: str
    reachable: bool
    latency_ms: float | None


class LogFile(BaseModel):
    """One log file and its size (from SSH `find`)."""

    hostname: str
    path: str
    size_bytes: int


# ---------- the interface every data source implements ----------


class DataSource(ABC):
    @abstractmethod
    def get_hosts(self) -> list[Host]:
        """All machines in the cluster."""

    @abstractmethod
    def get_services(self, cluster_name: str) -> list[Service]:
        """All services in the given cluster."""

    @abstractmethod
    def get_roles(self, cluster_name: str, service_name: str) -> list[Role]:
        """All parts of one service, per machine."""

    @abstractmethod
    def get_metrics(self, metric_names: list[str]) -> list[MetricSeries]:
        """Numeric measurements for the given metric names.
        An empty list means: return everything available."""

    @abstractmethod
    def get_events(self, category: str | None = None, alert_only: bool = True) -> list[Event]:
        """Alert/warning events. category=None keeps every event category."""

    @abstractmethod
    def get_disk_usage(self) -> list[DiskUsage]:
        """Disk fullness per machine and mount (via SSH on the live source)."""

    @abstractmethod
    def ping_hosts(self) -> list[PingResult]:
        """Reachability of every machine (via SSH on the live source)."""

    @abstractmethod
    def get_log_files(self) -> list[LogFile]:
        """Log files and their sizes per machine (via SSH on the live source)."""

    # ---- capabilities (checks use these to skip what a source can't provide) ----

    def has_services(self) -> bool:
        """Whether this source can provide the services/roles list. When False,
        the service-status check reports NO_DATA instead of a misleading result."""
        return True

    def has_events(self) -> bool:
        """Whether this source can provide alert events. When False, the alerts
        check reports NO_DATA."""
        return True

    def available_dates(self) -> list[date]:
        """Distinct days present in the data (used by the dashboard date filter).
        Sources without multi-day history return an empty list."""
        return []

    def provenance(self, data_kind: str) -> str:
        """Where a kind of data physically comes from, in human terms — a file
        name for file-backed sources, an API endpoint for the live source.

        `data_kind` is a logical name the checks use: "hosts", "services",
        "events", or a metric name like "cpu_percent" / "fs_bytes_used_percent".
        Powers the dashboard's "what was checked, and where from" panel. The
        default just echoes the kind; each concrete source overrides it."""
        return data_kind
