"""Cloudera Operations Center — the monitoring dashboard (API client).

This dashboard is a thin client: it talks to the FastAPI backend over HTTP and
renders what it returns. It contains no monitoring logic of its own — the checks
and the AI analysis all run in the API (see api/main.py). A separate frontend
could replace this dashboard by calling the exact same endpoints.

What it shows, top to bottom:
1. A live monitoring panel that re-fetches the report automatically (every N
   seconds) and shows each check as a healthy / breach / no-data card.
2. An on-demand AI analysis section: one button starts a background analysis job
   in the API and polls it until the report is ready.
"""

import os
import sys
import time
from datetime import date, datetime
from pathlib import Path

# When Streamlit runs this file directly, only dashboard/ is on the import path
# — add the project root so `styles` and the shared response models import.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
import streamlit as st
from dotenv import load_dotenv

import styles
from ai_analysis import AiReport            # shared response model (for rendering only)
from checks import HealthReport             # shared response model (for rendering only)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env", override=True)

# Where the FastAPI backend lives. Override with API_BASE_URL in .env if needed.
API_BASE = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")

# Display name + icon for each check.
CHECK_LABELS = {
    "host_health": ("Host Health", "🖥️"),
    "heartbeat": ("Heartbeat", "💓"),
    "cpu_percent": ("CPU Utilization", "⚙️"),
    "ram_percent": ("Memory Utilization", "🧠"),
    "disk_percent": ("Disk & Logs", "💾"),
    "hdfs_health": ("HDFS Capacity & Health", "🗄️"),
    "service_status": ("Service & Role Status", "🧩"),
    "alerts": ("Cluster Alerts", "🚨"),
    "network": ("Network & Connectivity", "🌐"),
}

st.set_page_config(page_title="Cloudera Operations Center", page_icon="🛰️", layout="wide")


# ---------- API client helpers ----------


class ApiError(Exception):
    """An API call failed. `detail` is the human-readable reason from the API."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"{status_code}: {detail}")


def _request(method: str, path: str, **kwargs) -> dict | list:
    try:
        resp = httpx.request(method, f"{API_BASE}{path}", timeout=30.0, **kwargs)
    except httpx.HTTPError as exc:
        raise ApiError(0, f"Could not reach the API at {API_BASE} — {exc}") from exc
    if resp.is_error:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        raise ApiError(resp.status_code, detail)
    return resp.json()


def api_list_tenants() -> list[dict]:
    return _request("GET", "/tenants")


def api_get_dates(tenant_id: str) -> list[date]:
    data = _request("GET", f"/tenants/{tenant_id}/dates")
    return [date.fromisoformat(d) for d in data["dates"]]


def api_get_report(tenant_id: str, as_of: date | None) -> HealthReport:
    params = {"as_of": as_of.isoformat()} if as_of else {}
    data = _request("GET", f"/tenants/{tenant_id}/report", params=params)
    return HealthReport.model_validate(data)


def api_start_analysis(tenant_id: str, as_of: date | None) -> str:
    params = {"as_of": as_of.isoformat()} if as_of else {}
    data = _request("POST", f"/tenants/{tenant_id}/analyze", params=params)
    return data["job_id"]


def api_poll_analysis(job_id: str) -> dict:
    return _request("GET", f"/analysis/{job_id}")


# ---------- rendering (identical to before; just fed by API data) ----------


def render_live_monitor(tenant_id: str, live_on: bool, interval: int, as_of: date | None) -> None:
    """Auto-refreshing panel: fetch the latest report from the API and show it."""
    try:
        report = api_get_report(tenant_id, as_of)
    except ApiError as exc:
        _render_source_error(tenant_id, exc)
        return

    st.session_state.health_report = report

    # "Last checked" is the real moment we just fetched (wall clock) — NOT the
    # data's own timestamp, which for a static export is days in the past and
    # would confusingly read as "checked days ago" right after a refresh.
    last_checked = datetime.now().strftime("%H:%M:%S")
    st.markdown(styles.live_line(last_checked, 0, live_on, interval), unsafe_allow_html=True)

    # For a static export the data is from a past capture, not live now — say so
    # plainly so nobody mistakes it for real-time. (Skipped for live/near-now data.)
    data_moment = report.timestamp
    age_hours = (datetime.now(data_moment.tzinfo) - data_moment).total_seconds() / 3600
    if age_hours > 12:
        st.caption(f"📅 Showing cluster data captured {data_moment.astimezone().strftime('%Y-%m-%d %H:%M')}")
    st.markdown(
        styles.overall_banner(report.has_breaches, report.breach_count, report.evaluated_count),
        unsafe_allow_html=True,
    )
    st.markdown(
        styles.kpi_row(report.evaluated_count, report.ok_count, report.breach_count, report.no_data_count),
        unsafe_allow_html=True,
    )
    st.markdown('<div class="section-title">Monitoring Checks</div>', unsafe_allow_html=True)
    st.markdown(styles.check_grid(report.results, CHECK_LABELS), unsafe_allow_html=True)


def _render_source_error(tenant_id: str, exc: ApiError) -> None:
    # 409 = the tenant's data source isn't usable yet (e.g. live API not wired up).
    if exc.status_code == 409:
        st.warning(
            "**This customer's data source isn't returning data yet.**\n\n"
            "If they're on the live Cloudera API, their cluster address/credentials "
            f"aren't set up. While they're still in the demo stage, keep their profile "
            "on a file-based source.",
            icon="⚠️",
        )
        with st.expander("Technical detail"):
            st.code(exc.detail)
    else:
        st.error(f"Could not load monitoring data: {exc.detail}")


def _view_key(tenant_id: str, as_of: date | None) -> str:
    """Identifies exactly what's on screen: this tenant + this day. AI reports
    are stored under this key so one day's analysis never shows under another."""
    return f"{tenant_id}|{as_of.isoformat() if as_of else 'latest'}"


