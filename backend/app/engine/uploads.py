"""Validate and store uploaded Cloudera Manager export files for a json-mode tenant.

Each tenant's files live under backend/uploads/<slug>/ in the exact layout the
engine's export source expects:

    hosts/<name>.json     one or more host resource files
    metrics/cpu.json      host CPU %
    metrics/ram.json      physical memory used/total
    metrics/disk.json     filesystem capacity
    metrics/hdfs.json     HDFS capacity
    metrics/network.json  receive throughput
    services.json         (optional) services + health
    events.json           (optional) alert events

A file is validated by running the engine's REAL parser for its type — so "valid"
means "the checks will actually be able to read this", not just "it's JSON".
"""

import json
from pathlib import Path

from data_sources import parse_cm_export as parse

UPLOAD_ROOT = Path(__file__).resolve().parents[3] / "backend" / "uploads"

# file_type -> (relative destination, validator). Validators raise on bad shape.
_METRIC_CHECK = {
    "cpu": lambda d: parse.parse_host_metric(d, "cpu_percent"),
    "ram": lambda d: parse.parse_host_metric(d, "physical_memory_used"),
    "disk": lambda d: parse.parse_disk_percent(d),
    "hdfs": lambda d: parse.parse_hdfs_capacity(d),
    "network": lambda d: parse.parse_network_throughput(d),
}

FILE_TYPES = ["hosts", "cpu", "ram", "disk", "hdfs", "network", "services", "events"]

# Which files must be present for the core checks; services/events are optional
# (their checks report NO_DATA when absent, by design).
REQUIRED_TYPES = ["hosts", "cpu", "ram", "disk", "hdfs", "network"]
OPTIONAL_TYPES = ["services", "events"]


class ValidationError(Exception):
    pass


def tenant_dir(slug: str) -> Path:
    return UPLOAD_ROOT / slug


def _destination(slug: str, file_type: str, original_name: str) -> Path:
    base = tenant_dir(slug)
    if file_type == "hosts":
        # keep multiple host files, sanitised name
        safe = original_name.replace("/", "_").replace("\\", "_") or "host.json"
        return base / "hosts" / safe
    if file_type in _METRIC_CHECK:
        return base / "metrics" / f"{file_type}.json"
    if file_type in ("services", "events"):
        return base / f"{file_type}.json"
    raise ValidationError(f"Unknown file type '{file_type}'. Expected one of: {', '.join(FILE_TYPES)}")


def validate_bytes(file_type: str, raw: bytes) -> str:
    """Parse `raw` as the given CM export type. Returns a human 'what we found'
    summary on success; raises ValidationError with a clear reason otherwise."""
    if file_type not in FILE_TYPES:
        raise ValidationError(f"Unknown file type '{file_type}'.")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Not valid JSON: {exc}") from exc

    try:
        if file_type == "hosts":
            host = parse.parse_host_file(data)
            if not host.hostname:
                raise ValidationError("Host file has no hostname.")
            return f"Host '{host.hostname}' (health {host.health_summary})"

        if file_type in _METRIC_CHECK:
            series = _METRIC_CHECK[file_type](data)
            if not series:
                raise ValidationError(
                    f"No '{file_type}' time-series found — is this the right metric export?"
                )
            hosts = {s.entity_name for s in series}
            return f"{len(series)} series across {len(hosts)} host(s)"

        if file_type == "services":
            services = parse.parse_services(data, cluster_name="")
            if not services:
                raise ValidationError("No services found in this file.")
            return f"{len(services)} services"

        if file_type == "events":
            events = parse.parse_events(data, category=None, alert_only=True)
            return f"{len(events)} active alert event(s)"
    except ValidationError:
        raise
    except Exception as exc:  # any parser error -> a friendly validation failure
        raise ValidationError(f"Doesn't match the expected Cloudera {file_type} shape: {exc}") from exc

    raise ValidationError(f"Unhandled file type '{file_type}'.")


def store(slug: str, file_type: str, original_name: str, raw: bytes) -> Path:
    """Validate then write the file to its place in the tenant's export folder.
    Returns the stored path. Raises ValidationError on bad content."""
    validate_bytes(file_type, raw)  # never store something the checks can't read
    dest = _destination(slug, file_type, original_name)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw)
    return dest


def coverage(slug: str) -> dict:
    """Which expected files are present for this tenant — powers the upload
    checklist and the 'ready to monitor?' status."""
    base = tenant_dir(slug)
    present = {}
    present["hosts"] = (base / "hosts").is_dir() and any((base / "hosts").glob("*.json"))
    for t in _METRIC_CHECK:
        present[t] = (base / "metrics" / f"{t}.json").is_file()
    present["services"] = (base / "services.json").is_file()
    present["events"] = (base / "events.json").is_file()
    missing_required = [t for t in REQUIRED_TYPES if not present.get(t)]
    return {
        "present": present,
        "missing_required": missing_required,
        "ready": not missing_required,
    }
