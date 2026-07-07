# RUNBOOK — end-to-end execution walkthrough

This document traces **exactly what runs, in what order**, from a browser
refresh all the way down to reading cluster data — for both data paths:

- **Extracted JSON path** (`data_source.type: export`) — reads real Cloudera
  Manager API exports saved as files. This is what the demo uses.
- **Live API path** (`data_source.type: api`) — calls a real Cloudera cluster.

The two paths differ **only** in the data-source object at the bottom. Every
layer above it — the API endpoints, the checks, the AI, the dashboard — is
identical. That's the whole design.

---

## 0. The two processes

| Process | Command | Role |
|---|---|---|
| **Backend** | `uvicorn api.main:app --port 8000` | FastAPI — runs checks + AI, exposes HTTP |
| **Frontend** | `streamlit run dashboard/app.py` | Dashboard — calls the backend over HTTP |

The frontend holds **no logic**; it only draws what the backend returns. A
different UI could replace it by calling the same endpoints.

```
Browser ──HTTP──> Streamlit (dashboard/app.py) ──HTTP──> FastAPI (api/) ──> checks / AI / data source
```

---

## 1. Startup — what runs first

### Backend (`uvicorn api.main:app`)
1. Python imports `api/main.py`.
2. `api/main.py` adds the project root to `sys.path` (so `config`, `checks`, … import no matter where uvicorn is launched).
3. `setup_logging()` (`app_logging.py`) — opens the daily log file `logs/ops_agent.log` (rotates at midnight, keeps 7 days).
4. `app = FastAPI(...)` is created and the route functions are registered.
5. uvicorn starts listening on `:8000`. **No cluster or file is touched yet** — data is only read when a request arrives.

### Frontend (`streamlit run dashboard/app.py`)
1. `dashboard/app.py` adds the project root to `sys.path` and reads `.env` (`load_dotenv`).
2. `API_BASE` is resolved (`API_BASE_URL` in `.env`, default `http://127.0.0.1:8000`).
3. Streamlit runs `main()` top-to-bottom on every page load / interaction.

---

## 2. First page load — the tenant list

When the browser opens the dashboard, `main()` in `dashboard/app.py` runs:

1. `api_list_tenants()` → `GET /tenants`.
2. Backend `list_tenants()` (`api/main.py`) → `service.list_tenants()` → `load_tenant_configs_from_dir("config/tenants")` (`config/loader.py`) — reads and validates every `*.yaml`.
3. For each tenant, `service.tenant_summary()` → `source_kind_for(tenant)` (`data_sources/select.py`) decides `json` / `export` / `api` (honoring the optional `USE_JSON` override in `.env`).
4. Returns `[{tenant_id, display_name, cluster_name, source_kind}, ...]`.
5. The dashboard draws the sidebar: tenant dropdown, live toggle, refresh interval, and — if the tenant has history — a **date picker** (next section).

---

## 3. The core loop — a monitoring report (runs every N seconds)

This is the heart. The dashboard's `st.fragment(run_every="10s")` calls
`render_live_monitor()` on a timer, which calls the backend report endpoint.

### 3a. Frontend → backend
1. `render_live_monitor()` (`dashboard/app.py`) → `api_get_report(tenant_id, as_of)` → `GET /tenants/{id}/report?as_of=YYYY-MM-DD`.

### 3b. Backend orchestration (identical for both data paths)
2. `tenant_report()` (`api/main.py`) → `service.build_report(tenant_id, as_of)`.
3. `build_report()` (`api/service.py`):
   - `get_tenant(tenant_id)` — load the tenant's config.
   - `get_source(tenant_id)` — get (or build + cache) the data source. **This is where the two paths diverge — see §5 and §6.**
   - Acquire the tenant's lock (so a concurrent request for a different day can't corrupt this one).
   - `_apply_day(source, as_of)` — if the source is day-aware, set `source.as_of = as_of` and compute `now = source.reference_now()` (the heartbeat reference).
   - `run_all_checks(source, tenant, now)`.