def _breach_signature(report: HealthReport) -> str:
    """Same fingerprint the API computes — lets us detect when the breaches on
    screen have changed since an analysis was generated."""
    return "|".join(
        f"{r.task}:{','.join(sorted(r.breached_entities))}"
        for r in report.results
        if r.status == "BREACH"
    )


def render_ai_section(tenant_id: str, as_of: date | None) -> None:
    report: HealthReport | None = st.session_state.get("health_report")
    if report is None:
        return

    day_label = as_of.isoformat() if as_of else "the latest data"

    st.markdown("---")
    st.markdown(
        f'<div class="section-title">AI Incident Analysis '
        f'<span class="scope-chip">for {day_label}</span></div>',
        unsafe_allow_html=True,
    )

    if not report.has_breaches:
        st.success(f"No active issues on {day_label} — AI analysis only runs when problems are detected.")
        return

    # AI reports are kept per (tenant, day). Look up the one for exactly what's
    # on screen; a different day's analysis is simply never shown here.
    saved = st.session_state.setdefault("ai_reports", {})
    key = _view_key(tenant_id, as_of)
    entry = saved.get(key)

    st.caption(
        f"{report.breach_count} issue(s) detected on {day_label}. "
        "Run the AI analyst to connect them, rank severity, and recommend fixes."
    )

    button_label = "🧠 Run AI Analysis" if entry is None else "🔄 Re-run AI Analysis"
    if st.button(button_label, type="primary"):
        _run_and_poll_analysis(tenant_id, as_of, key)
        entry = saved.get(key)  # freshly stored (or still None on failure)

    if entry is None:
        return

    ai_report: AiReport = entry["report"]

    # If the breaches on screen changed since this analysis (e.g. live data
    # moved), say so clearly instead of silently showing an out-of-date report.
    if entry.get("breach_signature") != _breach_signature(report):
        st.warning(
            f"The detected issues changed since this analysis was generated "
            f"({entry.get('generated_at', '—')}). Re-run to analyze the current state.",
            icon="⚠️",
        )

    st.caption(
        f"Analysis for **{day_label}** · generated at {entry.get('generated_at', '—')} "
        f"in {entry.get('seconds', 0):.0f}s"
    )
    summary = ai_report.overall_summary
    if ai_report.priority_order:
        summary += "  —  Priority order: " + " → ".join(ai_report.priority_order)
    st.markdown(styles.ai_summary(summary), unsafe_allow_html=True)
    for finding in ai_report.findings:
        st.markdown(styles.finding_card(finding), unsafe_allow_html=True)


# Stop polling after this long so a stuck job can't freeze the page forever.
_MAX_ANALYSIS_WAIT_SEC = 20 * 60


