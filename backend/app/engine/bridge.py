"""Turn a database Tenant into a live monitoring report.

Mapping from the product's `data_source_mode` to the engine's source kind:
    "json"  -> engine "export" source (real Cloudera Manager export files, which
               is exactly what admins upload) reading from the tenant's data_dir
    "api"   -> engine live ClouderaApiSource against the tenant's CM credentials

CM credentials live encrypted in the database. The engine's API source reads
them from environment variables (by name), so for api-mode tenants we decrypt
and place them in per-tenant env vars right before building the source — reusing
the engine untouched.
"""

import threading
from collections import defaultdict
from datetime import date, datetime
from typing import Optional

from config import (
    ClouderaConfig,
    CredentialsConfig,
    DataSourceConfig,
    TenantConfig,
    ThresholdsConfig,
)
from data_sources import DataSource, choose_data_source
from data_sources.select import DataSourceError

from ..core.crypto import decrypt
from ..db.models import Tenant

# Default per-check refresh cadence (seconds) — overridable per tenant in the DB.
# Fast-moving signals refresh often; heavy/slow ones (storage growth) rarely.
DEFAULT_REFRESH_RATES = {
    "host_health": 30,
    "heartbeat": 15,
    "cpu_percent": 15,
    "ram_percent": 15,
    "disk_percent": 60,
    "hdfs_health": 600,
    "service_status": 60,
    "alerts": 15,
    "network": 30,
}


def _thresholds(db_tenant: Tenant) -> ThresholdsConfig:
    """The tenant's stored thresholds, falling back to engine defaults for any
    field not set — so a half-configured tenant still runs."""
    stored = db_tenant.thresholds or {}
    return ThresholdsConfig(**stored)


def tenant_to_config(db_tenant: Tenant) -> TenantConfig:
    """Build the engine's TenantConfig from a database row."""
    if db_tenant.data_source_mode == "api":
        # Decrypt CM creds into per-tenant env vars the engine reads by name.
        import os

        user_env = f"CM_USER_{db_tenant.id}"
        pass_env = f"CM_PW_{db_tenant.id}"
        os.environ[user_env] = db_tenant.cm_username or ""
        os.environ[pass_env] = decrypt(db_tenant.cm_password_encrypted) if db_tenant.cm_password_encrypted else ""

        return TenantConfig(
            tenant_id=db_tenant.slug,
            display_name=db_tenant.display_name,
            cluster_name=db_tenant.cluster_name,
            data_source=DataSourceConfig(type="api"),
            cloudera=ClouderaConfig(
                cm_host=db_tenant.cm_host, port=db_tenant.cm_port, use_tls=db_tenant.cm_use_tls
            ),
            credentials=CredentialsConfig(username_env=user_env, password_env=pass_env),
            thresholds=_thresholds(db_tenant),
        )

    # json mode -> engine "export" source over the tenant's uploaded files
    return TenantConfig(
        tenant_id=db_tenant.slug,
        display_name=db_tenant.display_name,
        cluster_name=db_tenant.cluster_name,
        data_source=DataSourceConfig(type="export", data_dir=db_tenant.data_dir),
        thresholds=_thresholds(db_tenant),
    )


# --- source caching (built once, reused; export source re-reads changed files) ---
# Keyed by "slug:mode" so flipping a tenant's mode rebuilds. Each cached source
# has its own lock because setting `as_of` + running checks must be atomic.
_source_cache: dict[str, DataSource] = {}
_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)


def _cache_key(db_tenant: Tenant) -> str:
    return f"{db_tenant.slug}:{db_tenant.data_source_mode}"


def get_source(db_tenant: Tenant, fresh: bool = False) -> DataSource:
    """A ready DataSource for this tenant. `fresh=True` bypasses the cache (used
    by long-running work that must not be disturbed by dashboard refreshes)."""
    config = tenant_to_config(db_tenant)
    if fresh:
        return choose_data_source(config)
    key = _cache_key(db_tenant)
    if key not in _source_cache:
        _source_cache[key] = choose_data_source(config)
    return _source_cache[key]


def invalidate(db_tenant: Tenant) -> None:
    """Drop a tenant's cached source — call after re-uploading files or editing
    connection settings so the next report rebuilds it."""
    _source_cache.pop(_cache_key(db_tenant), None)


def available_dates(db_tenant: Tenant) -> list[date]:
    return get_source(db_tenant).available_dates()


def build_report(db_tenant: Tenant, as_of: Optional[date] = None):
    """Run all nine checks for this tenant as of an optional day. Raises
    DataSourceError if the tenant's data source isn't usable yet."""
    from checks import run_all_checks

    config = tenant_to_config(db_tenant)
    source = get_source(db_tenant)

    with _locks[_cache_key(db_tenant)]:
        now: Optional[datetime] = None
        if as_of is not None and hasattr(source, "as_of"):
            source.as_of = as_of
            if hasattr(source, "reference_now"):
                now = source.reference_now()
        elif hasattr(source, "as_of"):
            source.as_of = None
        return run_all_checks(source, config, now=now)


def build_single_check(db_tenant: Tenant, task: str, as_of: Optional[date] = None):
    """Run ONE check for this tenant — powers per-card refresh, so a fast card
    (alerts, 15s) doesn't force the slow ones (HDFS, 10min) to recompute."""
    from checks import ALL_CHECKS
    from checks.heartbeat import check_heartbeat

    by_task = {fn.__name__.replace("check_", ""): fn for fn in ALL_CHECKS}
    fn = by_task.get(task)
    if fn is None:
        raise KeyError(task)

    config = tenant_to_config(db_tenant)
    source = get_source(db_tenant)
    with _locks[_cache_key(db_tenant)]:
        now: Optional[datetime] = None
        if hasattr(source, "as_of"):
            source.as_of = as_of
            if as_of is not None and hasattr(source, "reference_now"):
                now = source.reference_now()
        if fn is check_heartbeat:
            return check_heartbeat(source, config, now=now)
        return fn(source, config)


def refresh_rates_for(db_tenant: Tenant) -> dict:
    """Per-check refresh seconds: stored overrides merged onto the defaults."""
    return {**DEFAULT_REFRESH_RATES, **(db_tenant.refresh_rates or {})}


__all__ = [
    "DataSourceError",
    "DEFAULT_REFRESH_RATES",
    "tenant_to_config",
    "get_source",
    "invalidate",
    "available_dates",
    "build_report",
    "refresh_rates_for",
]
