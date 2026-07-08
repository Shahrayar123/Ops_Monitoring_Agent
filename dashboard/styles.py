"""Custom CSS + small HTML render helpers for the dashboard, kept out of app.py
so the page logic stays readable."""

import base64
import html
import mimetypes
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_logo_data_uri() -> str | None:
    """Read the company logo and return it as a base64 data URI (so it embeds
    directly in the header HTML — no static-file serving needed). Returns None
    if no logo file is present, in which case the header falls back to an emoji."""
    logo_dir = _PROJECT_ROOT / "Logo"
    if not logo_dir.is_dir():
        return None
    for candidate in sorted(logo_dir.glob("*")):
        if candidate.suffix.lower() in (".png", ".jpg", ".jpeg", ".svg", ".webp"):
            mime = mimetypes.guess_type(candidate.name)[0] or "image/png"
            data = base64.b64encode(candidate.read_bytes()).decode("ascii")
            return f"data:{mime};base64,{data}"
    return None


LOGO_DATA_URI = _load_logo_data_uri()

CSS = """
<style>
:root {
  --ink: #0f172a; --muted: #64748b; --faint: #94a3b8;
  --line: #e6eaf0; --card: #ffffff; --page: #f4f6fb;
  --brand: #4f46e5; --brand-2: #2563eb;
  --shadow: 0 1px 2px rgba(15,23,42,.04), 0 4px 16px -8px rgba(15,23,42,.10);
  --shadow-lg: 0 12px 30px -14px rgba(37,99,235,.45);
}

/* --- global page feel --- */
html, body, [data-testid="stAppViewContainer"] {
  font-family: "Inter", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
}
[data-testid="stAppViewContainer"] { background: var(--page); }
/* Extra top padding so the app header never sits under Streamlit's top toolbar
   / sidebar-collapse control — fixes the title being clipped when the sidebar
   is collapsed. */
.block-container { padding-top: 3.4rem; padding-bottom: 3rem; max-width: 1480px; }
#MainMenu, footer { visibility: hidden; }
[data-testid="stHeader"] { background: transparent; }

/* --- sidebar --- */
[data-testid="stSidebar"] { background: #ffffff; border-right: 1px solid var(--line); }
[data-testid="stSidebar"] .stButton button { border-radius: 10px; font-weight: 600; }

/* --- product header --- */
.app-header {
  position: relative; overflow: hidden;
  background: linear-gradient(120deg, #312e81 0%, #4f46e5 55%, #2563eb 100%);
  border-radius: 18px; padding: 24px 30px; margin-bottom: 22px;
  color: #fff; box-shadow: var(--shadow-lg);
  display: flex; align-items: center; justify-content: space-between; gap: 20px;
}
.app-header::after {  /* subtle glow accent */
  content:""; position:absolute; top:-40%; right:-5%; width:320px; height:320px;
  background: radial-gradient(circle, rgba(255,255,255,.16), transparent 60%);
  pointer-events:none;
}
.app-header .brand { display:flex; align-items:center; gap:16px; }
.app-header .logo {
  height:58px; padding:6px 14px; border-radius:14px; flex:none;
  background:#ffffff; border:1px solid rgba(255,255,255,.55);
  display:flex; align-items:center; justify-content:center; font-size:24px;
  box-shadow: 0 6px 18px -8px rgba(0,0,0,.4);
}
.app-header .logo img { height:100%; width:auto; display:block; }
.app-header .title { font-size: 25px; font-weight: 750; letter-spacing: -.02em; margin: 0; line-height:1.15; }
.app-header .subtitle { font-size: 13px; opacity: .82; margin-top: 3px; }
.app-header .cluster-chip {
  background: rgba(255,255,255,.14); border: 1px solid rgba(255,255,255,.26);
  padding: 9px 15px; border-radius: 12px; font-size: 12.5px; text-align: right;
  white-space: nowrap; backdrop-filter: blur(4px); z-index:1;
}
.app-header .cluster-chip b { font-size: 15px; }

/* --- live status line --- */
.live-line { display:flex; align-items:center; gap:10px; margin: 2px 0 16px; font-size: 13px; color:var(--muted); }
.live-dot { width:9px; height:9px; border-radius:50%; background:#22c55e; box-shadow:0 0 0 rgba(34,197,94,.7); animation: pulse 1.8s infinite; }
.live-dot.paused { background:var(--faint); animation:none; }
@keyframes pulse { 0%{box-shadow:0 0 0 0 rgba(34,197,94,.55);} 70%{box-shadow:0 0 0 7px rgba(34,197,94,0);} 100%{box-shadow:0 0 0 0 rgba(34,197,94,0);} }

/* --- overall banner --- */
.banner { border-radius: 14px; padding: 17px 22px; margin-bottom: 18px; display:flex; align-items:center; gap:16px; box-shadow: var(--shadow); }
.banner .b-icon { font-size: 26px; line-height:1; }
.banner .b-title { font-size: 18px; font-weight: 750; margin:0; }
.banner .b-sub { font-size: 13px; margin-top:2px; opacity:.92; }
.banner.ok    { background: linear-gradient(180deg,#f0fdf4,#ecfdf5); border:1px solid #bbf7d0; color:#166534; }
.banner.breach{ background: linear-gradient(180deg,#fef2f2,#fff1f2); border:1px solid #fecaca; color:#991b1b; }

/* --- KPI cards --- */
.kpi-grid { display:grid; grid-template-columns: repeat(4, 1fr); gap:16px; margin-bottom:24px; }
.kpi { position:relative; background:var(--card); border:1px solid var(--line); border-radius:16px;
  padding:18px 20px; box-shadow: var(--shadow); transition: transform .15s ease, box-shadow .15s ease; }
.kpi:hover { transform: translateY(-2px); box-shadow: 0 10px 26px -12px rgba(15,23,42,.22); }
.kpi .k-label { font-size:11.5px; font-weight:700; text-transform:uppercase; letter-spacing:.06em; color:var(--faint); }
.kpi .k-value { font-size:32px; font-weight:800; margin-top:8px; line-height:1; letter-spacing:-.02em; }
.kpi .k-value.green { color:#16a34a; } .kpi .k-value.red { color:#dc2626; } .kpi .k-value.blue { color:var(--brand); } .kpi .k-value.slate { color:var(--ink); }
.kpi .k-foot { font-size:12px; color:var(--faint); margin-top:7px; }

/* --- section title --- */
.section-title { font-size:12.5px; font-weight:800; color:#334155; margin: 8px 0 13px;
  text-transform:uppercase; letter-spacing:.08em; display:flex; align-items:center; gap:9px; }
.section-title::before { content:""; width:4px; height:15px; border-radius:3px;
  background: linear-gradient(180deg,var(--brand),var(--brand-2)); display:inline-block; }
.scope-chip { display:inline-block; margin-left:2px; padding:2px 10px; border-radius:20px;
  background:#eef2ff; color:#3730a3; font-size:11px; font-weight:700; text-transform:none;
  letter-spacing:0; vertical-align:middle; }

/* --- check cards grid --- */
.check-grid { display:grid; grid-template-columns: repeat(3, 1fr); gap:16px; }
.check-card { background:var(--card); border:1px solid var(--line); border-left-width:4px;
  border-radius:14px; padding:15px 17px; box-shadow: var(--shadow);
  transition: transform .15s ease, box-shadow .15s ease; }
.check-card:hover { transform: translateY(-2px); box-shadow: 0 10px 26px -12px rgba(15,23,42,.22); }
.check-card.ok { border-left-color:#22c55e; }
.check-card.breach { border-left-color:#ef4444; }
.check-card.nodata { border-left-color:#cbd5e1; opacity:.72; }
.check-head { display:flex; align-items:center; gap:10px; }
.check-icon { font-size:17px; }
.check-name { font-weight:700; font-size:14px; color:var(--ink); flex:1; }
.badge { font-size:10.5px; font-weight:800; padding:3px 10px; border-radius:20px; letter-spacing:.04em; }
.badge.ok { background:#dcfce7; color:#15803d; }
.badge.breach { background:#fee2e2; color:#b91c1c; }
.badge.nodata { background:#f1f5f9; color:#64748b; }
.check-detail { font-size:12.5px; color:var(--muted); margin-top:10px; line-height:1.5; }

/* --- AI findings --- */
.finding { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:15px 17px; margin-bottom:12px; box-shadow: var(--shadow); }
.finding-head { display:flex; align-items:center; gap:10px; margin-bottom:8px; }
.finding-title { font-weight:750; font-size:15px; color:var(--ink); flex:1; }
.sev { font-size:10.5px; font-weight:800; padding:3px 11px; border-radius:7px; color:#fff; letter-spacing:.05em; }
.sev.CRITICAL { background:#7f1d1d; } .sev.HIGH { background:#dc2626; } .sev.MEDIUM { background:#d97706; } .sev.LOW { background:var(--brand-2); }
.finding-row { font-size:13px; color:#334155; margin-top:6px; line-height:1.5; }
.finding-row b { color:var(--ink); }
.rel-tag { display:inline-block; background:#f1f5f9; color:#475569; font-size:11px; padding:2px 9px; border-radius:6px; margin:2px 4px 2px 0; }
.ai-summary { background: linear-gradient(180deg,#eef2ff,#eff6ff); border:1px solid #c7d2fe; border-radius:14px;
  padding:17px 19px; margin-bottom:16px; font-size:14px; color:#312e81; line-height:1.55; box-shadow: var(--shadow); }
</style>
"""


def _esc(text: str) -> str:
    return html.escape(str(text))


def header_bar(product: str, subtitle: str, cluster: str, source_label: str) -> str:
    logo_html = (
        f'<img src="{LOGO_DATA_URI}" alt="logo"/>' if LOGO_DATA_URI else "🛰️"
    )
    return f"""
    <div class="app-header">
      <div class="brand">
        <div class="logo">{logo_html}</div>
        <div>
          <p class="title">{_esc(product)}</p>
          <div class="subtitle">{_esc(subtitle)}</div>
        </div>
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
