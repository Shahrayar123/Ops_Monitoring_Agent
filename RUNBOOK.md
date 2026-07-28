# RUNBOOK — end-to-end execution walkthrough

This document traces **exactly what runs, in what order** — from process startup, through a browser request, all the way down to reading cluster data and running the AI. It names the file and function at each step so you can follow any path in the code.

Read [README.md](README.md) first for the big picture; this is the "what executes first, and next, and next" companion.

Contents:
- §0 The two processes
- §1 Backend startup — what imports and runs first
- §2 Database preparation (migrations + seed)
- §3 Frontend startup — provider tree and routing
- §4 The request lifecycle every API call goes through
- §5 First load: login → tokens → tenant list
- §6 The monitoring loop (per-card polling → engine → checks)
- §7 The two data-source paths (uploaded files vs live API)
- §8 On-demand AI analysis (the agentic path)
- §9 Editing thresholds (a write path)
- §10 Access control (who sees which KPIs / models)
- §11 Logging, end to end
- §12 Operations quick reference + common issues

---

## 0. The two processes

| Process | Command (from repo root) | Role |
|---|---|---|
| **Backend** | `uvicorn backend.app.main:app --port 8000` | FastAPI — auth, monitoring, AI, admin; talks to Postgres and the engine |
| **Frontend** | `npm run dev --prefix frontend` | React SPA (Vite dev server on :5173), proxies `/api/*` → backend |

```
Browser ──/api/*──> Vite dev-proxy (or prod reverse-proxy) ──> FastAPI (backend/app) ──> engine ──> cluster data
```

Before either runs the first time, the **database must be prepared** (§2).

---

## 1. Backend startup — what runs first

Running `uvicorn backend.app.main:app` imports **`backend/app/main.py`**, which executes top-to-bottom:

