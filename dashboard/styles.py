"""Custom CSS + small HTML render helpers for the dashboard, kept out of app.py
so the page logic stays readable."""

import html

CSS = """
<style>
/* --- layout / chrome --- */
.block-container { padding-top: 1.5rem; padding-bottom: 3rem; max-width: 1500px; }
#MainMenu, footer { visibility: hidden; }

/* --- product header --- */
.app-header {
  background: linear-gradient(135deg, #1e3a8a 0%, #2563eb 100%);
  border-radius: 16px; padding: 22px 28px; margin-bottom: 22px;
  color: #fff; box-shadow: 0 10px 25px -12px rgba(37,99,235,.6);
  display: flex; align-items: center; justify-content: space-between; gap: 20px;
}
.app-header .title { font-size: 26px; font-weight: 700; letter-spacing: -.02em; margin: 0; }
.app-header .subtitle { font-size: 13.5px; opacity: .85; margin-top: 3px; }
.app-header .cluster-chip {
  background: rgba(255,255,255,.15); border: 1px solid rgba(255,255,255,.25);
  padding: 8px 14px; border-radius: 10px; font-size: 13px; text-align: right; white-space: nowrap;
}
.app-header .cluster-chip b { font-size: 15px; }

/* --- live status line --- */
.live-line { display:flex; align-items:center; gap:10px; margin: 2px 0 14px; font-size: 13.5px; color:#475569; }
.live-dot { width:10px; height:10px; border-radius:50%; background:#22c55e; box-shadow:0 0 0 rgba(34,197,94,.7); animation: pulse 1.8s infinite; }
.live-dot.paused { background:#94a3b8; animation:none; }
@keyframes pulse { 0%{box-shadow:0 0 0 0 rgba(34,197,94,.6);} 70%{box-shadow:0 0 0 8px rgba(34,197,94,0);} 100%{box-shadow:0 0 0 0 rgba(34,197,94,0);} }

/* --- overall banner --- */
.banner { border-radius: 14px; padding: 18px 22px; margin-bottom: 18px; display:flex; align-items:center; gap:16px; }
.banner .b-icon { font-size: 30px; }
.banner .b-title { font-size: 19px; font-weight: 700; margin:0; }
.banner .b-sub { font-size: 13.5px; margin-top:2px; opacity:.9; }
.banner.ok    { background:#f0fdf4; border:1px solid #bbf7d0; color:#166534; }
.banner.breach{ background:#fef2f2; border:1px solid #fecaca; color:#991b1b; }

/* --- KPI cards --- */
.kpi-grid { display:grid; grid-template-columns: repeat(4, 1fr); gap:14px; margin-bottom:22px; }
.kpi { background:#fff; border:1px solid #e2e8f0; border-radius:14px; padding:16px 18px; box-shadow:0 1px 3px rgba(15,23,42,.05); }
.kpi .k-label { font-size:12px; font-weight:600; text-transform:uppercase; letter-spacing:.04em; color:#64748b; }
.kpi .k-value { font-size:30px; font-weight:750; margin-top:6px; line-height:1; }
.kpi .k-value.green { color:#16a34a; } .kpi .k-value.red { color:#dc2626; } .kpi .k-value.blue { color:#2563eb; } .kpi .k-value.slate { color:#0f172a; }
.kpi .k-foot { font-size:12px; color:#94a3b8; margin-top:6px; }

/* --- check cards grid --- */
.section-title { font-size:15px; font-weight:700; color:#0f172a; margin: 6px 0 12px; text-transform:uppercase; letter-spacing:.03em; }
.scope-chip { display:inline-block; margin-left:8px; padding:2px 10px; border-radius:20px;
  background:#eff6ff; color:#1e40af; font-size:11px; font-weight:700; text-transform:none;
  letter-spacing:0; vertical-align:middle; }
.check-grid { display:grid; grid-template-columns: repeat(3, 1fr); gap:14px; }
.check-card { background:#fff; border:1px solid #e2e8f0; border-left-width:4px; border-radius:12px; padding:14px 16px; box-shadow:0 1px 3px rgba(15,23,42,.05); }
.check-card.ok { border-left-color:#22c55e; }
.check-card.breach { border-left-color:#ef4444; }
.check-card.nodata { border-left-color:#cbd5e1; opacity:.75; }
.check-head { display:flex; align-items:center; gap:9px; }
.check-icon { font-size:17px; }
.check-name { font-weight:650; font-size:14.5px; color:#0f172a; flex:1; }
.badge { font-size:11px; font-weight:700; padding:3px 9px; border-radius:20px; letter-spacing:.03em; }
.badge.ok { background:#dcfce7; color:#15803d; }
.badge.breach { background:#fee2e2; color:#b91c1c; }
.badge.nodata { background:#f1f5f9; color:#64748b; }
.check-detail { font-size:12.5px; color:#64748b; margin-top:9px; line-height:1.45; }

/* --- AI findings --- */
.finding { background:#fff; border:1px solid #e2e8f0; border-radius:12px; padding:14px 16px; margin-bottom:12px; box-shadow:0 1px 3px rgba(15,23,42,.05); }
.finding-head { display:flex; align-items:center; gap:10px; margin-bottom:8px; }
.finding-title { font-weight:700; font-size:15px; color:#0f172a; flex:1; }
.sev { font-size:11px; font-weight:800; padding:3px 10px; border-radius:6px; color:#fff; letter-spacing:.04em; }
.sev.CRITICAL { background:#7f1d1d; } .sev.HIGH { background:#dc2626; } .sev.MEDIUM { background:#d97706; } .sev.LOW { background:#2563eb; }
.finding-row { font-size:13px; color:#334155; margin-top:6px; }
.finding-row b { color:#0f172a; }
.rel-tag { display:inline-block; background:#f1f5f9; color:#475569; font-size:11px; padding:2px 8px; border-radius:6px; margin:2px 4px 2px 0; }
.ai-summary { background:#eff6ff; border:1px solid #bfdbfe; border-radius:12px; padding:16px 18px; margin-bottom:16px; font-size:14px; color:#1e3a8a; line-height:1.5; }
</style>
"""


