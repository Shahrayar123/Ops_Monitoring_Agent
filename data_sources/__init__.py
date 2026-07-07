"""Where monitoring data comes from.

A "data source" answers questions like "list the hosts", "get the CPU numbers",
"which disks are how full" — always in the same simple record shapes, no matter
where the data actually came from. There are two implementations:

- json_source.py : reads sample JSON files from the data/ folder (offline dev/demo)
- api_source.py  : calls the real Cloudera cluster (API + SSH) in production

The checks in checks/ only ever talk to the DataSource interface, so switching
between sample data and a live cluster changes nothing in the checks.

choose_data_source() picks which one to use based on USE_JSON in .env.
"""

from .base import (
    DataSource,
    DiskUsage,
    Event,
    HealthCheck,
    Host,
    LogFile,
    MetricPoint,
    MetricSeries,
    PingResult,
    Role,
    Service,
)
from .json_source import JsonDataSource
from .export_source import ClouderaExportSource
from .api_source import ClouderaApiSource, MissingEnvVarError
from .select import DataSourceError, choose_data_source

__all__ = [
    "DataSource",
    "DiskUsage",
    "Event",
    "HealthCheck",
    "Host",
    "LogFile",
    "MetricPoint",
    "MetricSeries",
    "PingResult",
    "Role",
    "Service",
    "JsonDataSource",
    "ClouderaExportSource",
    "ClouderaApiSource",
    "MissingEnvVarError",
    "DataSourceError",
    "choose_data_source",
]