1. **`sys.path` setup** — `main.py` prepends the repo root to `sys.path`, so the engine packages (`checks/`, `config/`, `data_sources/`, `cloudera/`) and `backend.app` resolve no matter where uvicorn was launched.
2. **Imports** pull in `get_settings`, `install_error_handling`, `configure_logging`, and every router module. (Importing a router module imports its dependencies — `db.models`, `llm.registry`, `ai.*` — so the model registry and agent definitions are constructed at import time.)
3. **`settings = get_settings()`** (`core/config.py`) — reads `.env`. **On first run**, if `SECRET_KEY` or `ENCRYPTION_KEY` is empty, it generates one and **appends it to `.env`** (so restarts don't invalidate sessions or stored secrets).
4. **`configure_logging(settings.log_level)`** (`core/logging_config.py`) — clears root handlers and installs three: a human-readable console handler, a JSON `logs/app.log` (INFO+), and a JSON `logs/errors.log` (ERROR+). Both files rotate at midnight UTC, keep 7 days. Also de-isolates uvicorn's loggers so HTTP access lines land in the files. **This is the first thing that touches the filesystem.**
5. **`app = FastAPI(...)`** is created.
6. **`install_error_handling(app)`** (`core/errors.py`) — registers the `request_id_middleware` (HTTP middleware) and the exception handlers that wrap every response in the `{ error: { code, message, request_id } }` envelope.
7. **CORS middleware** is added.
8. **`app.include_router(...)`** mounts every router: `auth`, `admin`, `monitoring`, `tenant_admin`, `settings`, `kpi_settings`, `plans_admin`, `user_admin`, `analysis`.
9. **`/health`** is defined.
10. uvicorn begins serving. **No database query, cluster call, or file read of tenant data happens at startup** — that only occurs when a request arrives. (The DB engine/session in `db/base.py` is created at import, but connects lazily.)

> The database schema is **not** created at startup. There is no `create_all()` or migration-on-boot — you must run the seed/migrations first (§2).

---

## 2. Database preparation (run once, before first boot)

```bash
python -m backend.app.seed
```

**`backend/app/seed.py`** runs, in order:

1. **`run_migrations()`** — invokes Alembic `upgrade head` against `backend/alembic/`, building every table in `db/models.py` (users, plans, tenants, tenant_files, user_tenants, user_kpi_refresh_rates, user_settings, api_usage, revoked_tokens).
2. **`seed()`** — idempotently creates:
   - the **Demo plan** (a starter set of allowed models + limits),
   - the **admin account** (`ADMIN_EMAIL`/`ADMIN_PASSWORD` from settings),
   - the **`bdaktprod` demo tenant** in `json` mode, pointing `data_dir` at the repo's `data/bdaktprod/` export, with thresholds copied from the engine's `config/tenants/bdaktprod.yaml`,
   - a `UserTenant` link so the admin can see the demo cluster.

Re-running is safe — existing rows are left alone.

---

## 3. Frontend startup — provider tree and routing

Vite serves **`frontend/src/main.jsx`** as the entry:

1. `createRoot(...).render(...)` mounts a nested provider tree (outermost → innermost):
   `ErrorBoundary → ThemeProvider → ToastProvider → QueryClientProvider (React Query) → AuthProvider → AnalysisProvider → App`.
   - **`AuthProvider`** (`lib/auth.jsx`) restores the session from tokens in storage (`lib/tokens.js`) and fetches the current user.
   - **`AnalysisProvider`** (`lib/analysis.jsx`) hydrates AI-analysis state from `localStorage` and resumes polling any still-running job. Polling lives **here, at the app root**, so a job keeps progressing as the user navigates.
2. **`App.jsx`** sets up `BrowserRouter` and the routes, wrapped in guards (`routes/guards.jsx`):
   - Public: `/login`, `/register` (redirect away if already signed in).
   - Protected (inside `AppShell`): `/dashboard`, `/dashboard/:slug/:task/analysis`, `/settings`, `/admin` (admin-only).
3. Every API call goes through **`lib/api.js`** — an axios instance with `baseURL: '/api'` that attaches the access token, and on a `401` transparently refreshes once (shared single in-flight refresh) and replays the request; if refresh fails, it clears tokens and redirects to `/login`.

---

## 4. The request lifecycle every API call goes through

For any request to the backend:

1. **`request_id_middleware`** (`core/errors.py`) assigns `request.state.request_id` (honoring an inbound `X-Request-ID`), sets it on the logging context (`core/log_context.py`), logs `"<METHOD> <path> started"`, and records the start time.
2. FastAPI resolves the route's **dependencies**. For protected routes that includes **`get_current_user`** (`api/deps.py`): it decodes the Bearer JWT (`core/security.py`), loads the `User`, and writes the user's id/email into both the logging contextvar **and** `request.state` (the latter because Starlette runs the route in a separate task from the middleware).
3. **`require_admin`** (`api/deps.py`) additionally gates admin routers with a 403 for non-admins.
4. The **route handler** runs (gets a DB session via `get_db`, one per request).
5. Back in the middleware, the completion line `"<METHOD> <path> -> <status> in <ms>ms"` is logged, attributed to the user (re-read from `request.state`), and `X-Request-ID` is set on the response.
6. Any raised `HTTPException` is turned into the standard error envelope; any **unhandled** exception is logged at ERROR (→ `errors.log`) and returned as a 500 envelope.

---

## 5. First page load — login → tokens → tenant list

1. The user submits the login form → `POST /auth/login` (`api/routes/auth.py::login`). On success it returns an **access + refresh token pair**; failures return one generic message (no email enumeration). Deleted/dormant accounts get specific 403s.
2. `AuthProvider` stores the tokens and calls **`GET /auth/me`** (`auth.py::me`) to load the current user (role, plan, must-change-password, etc.).
3. The dashboard mounts and calls **`GET /tenants`** (`api/routes/monitoring.py::list_tenants`): admins get every cluster; a normal user gets only the clusters linked to them via `UserTenant`.
4. For the selected cluster, `GET /tenants/{slug}` returns its detail (including effective per-user refresh rates), and `GET /tenants/{slug}/dates` powers the historical date picker.

---

## 6. The monitoring loop (deterministic, no AI)

The dashboard renders one **card per KPI**, and **each card polls on its own interval** (`components/monitoring/CheckCard.jsx`) — so a fast card (alerts, 15s) doesn't force a slow one (HDFS, 10 min) to recompute. There are two read endpoints:

### 6a. One card refreshing — `GET /tenants/{slug}/report/{task}`

1. `monitoring.py::tenant_single_check` runs. It first checks **KPI access** — `can_see_kpi(user, task)` (`engine/kpi_access.py`) → 403 if the user isn't granted that KPI.
2. → **`bridge.build_single_check(tenant, task, as_of)`** (`engine/bridge.py`):
   - `tenant_to_config(tenant)` builds an engine `TenantConfig` from the DB row (for `api` mode it decrypts CM credentials into per-tenant env vars the engine reads by name).
   - `get_source(tenant)` returns a cached engine data source (rebuilt only when the tenant's mode changes; the export source re-reads files whose mtime changed).
   - Under the tenant's lock, it sets `source.as_of` (for historical days) and runs the single check function from `checks/`.
3. The `CheckResult` (`status`, `detail`, `evidence`, `threshold`) is returned as JSON and the card re-renders.

### 6b. The whole dashboard — `GET /tenants/{slug}/report`

1. `monitoring.py::tenant_report` → **`bridge.build_report(tenant, as_of)`** → **`run_all_checks(source, config, now)`** (`checks/run_all_checks.py`) runs all nine checks in order into a `HealthReport` (`breach_count`, `ok_count`, `no_data_count`).
2. The endpoint **filters results to the KPIs this user may see** (`visible_kpis(user)`), recomputes `breach_count` over the visible set, and attaches effective refresh rates + the tenant's mode/version. The health ring and issue counts all derive from this filtered set, so every number on the dashboard is consistent with the cards shown.

**No AI runs in this loop** — it's pure deterministic Python, fast and cheap. If the data source isn't usable yet (no files uploaded, live API unreachable) the engine raises `DataSourceError` → HTTP **409** → the UI shows a friendly "not configured yet" message.

---

## 7. The two data-source paths — bottom of the stack

The paths differ **only** in the data-source object; every layer above is identical.

### 7a. Uploaded-files path (`data_source_mode: json` → engine `export` source)

Used by the seeded `bdaktprod` tenant and any tenant whose admin uploaded exports. `bridge.get_source` builds a **`ClouderaExportSource`** over the tenant's `data_dir`.

Expected folder layout:
```
<data_dir>/
  hosts/*.json          one host resource file each (view=FULL)
  metrics/cpu.json ram.json disk.json hdfs.json network.json
  services.json         (optional) GET /clusters/{c}/services?view=FULL
  events.json           (optional) GET /events?query=alert==true
```
Optional files that are absent make their check report **NO_DATA** rather than a false result. Metric files are cached by **mtime** (a large disk file isn't re-parsed every refresh); results are trimmed to `as_of` via `day_filter`. SSH-only methods (`get_disk_usage`, `ping_hosts`, `get_log_files`) return empty.

### 7b. Live-API path (`data_source_mode: api` → engine `ClouderaApiSource`)

Used once a customer provides live access. `bridge.tenant_to_config` decrypts the tenant's CM password (`core/crypto.py`) into per-tenant env vars; the engine builds a `ClouderaApiClient` (HTTP) and, if configured, `SshCommands` (paramiko). `check_connection()` confirms reachability (failure → `DataSourceError` → 409). Metrics come from real CM `timeseries` queries at HOURLY rollup, cached for `metrics_cache_ttl_sec`; host health/heartbeat are never cached.

### 7c. Same call, two paths

`check_cpu_percent` calls `source.get_metrics(["cpu_percent"])`. Files → read `metrics/cpu.json` (mtime-cached). Live → `GET /timeseries?query=... where category=HOST` (TTL-cached). **Same parser, same day-filter, same return type.** The check never knows which source answered.

---

## 8. On-demand AI analysis (the agentic path)

Triggered from a KPI card's "Run AI Analysis" (per-KPI) or the dashboard's incident section (all breaches). The AI is slow, so it runs as a **background job the frontend polls**.

### 8a. Start the job

1. Frontend `lib/analysis.jsx::start` → `POST /tenants/{slug}/analyze/{task}` (per-KPI) or `POST /tenants/{slug}/analyze` (incident) — `api/routes/analysis.py`.
2. The endpoint runs **`_preflight`**: the user has a non-empty model chain, and they're under their usage limit (`llm/usage.check_limit`) → otherwise an instant 400/429. It also re-checks KPI access.
3. **`jobs.start(...)`** (`ai/jobs.py`) creates an in-memory `Job` (`status: running`), **snapshots the logging context**, spawns a daemon **worker thread**, and returns a `job_id` immediately. The endpoint responds `{ job_id, status: "running" }`.

### 8b. The background job — `ai/jobs.py::_run`

Runs on the worker thread with its own DB session:

1. **Re-applies the logging context** (a raw thread doesn't inherit contextvars) so every log line is still attributed to the user/request.
2. Calls **`analyzer.analyze_kpi(...)`** or **`analyzer.analyze_incident(...)`** (`ai/analyzer.py`):
   - Re-runs the deterministic check(s) via the **bridge** to get the current breach detail. If nothing is breaching → `NoBreachError`, **the LLM is never called**.
   - Computes disk-trend context (`ai/trends.py`) where relevant.
   - Hands off to **`agent_runner.run_kpi_with_fallback` / `run_incident_with_fallback`**.
3. **`agent_runner.py`** resolves the user's fallback chain (`llm/access.effective_priority`) and, for each model until one succeeds:
   - Builds a fresh agent (`ai/kpi_agents.py`) bound to that model, with task-specific instructions, governance rules, **investigation tools** (`ai/agent_tools.py`), and a **structured output schema** (`ai/models.py`).
   - Seeds baseline knowledge (`ai/knowledge.py`) + dependency impact (`ai/dependencies.py`) directly into the agent input, then runs it (`Runner.run`, agentic) — **or**, for Anthropic, the single-shot direct-call fallback.
   - Meters the attempt (`llm/usage.record` → `ApiUsage`); on failure, logs and falls through to the next model.
4. Back in `analyzer.py`, the model's severity is **floored by the check's own data** (`ai/models.apply_floor`) — the governance guardrail — and the result is shaped into `KpiAnalysis` / `IncidentReport`.
5. The finished analysis is **appended to `context/breach_history.csv`** (`ai/breach_history.py`) — best-effort, never raises.
6. The `Job` is marked `done` (or `no_breach` / `error`).

### 8c. Poll until done

The frontend polls **`GET /analysis/{job_id}`** (`analysis.py::poll`, which enforces "your job or admin") every few seconds until `status` is `done` / `error` / `no_breach`. Results are cached in `localStorage` keyed by (cluster, task, day), so a refresh shows the finished analysis instead of re-running it, and any failed preferred model is surfaced with the provider's actual error.

---

## 9. Editing thresholds (a write path)

The only place the dashboard writes back configuration (`components/monitoring/ThresholdsModal.jsx`):

1. `GET /tenants/{slug}/thresholds` (`monitoring.py`) returns **only the thresholds behind KPIs this user can see** (`visible_threshold_fields`).
2. On save, `PUT /tenants/{slug}/thresholds` validates the values, **rejects edits to hidden fields with 403**, merges them onto the tenant's stored thresholds (a JSON column on `Tenant`), and persists. The next monitoring run reads the new limits — no cache to clear beyond the source, which the bridge handles.

Per-KPI **refresh intervals** work the same way via `/settings/kpi-refresh` (`api/routes/kpi_settings.py`), stored per-user in `user_kpi_refresh_rates` and merged over the cluster defaults.

---

## 10. Access control — who sees which KPIs and models

Enforced server-side, not just hidden in the UI:

- **KPI visibility** (`engine/kpi_access.py`): `User.allowed_kpis` — empty means all nine; non-empty restricts the dashboard cards, the report results, the thresholds, and the refresh settings a user sees. Admins always see all nine. Every read/write endpoint checks `can_see_kpi` / `visible_kpis` / `visible_threshold_fields`.
- **Model access** (`llm/access.py`): `effective_allowed_models(user)` = the user's own list if set, else their plan's — filtered to models still in the registry. `effective_priority(user)` is their fallback chain, filtered to what they're still allowed. A revoked model silently drops out.
- **Usage limits** (`llm/usage.py`): `effective_limits(user)` merges per-user overrides over plan defaults (0 = unlimited); `check_limit` runs before any analysis starts.

---

## 11. Logging, end to end

`core/logging_config.py` + `core/log_context.py`:

- **`logs/app.log`** (INFO+, JSON lines) and **`logs/errors.log`** (ERROR+), both rotating at midnight UTC, 7-day retention, older files auto-deleted.
- A `ContextFilter` attaches **`request_id`, `user_id`, `user_email`** to every record — from any logger, including the engine and third-party libraries.
- The context is set in the request middleware (§4), propagates automatically through async/await and into the monitoring engine, and is **explicitly re-applied inside the AI worker thread** (§8b) since raw threads don't inherit contextvars.
- Net effect: one `request_id` (or one `user_email`) is a single query away across every module that touched it.

```bash
# PowerShell:
Get-Content logs\app.log | ForEach-Object { $_ | ConvertFrom-Json } | Where-Object { $_.request_id -eq "abc123" }
# Git Bash / Linux:
grep '"request_id": "abc123"' logs/app.log | jq .
```

---

## 12. Operations quick reference

**Prepare DB (once):**
```bash
python -m backend.app.seed
```

**Run it (two terminals, venv active, repo root):**
```bash
uvicorn backend.app.main:app --port 8000 --reload    # backend
npm run dev --prefix frontend                         # frontend (Vite :5173, proxies /api -> :8000)
```
Frontend: http://localhost:5173 · API docs: http://127.0.0.1:8000/docs

**Logs:** `logs/app.log` (all, JSON) and `logs/errors.log` (errors) — daily rotation, 7 days.

**Breach history:** `context/breach_history.csv` — appended on every completed AI analysis (cross-user corpus; gitignored).

**Tests:** `python -m pytest backend/tests -q` (fully offline; the LLM is never actually called).

**Onboard a customer (admin, in the app):**
1. Create the tenant (Admin → Tenants).
2. Demo stage: keep `json` mode, upload their CM export files.
3. Live stage: switch to `api` mode, enter CM host/credentials (encrypted at rest), test the connection.
4. Link the customer's user(s) to the tenant; optionally restrict their KPIs, models, and limits.

**Add a new KPI (a 10th check):** the 9 KPIs are curated, code-defined checks; adding a new one is small, versioned dev work following a fixed pattern. See **[docs/ADDING_A_KPI.md](docs/ADDING_A_KPI.md)** for the step-by-step runbook (which files/functions to touch, in order).

**Common issues:**
| Symptom | Cause | Fix |
|---|---|---|
| Frontend: "Cannot reach the server" | backend not running, or on the wrong port | start uvicorn on `:8000` (or set `BACKEND_URL` for the Vite proxy) |
| `no such table` / login fails on a fresh checkout | migrations never run | `python -m backend.app.seed` |
| A KPI card shows **NO DATA** | that source file/endpoint isn't available (e.g. no `services.json`) | upload the file, or wire the live endpoint |
| Tenant shows "not configured yet" (409) | data source unusable — no files, or live CM unreachable/no creds | upload exports, or fill CM connection details |
| AI analysis returns instantly with an error | no model in the user's chain, or over the usage limit | set a model priority in Settings / raise the plan limit |
| AI falls back to another model | the preferred model failed (bad key, provider down, quota) | the card names the failed model + provider error; fix the key/quota |
| AI analysis "spins forever" until refresh | (fixed) frontend poll loop didn't start | ensure `lib/analysis.jsx` is current; polling now starts synchronously |
| A `403` on a threshold or KPI | the user isn't granted that KPI | grant it in Admin → the user's access panel |
| Local model errors instantly | Ollama not running / model not pulled | start Ollama, `ollama pull qwen2.5:7b`, set the Ollama URL in Settings |
| Port already in use | old process still bound | `netstat -ano \| findstr :8000`, then `taskkill /F /PID <pid>` |
