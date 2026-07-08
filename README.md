# Cloudera Ops Monitoring Agent

Automated health monitoring for Cloudera clusters, with AI-assisted incident analysis. Built to be sold as a service to multiple customers: everything customer-specific is configuration, never code.

> For a deep, function-by-function trace of what runs in what order (both data, paths), see **[RUNBOOK.md](RUNBOOK.md)**.

## How it works (30-second version)

```
 data source            checks (plain Python)           AI (only on problems)
┌──────────────┐      ┌──────────────────────┐        ┌─────────────────────┐
│ JSON exports │      │ 9 checks compare the │  any   │ AI connects related │
│   or a live  │ ───> │ data against limits  │ ────>  │ problems, ranks them │
│   cluster    │      │ from the tenant YAML │ breach │ & suggests fixes     │
└──────────────┘      └──────────────────────┘        └─────────────────────┘
                              │ no breaches
                              └────> "all green" (the AI is never called)
```

1. A **data source** provides cluster data — machines, services, metrics, events. The checks read a common interface, so the source is swappable.
2. **Nine checks** — plain, deterministic Python — compare that data against
   the customer's configured limits (CPU %, disk %, heartbeat window, ...).
   No AI is involved in detection, so results are fast and repeatable.
3. Only when checks find problems does the **AI analyst** run: it connects related problems, ranks severity, writes an incident summary, and suggests remediation. On a healthy cluster the AI is never called.

## The three data sources

Every tenant picks one via `data_source.type` in its YAML. All three return the **same record types**, so the checks, AI, and dashboard never change between them.

| `type` | Class | Reads from | Used for |
|---|---|---|---|
| `json` | `JsonDataSource` | hand-made `sample_*.json` in a folder | the built-in synthetic demo tenant + tests |
| `export` | `ClouderaExportSource` | real CM API exports saved as files (`hosts/`, `metrics/`) | a customer's **demo stage** — their real data, offline |
| `api` | `ClouderaApiSource` | the live Cloudera Manager REST API + SSH | a customer's **production stage** |

`json`/`export` are file-based (offline); `api` is live. Optional `USE_JSON` in
`.env` can force all tenants to files or to live for dev/testing.

## Folder guide

| Folder | What's in it |
|---|---|
| `config/` | Tenant YAML profiles, schema/loader, LLM + per-tenant secrets |
| `data/` | Sample data (`data/sample/`) + each export tenant's folder (`data/<id>/`) |
| `data_sources/` | The three data sources + shared parsing + day filtering |
| `cloudera/` | Talks to a real cluster: REST client, SSH commands, metric queries |
| `checks/` | The nine checks + `run_all_checks()` → `HealthReport` |
| `ai_analysis/` | The AI analyst (the only code that uses an LLM) |
| `api/` | FastAPI backend — exposes checks + AI over HTTP |
| `dashboard/` | Streamlit dashboard — a thin client that calls the API |
| `secrets/` | Per-customer credential files (`<tenant_id>.env`, gitignored) |
| `logs/` | Daily rotating logs, kept 7 days (gitignored) |
| `tests/` | Pytest suite — runs fully offline (fake HTTP, fake SSH) |

## Architecture: backend API + thin frontend

The backend logic (checks, AI, data sources) is exposed by a **FastAPI** service.
The **Streamlit dashboard is a thin client** that calls that API over HTTP — it holds no monitoring logic. A frontend team can build their own UI against the same endpoints.

```
  Streamlit dashboard ──HTTP──> FastAPI (api/) ──> checks / AI / data source
  (or any other frontend)
```

| Method + path | What it does |
|---|---|
| `GET /tenants` | list customers + their data source kind |
| `GET /tenants/{id}/dates` | days available for the date filter |
| `GET /tenants/{id}/report?as_of=YYYY-MM-DD` | run all checks, return the report |
| `GET /tenants/{id}/thresholds` | the tenant's current breach limits |
| `PUT /tenants/{id}/thresholds` | edit + persist the limits (validated, written to the YAML) |
| `POST /tenants/{id}/analyze?as_of=...` | start a background AI analysis → `job_id` |
| `GET /analysis/{job_id}` | poll the AI job until it's done |

Thresholds are editable from the dashboard sidebar; the change is validated by
the API and saved back to the tenant's YAML (comments preserved), so the next
monitoring run uses the new limits.

AI analysis is slow (minutes on CPU), so `analyze` returns immediately and the work runs in the background — the client polls `GET /analysis/{job_id}`.

## Running it

Two processes, in two terminals (both with the venv active):

```bash
# terminal 1 — the API backend  (run from the project root, not from api/)
uvicorn api.main:app --port 8000 --reload

# terminal 2 — the dashboard
streamlit run dashboard/app.py
```

Open http://localhost:8501 for the dashboard, or http://127.0.0.1:8000/docs for
the interactive API docs. The dashboard re-fetches the report automatically
(interval configurable in the sidebar), offers a **date picker** to view any day of history, and one-click AI analysis when problems are found.

## Configuration

- **`config/tenants/*.yaml`** — one file per customer: cluster name, thresholds,
  the customer's **stage** (`data_source.type`), and (for live) the *names* of
  the env vars holding credentials. Secret values never appear in YAML. For live
  tenants, `lookback_days` and `metrics_cache_ttl_sec` (in the `cloudera:` block)
  tune how much history to fetch and how long to cache it — per customer.
  Thresholds can also be edited from the dashboard sidebar — the API validates
  and writes the change straight back to this file (comments preserved).
- **`secrets/<tenant_id>.env`** (gitignored) — that customer's credential values,
  loaded automatically when their live source is built. One file per customer, so
  rotating or revoking one never touches another.
- **`.env`** (gitignored; copy `.env.example`) — global, non-customer settings:
  `OLLAMA_BASE_URL` / `OLLAMA_MODEL` (where the AI model is served), optional
  `USE_JSON` override, and `API_BASE_URL` (where the dashboard finds the API).

Adding a customer = one YAML in `config/tenants/` (+ one file in `secrets/` for live). No code changes.

## Customer onboarding flow

1. **Demo stage** — the customer provides real CM API exports as JSON. Drop them
   in `data/<id>/` — `hosts/` + `metrics/`, plus optional `services.json` and
   `events.json` (for the service-status and alerts checks) — create their YAML
   with `data_source: {type: export, data_dir: data/<id>}`, and demo offline.
   Any file that's missing simply makes its check report *no data* rather than a
   false result.
2. **Approval → live** — the customer provides a read-only Cloudera service
   account. Fill the `cloudera:` block in their YAML, put credentials in
   `secrets/<id>.env`, and flip `data_source.type` to `api`.

That one-line stage flip is the whole switch — checks, AI, and dashboard are identical in both stages. The exports and the live API are shaped the same, so only `data_sources/parse_cm_export.py` would ever need touching if a real response differs — the checks, AI, and dashboard stay untouched.

## Tests

```bash
python -m pytest tests/ -q
```

Everything runs offline (mocked HTTP + SSH). One test exercises the AI against a locally running Ollama model; it skips automatically when Ollama isn't up (and takes several minutes on CPU when it runs).

## The AI model

Detection never uses an LLM. The AI analyst runs on an open-source model served locally by [Ollama](https://ollama.com) (default: `qwen2.5:7b`) — no data leaves
the machine, which suits air-gapped deployments. Any OpenAI-compatible endpoint can be substituted via `.env`.