4. `run_all_checks()` (`checks/run_all_checks.py`) runs the **9 checks in order**, each reading the source and comparing against the tenant's thresholds:

   | # | Function | Reads (via the source) | Flags when |
   |---|---|---|---|
   | 1 | `check_host_health` | `get_hosts()` | any host `healthSummary != GOOD` |
   | 2 | `check_heartbeat` | `get_hosts()` | `now − last_heartbeat > heartbeat_window_sec` |
   | 3 | `check_cpu_percent` | `get_metrics(["cpu_percent"])` | any host CPU > `cpu_pct` |
   | 4 | `check_ram_percent` | `get_metrics(["physical_memory_used","physical_memory_total"])` | used/total > `ram_pct` |
   | 5 | `check_disk_percent` | `get_metrics(["fs_bytes_used_percent"])` + `get_disk_usage()` + `get_log_files()` | mount > `disk_pct` or log > `log_size_mb` |
   | 6 | `check_hdfs_health` | `get_services()` + `get_metrics(["dfs_capacity_used"])` | HDFS unhealthy or storage grew > threshold |
   | 7 | `check_service_status` | `get_services()` + `get_roles()` | any service/role not STARTED/GOOD |
   | 8 | `check_alerts` | `get_events()` | any active alert event |
   | 9 | `check_network` | `get_metrics([...throughput...])` + `ping_hosts()` | zero throughput / frame errors / unreachable |

   Each returns a `CheckResult` with `status` = **OK** / **BREACH** / **NO_DATA**
   (NO_DATA = the source can't provide that data yet, e.g. no services export).
5. `run_all_checks()` bundles them into a `HealthReport` (with `breach_count`, `ok_count`, `no_data_count`) and logs a one-line summary (full detail only when the situation changes).
6. The endpoint returns `report.model_dump()` as JSON.

### 3c. Backend → frontend
7. `render_live_monitor()` parses the JSON back into a `HealthReport` and renders (via `dashboard/styles.py`): the live indicator, the health banner, the KPI cards, and the 9 check cards. **No AI is involved in this loop** — it's pure deterministic Python, fast and cheap.

### 3d. Refresh interval vs. caching — how "fresh" the data really is

The sidebar **Refresh interval** (5 / 10 / 30 / 60s) sets `run_every` on the
Streamlit fragment. So *every interval*, the dashboard calls the backend and the
**9 checks re-run**. What that pulls underneath depends on the source:

**Export / JSON tenants (files):** fully fresh every interval. The checks re-read
the source; a file is re-parsed only if its mtime changed (unchanged files skip
re-parsing but the data returned is still current). Edit a JSON file → the
dashboard reflects it within one interval.

**Live API tenants:** two different freshness rules on purpose —

| What | Refreshes every interval? | Why |
|---|---|---|
| Dashboard → backend call + check run | ✅ yes | the refresh timer |
| Host health + heartbeat (`get_hosts`) | ✅ yes — hits Cloudera every interval | real-time signals, never cached |
| Metrics: CPU / RAM / disk / HDFS / network | ❌ served from cache for `metrics_cache_ttl_sec` (default 300s) | metrics are pulled at HOURLY rollup — they only change once an hour, so re-querying every few seconds would load CM for no benefit |

So on a live cluster with a 5s interval: the page and host health update every
5s, but the metric *values* re-pull from Cloudera every 5 minutes (by design).
To change that for a specific customer, set `metrics_cache_ttl_sec` in their
`cloudera:` block (e.g. `60` = re-pull metrics each minute; `0` = no cache,
every interval hits the cluster — not recommended for the large disk query).

---

## 4. On-demand AI analysis (only when there are breaches)

Triggered by the **Run AI Analysis** button. The AI is slow (minutes on CPU), so it runs as a background job the client polls.

### 4a. Start the job
1. `_run_and_poll_analysis()` (`dashboard/app.py`) → `api_start_analysis()` → `POST /tenants/{id}/analyze?as_of=...`.
2. `start_analysis()` (`api/main.py`) → `jobs.start_analysis(tenant_id, as_of)` (`api/jobs.py`):
   - `_new_job()` creates a job record `{status: "running", ...}` and returns a `job_id` **immediately**.
   - `asyncio.create_task(_run(...))` launches the analysis in the background.
3. The endpoint returns `{job_id, status: "running"}` right away.

### 4b. The background job (`_run` in `api/jobs.py`)
4. `build_fresh_source(tenant_id)` — its **own** data source (not the shared cached one), so the auto-refresh loop can't change the day under it mid-run.
5. `build_report_on(source, tenant, as_of)` — re-run the 9 checks for the pinned day. Records a `breach_signature` (which breaches it's about).
6. If no breaches → job marked `no_breaches`, **the LLM is never called**.
7. Otherwise `run_ai_analysis(report, source, tenant, load_llm_config())` (`ai_analysis/analyzer.py`):
   - `build_analyst()` builds the agent (OpenAI Agents SDK) pointed at **Ollama** via an OpenAI-compatible client (`config/llm_config.py` → `OLLAMA_BASE_URL` / `OLLAMA_MODEL`).
   - The **9 checks are registered as tools**, so the agent can pull more data on demand while reasoning.
   - `Runner.run(analyst, prompt)` — the prompt is the list of breaches; the agent correlates them, ranks severity, writes a summary, recommends fixes.
   - Returns an `AiReport` (`overall_summary`, `findings[]`, `priority_order`).
8. The job record is updated to `{status: "done", result: <AiReport>, seconds, breach_signature}`.

### 4c. Poll until done
9. The dashboard polls `GET /analysis/{job_id}` (`api_poll_analysis()`) every 3 seconds until `status` is `done` / `error` / `no_breaches`.
10. On `done`, the `AiReport` is stored **keyed by (tenant, day)** so it never shows under a different date, and rendered as severity-tagged finding cards.

---

## 5. The extracted-JSON path (`type: export`) — bottom of the stack

Used by the `bdaktprod` tenant. Reads real CM API exports saved as files under
`data/bdaktprod/`.

**How `get_source()` builds it:** `choose_data_source(tenant)` → `_export_source()` → `ClouderaExportSource("data/bdaktprod")` (`data_sources/export_source.py`).

Folder layout it expects:
```
data/bdaktprod/
  hosts/*.json          one host resource file each (HostsResource, view=FULL)
  metrics/cpu.json  ram.json  disk.json  hdfs.json  network.json
  services.json  events.json   (optional — not provided yet → those checks are NO_DATA)
```

**What each source method does when a check calls it:**
- `get_hosts()` → reads `hosts/*.json`, `parse_cm_export.parse_host_file()` each.
- `get_metrics([names])` → reads the relevant `metrics/*.json` (cached by file **mtime** — only re-read when the file changes on disk, so a 44 MB disk file isn't re-parsed every refresh), parses with `parse_cm_export.*`, then trims to `as_of` via `day_filter.trim_to_day()`.
  - disk: `capacity`/`capacity_used` bytes → computed `fs_bytes_used_percent`.
  - hdfs: per-DataNode capacity → summed into one cluster series.
- `get_services()` / `get_events()` → `[]` for now (`has_services()`/`has_events()` return False → checks 6/7/8 report NO_DATA).
- `get_disk_usage()` / `ping_hosts()` / `get_log_files()` → `[]` (SSH isn't part of a file export).
- `available_dates()` → the days present in `cpu.json` (powers the date picker).
- `reference_now()` → newest host heartbeat (so a days-old export isn't reported as every host being silent).

---

## 6. The live-API path (`type: api`) — bottom of the stack

Used once a customer provides live access. Same interface, different plumbing.

**How `get_source()` builds it:** `choose_data_source(tenant)` → `_api_source()` (`data_sources/select.py`):
1. `load_tenant_secrets(tenant_id)` — loads `secrets/<tenant_id>.env` (that customer's credentials) into the environment.
2. `ClouderaApiSource(tenant)` (`data_sources/api_source.py`) — builds a `ClouderaApiClient` (HTTP, `cloudera/api_client.py`) and, if configured, `SshCommands` (paramiko, `cloudera/ssh_commands.py`).
3. `source.check_connection()` — one `GET /api/version` call to confirm the cluster is reachable. **If it fails, a clear `DataSourceError` is raised** → the endpoint returns HTTP 409 → the dashboard shows the friendly "not configured yet" message.

**What each source method does when a check calls it:**
- `get_hosts()` → `GET /hosts?view=FULL` → `parse_cm_export.parse_host_file()` each.
- `get_metrics([names])` → for each needed query, `_fetch_plan()`:
  - Builds the real CM tsquery (e.g. `select capacity_used, capacity where category=FILESYSTEM`).
  - `GET /timeseries?query=...&from=<lookback_days ago>&to=now&desiredRollup=HOURLY`.
  - Caches the result for `metrics_cache_ttl_sec` (default 300s) — since metrics are HOURLY, the ~10 s auto-refresh reuses the cache instead of re-hitting CM.
  - Parses with the **same** `parse_cm_export.*` functions as the file path, then trims to `as_of`.
- `get_services()` / `get_roles()` / `get_events()` → real `/services`, `/roles`, `/events` calls (checks 6/7/8 light up automatically once the account can read them).
- `get_disk_usage()` / `ping_hosts()` / `get_log_files()` → over SSH (`cloudera/ssh_commands.py`), only if the tenant has an `ssh:` block.
- `available_dates()` → days in the fetched CPU history (date picker works in live mode too).
- `reference_now()` → newest host heartbeat.

`lookback_days` and `metrics_cache_ttl_sec` are **per-tenant** (the `cloudera:` block in the tenant YAML).

---

## 7. Side-by-side: same call, two paths

`check_cpu_percent` calls `source.get_metrics(["cpu_percent"])`. What happens:

| Step | `type: export` (files) | `type: api` (live) |
|---|---|---|
| Where data comes from | `data/<tenant>/metrics/cpu.json` | `GET /timeseries?query=select cpu_percent where category=HOST` |
| Freshness control | re-read when file's mtime changes | cached `metrics_cache_ttl_sec` |
| Parser | `parse_cm_export.parse_host_metric` | `parse_cm_export.parse_host_metric` (same) |
| Day filter | `day_filter.trim_to_day(as_of)` | `day_filter.trim_to_day(as_of)` (same) |
| Return type | `list[MetricSeries]` | `list[MetricSeries]` (same) |

The check itself is byte-for-byte identical in both cases — it never knows which
source answered.

---

## 8. Operations quick reference

**Run it (two terminals, venv active):**
```bash
uvicorn api.main:app --port 8000 --reload      # backend
streamlit run dashboard/app.py                 # frontend
```
Dashboard: http://localhost:8501 · API docs: http://127.0.0.1:8000/docs

**Logs:** `logs/ops_agent.log` — daily rotation, 7 days kept. Records every
monitoring run's breaches, AI start/finish/failure, data-source choices, errors.

**Onboard a customer:**
1. `config/tenants/<id>.yaml` — their cluster name, thresholds, `data_source.type`.
2. Demo stage: `type: export`, drop their JSON exports in `data/<id>/`.
3. Live stage: `type: api`, fill the `cloudera:` block, put credentials in `secrets/<id>.env`, flip the type.

**Tests:** `python -m pytest tests/ -q` (runs fully offline; the one live-LLM
test is deselected by default in CI).

**Common issues:**
| Symptom | Cause | Fix |
|---|---|---|
| Dashboard: "Can't reach the monitoring API" | backend not running | start uvicorn on :8000 |
| `ModuleNotFoundError: app_logging` | uvicorn launched from inside `api/` | run from project root as `api.main:app` |
| Tenant shows ⚠️ "not configured yet" | live-API tenant, cluster unreachable / no creds | fill `cloudera:` + `secrets/<id>.env`, or keep `type: export` |
| Port already in use | old process still bound | `netstat -ano | findstr :8000`, then `taskkill /F /PID <pid>` |
| AI analysis fails instantly | Ollama not running / model not pulled | start Ollama, `ollama pull qwen2.5:7b` |
