# Cloudera Ops Monitoring Agent

Automated health monitoring for Cloudera clusters, with **governed, agentic AI incident analysis**. Built to be sold as a service to multiple customers: everything customer-specific is data/configuration in a database, never code.

The product is a **FastAPI backend + React (Vite) frontend + PostgreSQL** (with a SQLite dev fallback). It wraps a deterministic monitoring **engine** (the `checks/`, `config/`, `data_sources/`, `cloudera/` packages) and adds accounts, multi-tenant clusters, plans, per-user access control, a multi-provider LLM layer, usage metering, and end-to-end logging.

> For a function-by-function trace of **what runs in what order** — from process start, through a browser request, down to reading cluster data and running the AI — see **[RUNBOOK.md](RUNBOOK.md)**.

---

## How it works (30-second version)

```
 data source            checks (plain Python)            AI (only on problems)
┌──────────────┐      ┌──────────────────────┐        ┌──────────────────────┐
│ uploaded CM  │      │ 9 checks compare the │  any   │ agentic AI connects  │
│ export files │ ───> │ data against limits  │ ────>  │ related problems,    │
│   OR a live  │      │ from the tenant's DB │ breach │ ranks severity &     │
│   CM cluster │      │ thresholds           │        │ suggests fixes       │
└──────────────┘      └──────────────────────┘        └──────────────────────┘
                              │ no breaches
                              └────> "all green" (the AI is never called)
```

1. A **data source** provides cluster data — hosts, services, metrics, events. The checks read one common interface, so the source is swappable.
2. **Nine checks** — plain, deterministic Python — compare that data against the tenant's configured limits (CPU %, disk %, heartbeat window, …). **No AI is involved in detection**, so results are fast and repeatable.
3. Only when checks find breaches does the **AI analyst** run: specialized per-KPI agents (and one incident coordinator) investigate with tools, connect related problems, rank severity, and suggest remediation. On a healthy cluster the AI is never called.

The AI **never decides what is broken** — a deterministic check already did that, and a **severity floor** computed from the check's own data means the model can raise severity but never under-rate a finding. That is the "governed" part.

---

## Architecture at a glance

```
                 Browser (React SPA, Vite)
                          │  /api/*  (same-origin; Vite dev-proxy or prod reverse-proxy)
                          ▼
              FastAPI app  (backend/app/main.py)
    ┌─────────────────────────────────────────────────────────┐
    │  api/routes/*   auth · monitoring · analysis · admin …   │
    │  api/deps.py    JWT auth, current-user, admin guard      │
    │  core/          config · logging · errors · crypto · JWT │
    │  db/            SQLAlchemy models + session (Postgres)   │
    │  llm/           model registry · access · usage · keys   │
    │  ai/            agentic analyzer · agents · tools · jobs  │
    │  engine/        bridge  ── adapts a DB Tenant to ↓ ──────┼──┐
    └─────────────────────────────────────────────────────────┘  │
                                                                  ▼
              Monitoring engine (unchanged, provider-agnostic):
              checks/  config/  data_sources/  cloudera/
                          │
                          ▼
              Cluster data:  uploaded export files  OR  live CM API + SSH
```

The **engine** (`checks/`, `config/`, `data_sources/`, `cloudera/`) is the original, standalone monitoring core. The **product** (`backend/app/`) never re-implements monitoring — `backend/app/engine/bridge.py` builds an engine `TenantConfig`/data source from a database `Tenant` row and calls the engine. Swapping a customer from "uploaded files" to "live cluster" is a single field on that row; nothing above the data source changes.

---

## Tech stack

### Frontend (`frontend/`)

| Concern | Technology |
|---|---|
| UI library | **React 19** (+ react-dom) |
| Language | **JavaScript + JSX** — not TypeScript (`@types/*` present only for editor autocomplete) |
| Build tool / dev server | **Vite 8** (`@vitejs/plugin-react`), with HMR and an `/api` → backend dev proxy |
| Routing | **React Router 7** (`react-router-dom`) + auth route guards |
| Server state / data fetching | **TanStack React Query 5** |
| HTTP client | **Axios** (single instance with JWT attach + auto token-refresh, `lib/api.js`) |
| Styling | **Tailwind CSS 4** (`@tailwindcss/vite`) + CSS design tokens |
| Theming | Class-based dark mode (`.dark` on `<html>`, persisted in localStorage) |
| App state | **React Context** providers (Auth, Analysis, Theme, Toast) + localStorage — no Redux/Zustand |
| Linter | **oxlint** |

### Backend (`backend/app/`)