def _run_and_poll_analysis(tenant_id: str, as_of: date | None, key: str) -> None:
    """Start a background analysis job in the API and poll until it finishes.
    The work runs in the API, so it survives even if this page is refreshed.
    On success the result is stored under `key` = (tenant, day)."""
    try:
        job_id = api_start_analysis(tenant_id, as_of)
    except ApiError as exc:
        st.error(f"Could not start AI analysis: {exc.detail}")
        return

    started = time.monotonic()
    with st.spinner("AI analyst connecting issues and drafting remediation… (this can take a few minutes)"):
        while True:
            if time.monotonic() - started > _MAX_ANALYSIS_WAIT_SEC:
                st.error("AI analysis is taking unusually long — please try again.")
                return
            time.sleep(3)
            try:
                job = api_poll_analysis(job_id)
            except ApiError as exc:
                st.error(f"Lost contact with the analysis job: {exc.detail}")
                return
            status = job["status"]
            if status == "done":
                st.session_state["ai_reports"][key] = {
                    "report": AiReport.model_validate(job["result"]),
                    "seconds": job.get("seconds") or 0,
                    "generated_at": datetime.now().strftime("%H:%M:%S"),
                    "breach_signature": job.get("breach_signature"),
                }
                return
            if status == "error":
                st.error(f"AI analysis failed: {job.get('error')}")
                return
            if status == "no_breaches":
                st.info("No breaches to analyze — the cluster is healthy.")
                return


def _source_label(kind: str) -> str:
    return {
        "json": "📄 JSON files (demo stage)",
        "export": "📄 Cloudera API exports",
        "api": "🌐 Live Cloudera API",
    }.get(kind, kind)


def main() -> None:
    st.markdown(styles.CSS, unsafe_allow_html=True)

    # ---- Fetch the tenant list from the API ----
    try:
        tenants = api_list_tenants()
    except ApiError as exc:
        st.error(
            f"Can't reach the monitoring API at `{API_BASE}`.\n\n{exc.detail}\n\n"
            "Start it with:  `uvicorn api.main:app --port 8000`"
        )
        return
    if not tenants:
        st.error("No tenants configured in config/tenants.")
        return

    by_id = {t["tenant_id"]: t for t in tenants}

    # ---- Sidebar ----
    st.sidebar.header("Controls")
    tenant_id = st.sidebar.selectbox(
        "Cluster / Tenant",
        list(by_id.keys()),
        format_func=lambda tid: f"{by_id[tid]['display_name']}  ·  {by_id[tid]['source_kind']}",
    )
    tenant = by_id[tenant_id]
    st.sidebar.markdown(f"**Data source:** {_source_label(tenant['source_kind'])}")

    live_on = st.sidebar.toggle("Live monitoring", value=True)
    interval = st.sidebar.selectbox(
        "Refresh interval", [5, 10, 30, 60], index=1, format_func=lambda s: f"{s} seconds",
        disabled=not live_on,
    )
    if st.sidebar.button("🔄 Refresh now", use_container_width=True):
        st.rerun()

    # ---- Date filter (only for sources that carry multiple days) ----
    as_of = None
    try:
        available = api_get_dates(tenant_id)
    except ApiError:
        available = []
    if available:
        st.sidebar.markdown("---")
        st.sidebar.markdown("**View day**")
        as_of = st.sidebar.date_input(
            "Show the cluster's state as of",
            value=available[-1], min_value=available[0], max_value=available[-1],
            help="The exports hold several days; pick a day to see that day's breaches.",
        )

    # ---- Header ----
    st.markdown(
        styles.header_bar(
            "Cloudera Operations Center",
            "Autonomous cluster monitoring & AI-assisted incident triage",
            tenant["cluster_name"],
            _source_label(tenant["source_kind"]),
        ),
        unsafe_allow_html=True,
    )

    # ---- Live monitoring (auto-refreshing fragment) ----
    run_every = f"{interval}s" if live_on else None
    monitor = st.fragment(run_every=run_every)(render_live_monitor)
    monitor(tenant_id, live_on, interval, as_of)

    # ---- AI analysis (on-demand, survives the auto-refresh) ----
    render_ai_section(tenant_id, as_of)


if __name__ == "__main__":
    main()
