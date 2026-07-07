"""Bridges the HTTP API to the existing backend.

Every function here just calls the same framework-agnostic code the Streamlit
dashboard used to call directly (choose_data_source, run_all_checks, ...). The
API layer adds no monitoring logic of its own — it only exposes what already
exists over HTTP.

Thread-safety note: a data source that carries an `as_of` day (the export
source) holds that day as mutable state. Two requests running at once (e.g. the
dashboard's auto-refresh and a date change) must not clobber each other's day,
so build_report() holds a per-tenant lock while it sets the day and runs the
checks. The AI job deliberately uses its OWN fresh source (see build_fresh_source)
so a minutes-long analysis can't be disturbed by report requests in between.
"""

import threading
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from checks import HealthReport, run_all_checks
from config import TenantConfig, load_tenant_configs_from_dir
from data_sources import DataSource, choose_data_source
from data_sources.select import source_kind_for

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TENANTS_DIR = PROJECT_ROOT / "config" / "tenants"


class TenantNotFound(Exception):
    pass


def list_tenants() -> list[TenantConfig]:
    return list(load_tenant_configs_from_dir(TENANTS_DIR).values())


def get_tenant(tenant_id: str) -> TenantConfig:
    tenants = load_tenant_configs_from_dir(TENANTS_DIR)
    if tenant_id not in tenants:
        raise TenantNotFound(f"No tenant named '{tenant_id}'")
    return tenants[tenant_id]


def tenant_summary(tenant: TenantConfig) -> dict:
    return {
        "tenant_id": tenant.tenant_id,
        "display_name": tenant.display_name,
        "cluster_name": tenant.cluster_name,
        "source_kind": source_kind_for(tenant),
    }


# Shared data sources are cached across requests (the export source re-reads its
# files only when they change on disk, so this stays live and fast). Each cached
# source has its own lock, since setting `as_of` + running checks must be atomic.
_source_cache: dict[str, DataSource] = {}
_source_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)


def _cache_key(tenant: TenantConfig) -> str:
    return f"{tenant.tenant_id}:{source_kind_for(tenant)}"


def get_source(tenant_id: str) -> DataSource:
    tenant = get_tenant(tenant_id)
    key = _cache_key(tenant)
    if key not in _source_cache:
        _source_cache[key] = choose_data_source(tenant)
    return _source_cache[key]


def build_fresh_source(tenant_id: str) -> DataSource:
    """A brand-new, uncached data source — used by the AI job so its minutes-long
    run has a source all to itself that report requests can't disturb."""
    return choose_data_source(get_tenant(tenant_id))


def clear_source_cache() -> None:
    _source_cache.clear()


def available_dates(tenant_id: str) -> list[date]:
    return get_source(tenant_id).available_dates()


def _apply_day(source: DataSource, as_of: Optional[date]) -> Optional[datetime]:
    """Point a day-aware source at `as_of` and return the 'now' to judge
    heartbeats against (the export's capture moment). No-op for sources that
    don't carry a day."""
    if as_of is not None and hasattr(source, "as_of"):
        source.as_of = as_of
        if hasattr(source, "reference_now"):
            return source.reference_now()
    return None


def build_report(tenant_id: str, as_of: Optional[date] = None) -> HealthReport:
    tenant = get_tenant(tenant_id)
    source = get_source(tenant_id)

    # Atomically: set the day, then run the checks, so a concurrent request for
    # a different day can't change the day out from under us mid-run.
    with _source_locks[_cache_key(tenant)]:
        now = _apply_day(source, as_of)
        return run_all_checks(source, tenant, now=now)


def build_report_on(source: DataSource, tenant: TenantConfig, as_of: Optional[date]) -> HealthReport:
    """Run the checks against a specific (caller-owned) source — used by the AI
    job, which owns its source and needs no locking."""
    now = _apply_day(source, as_of)
    return run_all_checks(source, tenant, now=now)
