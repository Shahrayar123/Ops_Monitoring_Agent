"""Standalone data-inspection tool — for UNDERSTANDING and CROSS-CHECKING only.

This does NOT touch the monitoring pipeline. It loads the SAME data the checks
read (via the same data source), then lays every check's underlying values out
as a table: the raw value, the threshold, and the verdict (OK / BREACH). So for
any breach on the dashboard, you can see exactly which row in the data caused it.

It prints the tables to the console AND writes one CSV per check into
`data_inspection/` so you can open them in Excel.

Run it:  python inspect_data.py
Change TENANT_ID / AS_OF below to inspect a different tenant or day.

--------------------------------------------------------------------------------
IMPORTANT — why some checks look the same on every date:

Only the time-series METRICS vary by day: cpu, ram, disk, network, and HDFS
*growth*. Those come from metrics/*.json and are filtered to the chosen day.

Host health, the HDFS *health verdict*, service status, and alerts come from
SNAPSHOT files (the host resource files, services.json, events.json). A snapshot
has no per-day history, so those four look the same whatever date you pick.

That's why on 2026-06-25 the four breaches are Host Health, HDFS Health,
Service Status, and Cluster Alerts — all snapshot-based. The metric checks
(cpu/ram/disk/network/heartbeat) are within limits that day.
--------------------------------------------------------------------------------
"""

import csv
import logging
from datetime import date, datetime, timezone
from pathlib import Path

from config import load_tenant_config
from data_sources import choose_data_source

logging.disable(logging.CRITICAL)  # keep the pipeline's logs quiet here

# --- what to inspect -----------------------------------------------------
TENANT_ID = "bdaktprod"
AS_OF = date(2026, 6, 25)
OUT_DIR = Path("data_inspection")
# -------------------------------------------------------------------------


def verdict(is_breach: bool) -> str:
    return "BREACH" if is_breach else "OK"


# ---- one function per check: returns (title, headers, rows) --------------


def host_health_table(source, tenant):
    rows = []
    for h in source.get_hosts():
        bad = h.health_summary != "GOOD"
        rows.append([h.hostname, h.health_summary, "GOOD", verdict(bad)])
    return "1. Host Health", ["host", "healthSummary", "expected", "verdict"], rows


def heartbeat_table(source, tenant, now):
    window = tenant.thresholds.heartbeat_window_sec
    rows = []
    for h in source.get_hosts():
        age = (now - h.last_heartbeat).total_seconds()
        rows.append([
            h.hostname, h.last_heartbeat.isoformat(), f"{age:.0f}", window, verdict(age > window)
        ])
    return "2. Heartbeat", ["host", "last_heartbeat", "age_sec", "window_sec", "verdict"], rows


def cpu_table(source, tenant):
    limit = tenant.thresholds.cpu_pct
    rows = []
    for s in source.get_metrics(["cpu_percent"]):
        if not s.points:
            continue
        v = s.points[-1].value
        rows.append([s.entity_name, f"{v:.1f}", limit, verdict(v > limit)])
    return "3. CPU Utilization", ["host", "cpu_%", "limit_%", "verdict"], rows


def ram_table(source, tenant):
    limit = tenant.thresholds.ram_pct
    series = source.get_metrics(["physical_memory_used", "physical_memory_total"])
    used = {s.entity_name: s.points[-1].value for s in series if s.metric_name == "physical_memory_used" and s.points}
    total = {s.entity_name: s.points[-1].value for s in series if s.metric_name == "physical_memory_total" and s.points}
    rows = []
    for host in sorted(used):
        if host in total and total[host] > 0:
            pct = used[host] / total[host] * 100
            rows.append([host, f"{used[host]/1e9:.1f}", f"{total[host]/1e9:.1f}", f"{pct:.1f}", limit, verdict(pct > limit)])
    return "4. Memory Utilization", ["host", "used_GB", "total_GB", "used_%", "limit_%", "verdict"], rows


def disk_table(source, tenant):
    limit = tenant.thresholds.disk_pct
    watched = set(tenant.thresholds.disk_mounts)
    rows = []
    for s in source.get_metrics(["fs_bytes_used_percent"]):
        mount = s.attributes.get("mount_point")
        if not s.points or mount not in watched:
            continue
        v = s.points[-1].value
        rows.append([s.entity_name, mount, f"{v:.1f}", limit, verdict(v > limit)])
    rows.sort(key=lambda r: (r[0], r[1]))
    return "5. Disk Utilization (watched mounts)", ["host", "mount", "used_%", "limit_%", "verdict"], rows