def _esc(text: str) -> str:
    return html.escape(str(text))


def header_bar(product: str, subtitle: str, cluster: str, source_label: str) -> str:
    return f"""
    <div class="app-header">
      <div>
        <p class="title">{_esc(product)}</p>
        <div class="subtitle">{_esc(subtitle)}</div>
      </div>
      <div class="cluster-chip">
        <b>{_esc(cluster)}</b><br/>{_esc(source_label)}
      </div>
    </div>
    """


def live_line(last_updated: str, seconds_ago: int, live_on: bool, interval: int | None) -> str:
    dot = "live-dot" if live_on else "live-dot paused"
    if live_on:
        state = f"Live monitoring · auto-refresh every {interval}s"
    else:
        state = "Live monitoring paused"
    return (
        f'<div class="live-line"><span class="{dot}"></span>'
        f"<span>{state} &nbsp;·&nbsp; Last checked {_esc(last_updated)}</span></div>"
    )


def overall_banner(has_breaches: bool, breach_count: int, evaluated: int) -> str:
    if not has_breaches:
        return (
            '<div class="banner ok"><span class="b-icon">✅</span>'
            '<div><p class="b-title">All systems operational</p>'
            f'<div class="b-sub">All {evaluated} evaluated checks are within thresholds.</div></div></div>'
        )
    return (
        '<div class="banner breach"><span class="b-icon">⚠️</span>'
        f'<div><p class="b-title">{breach_count} issue{"s" if breach_count != 1 else ""} detected</p>'
        f'<div class="b-sub">{breach_count} of {evaluated} evaluated checks are breaching configured thresholds and need attention.</div></div></div>'
    )


def kpi_row(evaluated: int, passing: int, breached: int, no_data: int = 0) -> str:
    # Health % is over the checks that actually ran (NO_DATA ones are excluded).
    health = round(passing / evaluated * 100) if evaluated else 0
    health_cls = "green" if health == 100 else ("red" if health < 60 else "blue")
    no_data_foot = f"{no_data} awaiting data" if no_data else "all checks have data"
    return f"""
    <div class="kpi-grid">
      <div class="kpi"><div class="k-label">Cluster Health</div>
        <div class="k-value {health_cls}">{health}%</div>
        <div class="k-foot">{passing}/{evaluated} evaluated passing</div></div>
      <div class="kpi"><div class="k-label">Checks Run</div>
        <div class="k-value slate">{evaluated}</div>
        <div class="k-foot">{no_data_foot}</div></div>
      <div class="kpi"><div class="k-label">Passing</div>
        <div class="k-value green">{passing}</div>
        <div class="k-foot">within thresholds</div></div>
      <div class="kpi"><div class="k-label">Issues</div>
        <div class="k-value {'red' if breached else 'green'}">{breached}</div>
        <div class="k-foot">need attention</div></div>
    </div>
    """


def check_grid(results, task_meta) -> str:
    cards = []
    for r in results:
        name, icon = task_meta.get(r.task, (r.task, "•"))
        if r.status == "BREACH":
            cls, label = "breach", "BREACH"
        elif r.status == "NO_DATA":
            cls, label = "nodata", "NO DATA"
        else:
            cls, label = "ok", "HEALTHY"
        cards.append(
            f'<div class="check-card {cls}"><div class="check-head">'
            f'<span class="check-icon">{icon}</span>'
            f'<span class="check-name">{_esc(name)}</span>'
            f'<span class="badge {cls}">{label}</span></div>'
            f'<div class="check-detail">{_esc(r.detail)}</div></div>'
        )
    return f'<div class="check-grid">{"".join(cards)}</div>'


def ai_summary(text: str) -> str:
    return f'<div class="ai-summary">{_esc(text)}</div>'


def finding_card(f) -> str:
    rels = "".join(f'<span class="rel-tag">{_esc(t)}</span>' for t in f.related_tasks) or "—"
    return (
        f'<div class="finding"><div class="finding-head">'
        f'<span class="finding-title">{_esc(f.primary_task)}</span>'
        f'<span class="sev {_esc(f.severity)}">{_esc(f.severity)}</span></div>'
        f'<div class="finding-row">{_esc(f.summary)}</div>'
        f'<div class="finding-row"><b>Recommended remediation:</b> {_esc(f.recommended_remediation)}</div>'
        f'<div class="finding-row"><b>Related:</b> {rels}</div></div>'
    )
