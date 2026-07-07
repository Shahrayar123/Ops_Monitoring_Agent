"""Picks which data source to use for a tenant.

The normal rule (production): each tenant's YAML says where its data comes
from, via data_source.type —

    type: json  -> JsonDataSource     (customer gave us JSON files; demo stage)
    type: api   -> ClouderaApiSource  (customer approved; live API credentials)

This matches the onboarding flow: a new customer first hands over JSON data for
the demo, and after approval their profile is switched to the live API by
editing one line in their YAML — no code changes.

Optional override (dev/testing): setting USE_JSON in .env forces EVERY tenant
to one source kind for this process —

    USE_JSON=true   -> force JSON files for all tenants
    USE_JSON=false  -> force the live API for all tenants
    (unset/empty)   -> no override; each tenant's own type applies

Every failure raises DataSourceError with a message that says what's wrong and
how to fix it — never a raw traceback.
"""

import logging
import os

import httpx

from cloudera import ClouderaApiError
from config import TenantConfig, load_tenant_secrets, secrets_file_for

log = logging.getLogger(__name__)

from .api_source import ClouderaApiSource, MissingEnvVarError
from .base import DataSource
from .export_source import ClouderaExportSource
from .json_source import JsonDataSource


class DataSourceError(Exception):
    """The data source could not be set up. The message explains why and what
    to do about it."""


def forced_source_kind() -> str | None:
    """Returns "json" or "api" when USE_JSON is set in the environment,
    or None when it isn't (meaning: each tenant's own type applies)."""
    value = os.environ.get("USE_JSON", "").strip().lower()
    if value == "":
        return None
    return "json" if value in {"1", "true", "yes"} else "api"


def source_kind_for(tenant: TenantConfig) -> str:
    """The data source kind this tenant will actually get ("json", "export" or
    "api"), taking the optional USE_JSON override into account. The override
    only forces the file-vs-live choice; a file-based tenant keeps its own
    on-disk layout (json vs export)."""
    override = forced_source_kind()
    if override == "json":
        # Force file mode, but respect whether the tenant uses the export layout.
        return "export" if tenant.data_source.type == "export" else "json"
    if override == "api":
        return "api"
    return tenant.data_source.type


def choose_data_source(tenant: TenantConfig) -> DataSource:
    kind = source_kind_for(tenant)
    override = forced_source_kind()
    label = {"json": "JSON files", "export": "Cloudera API exports", "api": "live Cloudera API"}[kind]
    log.info(
        "Tenant '%s': using %s data source%s",
        tenant.tenant_id, label, f" (forced by USE_JSON={override})" if override else "",
    )
    try:
        if kind == "json":
            return _json_source(tenant)
        if kind == "export":
            return _export_source(tenant)
        return _api_source(tenant)
    except DataSourceError as exc:
        log.error("Tenant '%s': data source setup failed — %s", tenant.tenant_id, exc)
        raise


def _export_source(tenant: TenantConfig) -> "ClouderaExportSource":
    if not tenant.data_source.data_dir:
        raise DataSourceError(
            f"Tenant '{tenant.tenant_id}' should read Cloudera API exports but has no "
            f"data folder set (data_source.data_dir in its YAML profile)."
        )
    try:
        return ClouderaExportSource(tenant.data_source.data_dir)
    except FileNotFoundError as exc:
        raise DataSourceError(f"Tenant '{tenant.tenant_id}': export folder problem — {exc}") from exc


def _json_source(tenant: TenantConfig) -> JsonDataSource:
    if not tenant.data_source.data_dir:
        raise DataSourceError(
            f"Tenant '{tenant.tenant_id}' should read JSON files but has no data folder "
            f"set (data_source.data_dir in its YAML profile). If USE_JSON=true is set in "
            f".env, it forces JSON mode even for live-API tenants — unset it to let this "
            f"tenant use its own configured source."
        )
    try:
        return JsonDataSource(tenant.data_source.data_dir)
    except FileNotFoundError as exc:
        raise DataSourceError(f"Tenant '{tenant.tenant_id}': data file missing — {exc}") from exc


def _api_source(tenant: TenantConfig) -> ClouderaApiSource:
    if tenant.cloudera is None or tenant.credentials is None:
        raise DataSourceError(
            f"Tenant '{tenant.tenant_id}' should use the live Cloudera API but has no "
            f"cloudera/credentials settings in its YAML profile. If USE_JSON=false is set "
            f"in .env, it forces API mode even for JSON-stage tenants — unset it to let "
            f"this tenant use its own configured source."
        )

    # This customer's credentials live in their own file: secrets/<tenant_id>.env
    load_tenant_secrets(tenant.tenant_id)

    try:
        source = ClouderaApiSource(tenant)
    except MissingEnvVarError as exc:
        raise DataSourceError(
            f"Tenant '{tenant.tenant_id}': {exc} Put it in this customer's secrets file "
            f"({secrets_file_for(tenant.tenant_id)}) before using the live API."
        ) from exc

    # Try one cheap API call now, so a connection problem shows up immediately
    # with a clear message instead of failing later mid-check.
    try:
        source.check_connection()
    except ClouderaApiError as exc:
        raise DataSourceError(
            f"Tenant '{tenant.tenant_id}': the Cloudera Manager API returned an error — {exc}"
        ) from exc
    except httpx.ConnectError as exc:
        raise DataSourceError(
            f"Tenant '{tenant.tenant_id}': could not reach Cloudera Manager at "
            f"{tenant.cloudera.cm_host}:{tenant.cloudera.port} — {exc}. "
            f"If this customer hasn't provided live API access yet, keep their profile "
            f"on data_source.type: json (or set USE_JSON=true in .env) to use their "
            f"JSON files instead."
        ) from exc
    except httpx.TimeoutException as exc:
        raise DataSourceError(
            f"Tenant '{tenant.tenant_id}': timed out reaching Cloudera Manager at "
            f"{tenant.cloudera.cm_host}:{tenant.cloudera.port} — {exc}"
        ) from exc
    except httpx.HTTPError as exc:
        raise DataSourceError(
            f"Tenant '{tenant.tenant_id}': HTTP error reaching Cloudera Manager — {exc}"
        ) from exc

    return source
