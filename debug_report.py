"""Debug entry point — build one monitoring report, step by step.

This is the easiest way to understand the backend: it calls the SAME functions
the API uses, but directly (no HTTP, no async, no uvicorn), so you can press F11
("Step Into") and follow the whole flow in one process.

How to use in VS Code:
  1. Set breakpoints (F9) on the lines marked "STEP INTO" below, and in any
     check under checks/ or the data source under data_sources/.
  2. Run the "Debug: report (backend, step through checks)" configuration
     (Run and Debug panel, or F5).
  3. Use F10 (step over), F11 (step into), Shift+F11 (step out) to walk through.
     Hover over variables, or use the Variables / Watch panels, to inspect them.

Change TENANT_ID / AS_OF below to debug a different tenant or day.
"""

import logging
from datetime import date  # noqa: F401 — available for setting AS_OF below

from checks import run_all_checks
from config import load_tenant_config
from data_sources import choose_data_source

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

# --- what to debug -------------------------------------------------------
TENANT_ID = "bdaktprod"      # try "example-dev" for the synthetic all-breaches tenant
AS_OF: "date | None" = None  # e.g. date(2026, 7, 2) to view a specific day; None = latest
# -------------------------------------------------------------------------


def main() -> None:
    # 1. Load and validate the tenant's YAML config.
    tenant = load_tenant_config(f"config/tenants/{TENANT_ID}.yaml")  # STEP INTO
    print(f"Tenant: {tenant.tenant_id} | cluster: {tenant.cluster_name}")

    # 2. Build the data source (picks JsonDataSource / ClouderaExportSource /
    #    ClouderaApiSource based on data_source.type). This is where the two
    #    data paths diverge — step in to see which one is chosen.
    source = choose_data_source(tenant)  # STEP INTO

    # 3. For day-aware sources, pin the day (default to the latest available,
    #    like the dashboard does) and pick the heartbeat reference moment.
    now = None
    if hasattr(source, "as_of"):
        dates = source.available_dates()
        source.as_of = AS_OF or (dates[-1] if dates else None)
        if hasattr(source, "reference_now"):
            now = source.reference_now()
    print(f"Viewing day: {getattr(source, 'as_of', 'n/a')}")

    # 4. Run all nine checks. STEP INTO to walk each check reading the source
    #    and comparing against tenant.thresholds.
    report = run_all_checks(source, tenant, now=now)  # STEP INTO

    # 5. Inspect the result.
    print(f"\n{report.breach_count} breaches | {report.ok_count} OK | {report.no_data_count} no-data")
    for r in report.results:
        print(f"  {r.status:8} {r.task:18} {r.detail[:80]}")


if __name__ == "__main__":
    main()