| Concern | Technology |
|---|---|
| Web framework | **FastAPI** (pinned `0.115.6` / Starlette `0.41.3` — see `requirements.txt`) |
| Server | **Uvicorn** |
| Language | **Python 3.12+** (dev env: 3.14) |
| Validation / schemas | **Pydantic v2** (+ `pydantic-settings` for config) |
| ORM | **SQLAlchemy 2.0** (typed `Mapped[...]` models) |
| Migrations | **Alembic** |
| Auth | **PyJWT** (access + refresh tokens) + **bcrypt** (password hashing) |
| Secrets at rest | **cryptography** (Fernet) — encrypts stored API keys / CM passwords |
| AI / LLM | **OpenAI Agents SDK** (`openai-agents`) for agentic analysis, **Anthropic SDK** for the Claude direct-call path, OpenAI-compatible transport for all other providers |
| Knowledge base parsing | **openpyxl** (known-issues `.xlsx`) |
| Cluster access (engine) | **httpx** (CM REST) + **paramiko** (SSH) + **ruamel.yaml** / **pyyaml** |

### Database

| Concern | Technology |
|---|---|
| Production | **PostgreSQL** (driver: `psycopg[binary]`) |
| Local dev fallback | **SQLite** — used automatically when no `DATABASE_URL` is set (`backend/ops.db`) |

Models use only portable column types (`JSON`, `String`, `DateTime`), so the same schema and Alembic migrations run unchanged on both PostgreSQL and the SQLite dev fallback.

---

## Repository layout

| Path | What's in it |
|---|---|
| **`backend/app/`** | The FastAPI product (see the sub-table below) |
| `backend/alembic/` | Database migrations (`alembic upgrade head`) |
| `backend/tests/` | Pytest suite for the product (auth, access, AI, monitoring, logging, …) |
| `backend/uploads/` | Admin-uploaded tenant export files (gitignored) |
| **`frontend/`** | React + Vite single-page app (`frontend/src/`) |
| **`checks/`** | The nine checks + `run_all_checks()` → `HealthReport` (engine) |
| **`config/`** | Engine tenant schema/loader + the demo tenant YAML (engine) |
| **`data_sources/`** | The data sources (export files, live API, JSON) + parsing + day filter (engine) |
| **`cloudera/`** | Live-cluster access: CM REST client, SSH commands, metric queries (engine) |
| `knowledge/` | The AI knowledge base (best-practices `.md` + actionable known-issues `.xlsx`) |
| `data/` | Sample data + the `bdaktprod` demo export the seed tenant points at |
| `context/` | **Generated:** append-only `breach_history.csv` (every AI analysis; gitignored) |
| `logs/` | **Generated:** rotating JSON logs, 7-day retention (gitignored) |
| `secrets/` | Legacy per-tenant credential files for the engine's standalone mode (gitignored) |

### Inside `backend/app/`

| Package | Responsibility |
|---|---|
| `main.py` | **App entry point** — builds the FastAPI app, configures logging, mounts routers |
| `core/` | `config` (settings/.env), `logging_config` + `log_context` (structured logs), `errors` (request-id + error envelope), `security` (JWT + bcrypt), `crypto` (Fernet at-rest encryption), `email` |
| `db/` | `models.py` (all tables), `base.py` (engine/session, `get_db`) |
| `api/routes/` | HTTP endpoints, grouped by area (auth, monitoring, analysis, settings, and four admin routers) |
| `api/deps.py` | Auth dependencies: `get_current_user`, `require_admin` |
| `engine/` | `bridge.py` (DB Tenant → engine), `kpi_access.py` (per-user KPI visibility), `uploads.py` (file handling) |
| `llm/` | `registry.py` (every model the product can use), `access.py` (effective per-user access), `usage.py` (metering + limits), `settings.py` (per-user keys/priority), `providers.py`/`runner.py` (chat transport) |
| `ai/` | `analyzer.py` (orchestrates one analysis), `agent_runner.py` (fallback chain), `kpi_agents.py` (agent definitions), `agent_tools.py` (investigation tools), `jobs.py` (background threads), `knowledge.py`, `dependencies.py`, `trends.py`, `breach_history.py`, `models.py` (output schemas + severity floor) |
| `schemas/` | Pydantic request/response models |
| `seed.py` | First-run: run migrations, create the admin, a demo plan, and the `bdaktprod` demo tenant |

---

## The monitoring engine (deterministic, no AI)

`run_all_checks()` runs **nine checks in a fixed order**, each reading the data source through one interface and comparing against the tenant's thresholds:

| # | Check (`task`) | Flags when |
|---|---|---|
| 1 | `host_health` | any host `healthSummary` is CONCERNING/BAD |
| 2 | `heartbeat` | `now − last_heartbeat > heartbeat_window_sec` |
| 3 | `cpu_percent` | any host CPU > `cpu_pct` |
| 4 | `ram_percent` | used/total memory > `ram_pct` |
| 5 | `disk_percent` | a watched mount > `disk_pct`, or a log dir > `log_size_mb` |
| 6 | `hdfs_health` | HDFS unhealthy, or storage grew past the growth threshold |
| 7 | `service_status` | any service/role not STARTED/GOOD |
| 8 | `alerts` | active Cloudera Manager alert events |
| 9 | `network` | zero throughput / frame errors / unreachable hosts |

Each returns a `CheckResult` with `status` = **OK / BREACH / NO_DATA** (NO_DATA = the source can't provide that data yet, e.g. no services file uploaded).

### Two data-source modes (per tenant, chosen by an admin)

A `Tenant.data_source_mode` decides where a customer's data comes from — the whole demo-to-production switch:

| Mode | Engine source | Reads from | Stage |
|---|---|---|---|
| `json` | `ClouderaExportSource` | Cloudera Manager API exports uploaded as files (`hosts/`, `metrics/`, optional `services.json`/`events.json`) | Demo — the customer's real data, offline |
| `api` | `ClouderaApiSource` | the live Cloudera Manager REST API (+ optional SSH) using the tenant's encrypted credentials | Production |

Both return the **same record types**, so the checks, AI, and dashboard are byte-for-byte identical between them. See [RUNBOOK.md](RUNBOOK.md) §6–§8 for the side-by-side.

---

## The AI layer (agentic + governed)

When at least one check breaches and a user asks for analysis, `backend/app/ai/analyzer.py` runs an **agentic** analysis on the [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/):

- **Per-KPI agents** (`kpi_agents.py`) — one specialized analyst per check — and one **Incident Coordinator** for the all-breaches view. Each agent has task-specific instructions, shared governance rules, a set of **investigation tools** (`agent_tools.py`: knowledge search, evidence detail, dependency impact, disk-trend projection), and a **structured output schema**.
- **Grounding is seeded into the input** (top knowledge match + dependency impact) so even weak/local models produce grounded answers; capable models use the tools to go further.
- **Governance:** detection is deterministic; a **severity floor** (`ai/models.py`) computed from the check's own data means the model can raise severity but never under-rate it.
- **Multi-provider fallback chain** (`agent_runner.py`): the analysis is attempted against each model in the user's priority chain until one succeeds, with per-attempt metering and fallback-on-error.
- **Breach history:** every completed analysis is appended to `context/breach_history.csv` — a cross-user corpus of "what broke and what the AI said," for later review or as future LLM context. This is best-effort and can never fail an analysis.
- **Background jobs:** analysis is slow (minutes on CPU), so it runs on a worker thread (`ai/jobs.py`) and the frontend polls; nothing blocks a request.

### Supported models (`llm/registry.py`)

Because analysis is agentic, **every model must support tool/function calling.** Providers:

- **Agentic path** (OpenAI-compatible transport): **Ollama** (local — data never leaves the network), **OpenAI**, **Google Gemini**, **xAI Grok**, **Groq**, **OpenRouter**.
- **Direct-call path:** **Anthropic (Claude)** — runs a single-shot prompt (no live tool use for that one provider) because the Agents SDK needs an adapter package that can't be installed in this environment. Same governance, metering, and severity floor apply. See the docstring in `ai/agent_runner.py`.

Which models a user may use, and their fallback order, come from their **plan** (default) overridden by **per-user access** (`llm/access.py`).

---

## Accounts, tenants, plans, and access control

- **Auth** (`api/routes/auth.py`, `core/security.py`): JWT access + refresh tokens, bcrypt passwords, roles (`admin` / `user`). Registration always creates a normal user — admins are made by other admins or the seed script. Includes a full **account-deletion lifecycle** (self-service request → admin accept → 30-day recoverable window → recovery or dormant); see `db/models.py::AccountStatus`.
- **Tenants** (clusters): admins onboard a cluster, upload its export files or enter live CM credentials, and **link users** to it. Users only see clusters they're linked to; admins see all.
- **Plans** (`db/models.py::Plan`): the commercial knob — which models a customer may use, context budget, allowed Cloudera versions, and daily/monthly AI-call & token limits.
- **Per-user overrides:** an admin can grant a user a specific model set, a personal fallback chain, custom limits, and **per-KPI visibility** (`allowed_kpis`) — which of the nine checks (and their thresholds and refresh settings) appear on that user's dashboard. Empty = unrestricted; admins always see all nine. Enforced in `engine/kpi_access.py`.
- **Usage metering** (`llm/usage.py`, `ApiUsage` table): every model call is recorded (tokens, latency, success) and checked against the effective limits before a new analysis starts.

---

## Running it

### Prerequisites

- **Python 3.12+** with the repo's virtualenv (`.venv`) and `pip install -r requirements.txt`.
- **Node 18+** for the frontend (`cd frontend && npm install`).
- **PostgreSQL** for production. For local dev you can skip it — with no `DATABASE_URL` set, the backend falls back to a SQLite file at `backend/ops.db`.
- *(Optional)* **Ollama** running locally if you want the free local model (`ollama pull qwen2.5:7b`). Cloud providers need only an API key, pasted per-user in the UI.

### 1. Prepare the database (once)

Runs Alembic migrations, then creates the default admin, a demo plan, and the `bdaktprod` demo tenant. Idempotent.

```bash
python -m backend.app.seed
```

Default admin: `admin@blutechconsulting.com` / `ChangeMe!123` (override via `ADMIN_EMAIL` / `ADMIN_PASSWORD` in `.env`; change the password immediately in a real deployment).

### 2. Start the backend (terminal 1, venv active, from the repo root)

```bash
uvicorn backend.app.main:app --port 8000 --reload
```

Interactive API docs: http://127.0.0.1:8000/docs · health check: http://127.0.0.1:8000/health

### 3. Start the frontend (terminal 2)

```bash
npm run dev --prefix frontend
```

Open http://localhost:5173. The Vite dev server proxies `/api/*` to the backend on port 8000 (override with `BACKEND_URL` before `npm run dev`), so the SPA makes same-origin calls with no CORS setup in dev.

---

## Configuration

Global settings live in **`.env`** at the repo root (gitignored; loaded by `core/config.py`). Everything has a sensible default — the app runs with an empty `.env`.

| Setting | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | SQLite `backend/ops.db` | Set to `postgresql+psycopg://user:pw@host:5432/db` for production |
| `SECRET_KEY` | auto-generated | Signs JWTs — **generated into `.env` on first run** if empty |
| `ENCRYPTION_KEY` | auto-generated | Fernet key encrypting stored API keys / CM passwords — generated on first run |
| `LOG_LEVEL` | `INFO` | Logging verbosity (see below) |
| `ACCESS_TOKEN_MINUTES` / `REFRESH_TOKEN_DAYS` | 30 / 7 | Token lifetimes |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | see above | First-run admin the seed creates |
| `CORS_ORIGINS` | localhost:5173 | Allowed browser origins |
| `APP_BASE_URL` | localhost:5173 | Used in invite links |
| `SMTP_*` | empty | Optional — invite emails; invites still work without SMTP |

> `SECRET_KEY` and `ENCRYPTION_KEY` auto-generate and **persist to `.env`** on first boot. Don't rotate them casually — a new `SECRET_KEY` invalidates all sessions, and a new `ENCRYPTION_KEY` makes stored secrets undecryptable.

**Per-user runtime settings** (LLM API keys, Ollama URL, model priority, KPI refresh intervals) are **not** in `.env` — users set them in the app's Settings page, and they're stored (secrets encrypted) in the database.

---

## Logging

End-to-end structured logging (`core/logging_config.py` + `core/log_context.py`):

- **`logs/app.log`** — everything, one JSON object per line.
- **`logs/errors.log`** — ERROR and above only (unhandled exceptions, model failures).
- Both **rotate at midnight (UTC) and keep 7 days**; older files auto-delete.
- Every line carries `request_id`, `user_id`, and `user_email`, propagated automatically through async code, the monitoring engine, and background AI threads — so one request (or one user's activity) is a single query away.

```bash
# PowerShell (no grep/jq needed):
Get-Content logs\app.log | ForEach-Object { $_ | ConvertFrom-Json } | Where-Object { $_.user_email -eq "someone@company.com" }
# Git Bash / Linux:
grep '"request_id": "abc123"' logs/app.log | jq .
```

---

## Tests

```bash
python -m pytest backend/tests -q
```

Runs fully offline — the LLM is never actually called (the AI endpoints monkeypatch the analyzer, and agent behavior is asserted structurally). Covers auth, the account lifecycle, per-user KPI/model access, monitoring endpoints, the AI job flow, breach history, and logging.

---

## Deployment notes

- Point `DATABASE_URL` at PostgreSQL and run `python -m backend.app.seed` (or `alembic upgrade head`) on deploy.
- Serve the built frontend (`npm run build --prefix frontend`) and the FastAPI app behind one reverse proxy that forwards `/api/*` to the backend, so the SPA's same-origin `/api` calls keep working.
- Ship `logs/*.log` to your aggregator (Loki/ELK/CloudWatch) — they're already structured JSON, no reformatting needed.
```