def hdfs_table(source, tenant):
    """Two parts: the CM health verdict (snapshot) and the storage growth (metric)."""
    rows = []
    services = source.get_services(tenant.cluster_name)
    hdfs = next((s for s in services if s.name == "hdfs"), None)
    if hdfs is None:
        rows.append(["service verdict", "hdfs", "NOT FOUND", "-", "BREACH"])
    else:
        rows.append(["service verdict", "hdfs healthSummary", hdfs.health_summary, "GOOD", verdict(hdfs.health_summary != "GOOD")])
        for hc in hdfs.health_checks:
            if hc.summary != "GOOD":
                rows.append(["service check", hc.name, hc.summary, "GOOD", "BREACH"])

    growth_limit = tenant.thresholds.hdfs_growth_pct_threshold
    series = source.get_metrics(["dfs_capacity_used"])
    if series and len(series[0].points) >= 2:
        pts = sorted(series[0].points, key=lambda p: p.timestamp)
        first, last = pts[0].value, pts[-1].value
        g = (last - first) / first * 100 if first else 0.0
        rows.append(["growth", f"{first/1e12:.1f}TB -> {last/1e12:.1f}TB", f"{g:.2f}%", f"{growth_limit}%", verdict(g > growth_limit)])
    else:
        rows.append(["growth", "no dfs_capacity_used data for this day", "-", f"{growth_limit}%", "n/a"])
    return "6. HDFS Capacity & Health", ["part", "what", "value", "expected", "verdict"], rows


def service_status_table(source, tenant):
    rows = []
    for svc in source.get_services(tenant.cluster_name):
        state_bad = svc.service_state not in ("STARTED", "NA")
        summary_bad = svc.health_summary in ("CONCERNING", "BAD")
        bad_checks = [hc.name for hc in svc.health_checks if hc.summary in ("CONCERNING", "BAD")]
        breach = state_bad or summary_bad or bool(bad_checks)
        rows.append([
            svc.name, svc.service_state, svc.health_summary,
            ", ".join(bad_checks) if bad_checks else "-", verdict(breach),
        ])
    return "7. Service & Role Status", ["service", "state", "healthSummary", "concerning/bad checks", "verdict"], rows


def alerts_table(source, tenant):
    rows = []
    for e in source.get_events(alert_only=True):
        serious = e.severity in ("CRITICAL", "IMPORTANT")
        summary = (e.attributes.get("ALERT_SUMMARY") or [e.content])[0]
        rows.append([e.id[:8], e.severity, summary[:80], verdict(serious)])
    rows.sort(key=lambda r: (r[1] != "CRITICAL", r[1] != "IMPORTANT"))
    return "8. Cluster Alerts (active)", ["event_id", "severity", "summary", "counts_as_breach"], rows


def network_table(source, tenant):
    rows = []
    for s in source.get_metrics(["total_bytes_receive_rate_across_network_interfaces"]):
        if not s.points:
            continue
        v = s.points[-1].value
        rows.append([s.entity_name, f"{v:.1f}", "> 1.0", verdict(v < 1.0)])
    return "9. Network & Connectivity", ["host", "receive_B/s", "expected", "verdict"], rows


# ---- output helpers -----------------------------------------------------


def print_table(title, headers, rows):
    print(f"\n{'='*90}\n{title}   ({len(rows)} rows)\n{'='*90}")
    if not rows:
        print("  (no data)")
        return
    widths = [max(len(str(h)), *(len(str(r[i])) for r in rows)) for i, h in enumerate(headers)]
    line = "  " + " | ".join(str(h).ljust(widths[i]) for i, h in enumerate(headers))
    print(line)
    print("  " + "-+-".join("-" * w for w in widths))
    for r in rows:
        marker = " <" if (str(r[-1]) == "BREACH") else ""
        print("  " + " | ".join(str(c).ljust(widths[i]) for i, c in enumerate(r)) + marker)


def write_csv(title, headers, rows):
    OUT_DIR.mkdir(exist_ok=True)
    name = title.split(".", 1)[0].strip() + "_" + title.split(".", 1)[1].strip().split("(")[0].strip()
    name = name.replace(" ", "_").replace("&", "and").replace("/", "-").lower()
    path = OUT_DIR / f"{name}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(headers)
        w.writerows(rows)


def main():
    tenant = load_tenant_config(f"config/tenants/{TENANT_ID}.yaml")
    source = choose_data_source(tenant)
    if hasattr(source, "as_of"):
        source.as_of = AS_OF
    now = source.reference_now() if hasattr(source, "reference_now") else datetime.now(timezone.utc)

    print(f"\nTenant: {tenant.tenant_id}  |  cluster: {tenant.cluster_name}  |  viewing day: {AS_OF}")
    print(f"Thresholds: cpu={tenant.thresholds.cpu_pct}%  ram={tenant.thresholds.ram_pct}%  "
          f"disk={tenant.thresholds.disk_pct}%  heartbeat={tenant.thresholds.heartbeat_window_sec}s")

    tables = [
        host_health_table(source, tenant),
        heartbeat_table(source, tenant, now),
        cpu_table(source, tenant),
        ram_table(source, tenant),
        disk_table(source, tenant),
        hdfs_table(source, tenant),
        service_status_table(source, tenant),
        alerts_table(source, tenant),
        network_table(source, tenant),
    ]

    breaching = []
    for title, headers, rows in tables:
        print_table(title, headers, rows)
        write_csv(title, headers, rows)
        if any(str(r[-1]) == "BREACH" for r in rows):
            breaching.append(title)

    print(f"\n{'='*90}")
    print(f"CHECKS WITH AT LEAST ONE BREACH ({len(breaching)}): " + " | ".join(breaching))
    print(f"CSV files written to: {OUT_DIR.resolve()}")
    print("=" * 90)


if __name__ == "__main__":
    main()
