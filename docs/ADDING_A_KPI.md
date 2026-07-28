# Adding a new KPI (a 10th check)

The product ships with **9 curated, code-defined KPIs** (the checks in `checks/`).
Admins can already control *which* of them a given user sees — but that's pure
visibility over a fixed set. Adding a **genuinely new** KPI (a new signal to
monitor) is a small, repeatable piece of development work released in a new
version — not a config change and not research.

This is the pattern to follow so any dev can add one consistently.

> **Why not a fully dynamic "admin invents a KPI" builder?** A KPI isn't just a
> label — it's *logic* (what data to read, what "breach" means). Simple
> `metric > threshold` KPIs (cpu/ram/disk) could in principle be form-authored,
> but the structural ones (host_health, service_status, hdfs_health, alerts,
> network) carry bespoke multi-signal logic that can't be expressed in a form
> without effectively building a rules DSL. And you can only ever monitor data
> the source already exposes. So the curated, code-defined approach below is the
> deliberate choice; see the git history / team notes for that discussion.

---

## The one rule that ties it together

Pick the **task name** once (a short snake_case id, e.g. `gc_pause`) and use that
exact string in every layer below. It is the key that links the check, the
thresholds, the AI framing, and the frontend card.

Do the steps in order: backend logic → AI framing → frontend → tests.

---

## Step 0 — Confirm the data exists *(gate — the only non-boilerplate step)*

A KPI can only be built on data the data source already provides. Check whether
the signal is already parsed in `data_sources/` (from the uploaded CM export
files and/or the live CM API — see `parse_cm_export.py` and the source's
`get_metrics()` / `get_services()` / etc.).

- **Already available** → continue to Step 1.
- **Not available** → add the parsing first (new metric query / parsed field in
  `data_sources/`). Everything from Step 1 on is pattern-following; this is the
  step that takes real thought.

---

## Step 1 — Threshold field *(only if the KPI is tunable)*

`config/schema.py` → add a validated field to `ThresholdsConfig`:

```python
gc_pause_ms: float = Field(default=200.0, ge=0)
```

The `ge` / `le` bounds are exactly what `PUT /tenants/{slug}/thresholds`
validates against, so set them sensibly (percentages use `ge=0, le=100`).

Skip this step for a status-only KPI (one with no numeric limit, like
`service_status`).

---

## Step 2 — The check itself

`checks/gc_pause.py` → write `check_gc_pause(source, tenant) -> CheckResult`,
following **`checks/cpu_percent.py`** as the template:

1. read the threshold from `tenant.thresholds.gc_pause_ms`,
2. read data via the source (`source.get_metrics([...])`, `get_services()`, …),
3. build a `CheckEvidence` (the per-entity rows the UI shows),
4. return a `CheckResult(task="gc_pause", status=..., metric=..., threshold=...,
   breached_entities=..., detail=..., evidence=...)` with `status` one of
   `OK` / `BREACH` / `NO_DATA` (use `NO_DATA` when the source can't provide the
   input yet — never a false `OK`).

Then register it in **`checks/run_all_checks.py` → `ALL_CHECKS`**. Its position
in that list sets its order on the dashboard.

---

## Step 3 — Refresh cadence

`backend/app/engine/bridge.py` → add an entry to `DEFAULT_REFRESH_RATES`:

```python
"gc_pause": 30,   # seconds; fast signals low, heavy/slow ones high
```

> **This single line also auto-registers the KPI in `ALL_KPI_TASKS`** (it's
> derived from `DEFAULT_REFRESH_RATES.keys()` in `engine/kpi_access.py`). That
> means per-user visibility, the `can_see_kpi` gate, and the refresh-settings UI
> all light up for the new KPI for free.

---

## Step 4 — Wire the threshold to the KPI *(only if Step 1 applied)*

`backend/app/engine/kpi_access.py` → add to `THRESHOLD_FIELD_TASK`:

```python
"gc_pause_ms": "gc_pause",
```

This is what makes the threshold appear (and be editable) only for users who can
see the KPI, and hidden for those who can't.

---

## Step 5 — AI framing *(so the analysis is actually good)*

The AI never decides what's broken, but it does explain the breach — give it the
context to do that well:

- **`backend/app/ai/kpi_agents.py`** — add:
  - `_TASK_BRIEF["gc_pause"]` — what this check means and what "wrong" looks like.
  - `_TASK_LABEL["gc_pause"]` — the human label used in the agent's instructions.
- **`backend/app/ai/dependencies.py`** — add dependency edges if this KPI affects
  or is affected by others. Drives the "may be affected by X" chips on related
  cards and the incident-coordinator correlation. *(Optional but recommended.)*
- **`backend/app/ai/models.py`** — add a `severity_floor` rule if the raw data
  implies a minimum severity (the governance guardrail — the model can raise
  severity but never go below this). *(Optional.)*
- **`knowledge/`** — add best-practice / known-issue guidance for the new task so
  the agent has grounded, citable remediation instead of guessing.

---

## Step 6 — Frontend presentation

- **`frontend/src/lib/monitoringApi.js` → `CHECK_META`** — add an entry:

  ```js
  gc_pause: { label: 'GC Pause', icon: '…', description: '…' },
  ```

  This is the **main required frontend change**. The KPI card, the admin access
  checkboxes, the refresh-settings list, and the incident view all render off the
  task list the backend returns, so they pick up the new KPI once it has
  `CHECK_META`.

- **`frontend/src/components/monitoring/ThresholdsModal.jsx` → `NUM_FIELDS`** —
  *if tunable*, add `{ key: 'gc_pause_ms', label: 'GC pause limit (ms)' }` so the
  threshold renders and can be edited. (The modal already filters to fields the
  backend returns, so no other change is needed.)

---

## Step 7 — Tests

- Add a check test next to the existing `checks/` tests covering **BREACH**,
  **OK**, and **NO_DATA**.
- If the KPI has a threshold, extend the KPI-access tests
  (`backend/tests/test_kpi_access.py`) so its visibility + threshold gating is
  covered like the other nine (granted → visible/editable; not granted → hidden
  and 403 on edit).

---

## What you do NOT have to touch (already generic)

These are all driven by the task lists and the report payload, so they pick up a
new KPI automatically once Steps 2–3 register it:

- per-user KPI visibility and the admin access checkboxes,
- the thresholds `GET`/`PUT` access gating,
- the KPI refresh-rate settings,
- the dashboard health ring, issue counts, and per-card polling,
- the incident (all-breaches) view.

---

## Scope summary

| KPI shape | Files touched |
|---|---|
| Tunable `metric > threshold` (like cpu/disk) | ~7 (schema, check, run_all_checks, bridge, kpi_access, kpi_agents, CHECK_META) + thresholds modal + tests |
| Status-only (like service_status) | fewer — skip the threshold steps (1, 4, and the modal) |
| Brand-new signal not yet parsed | the above **plus** data-source/parser work (Step 0) |

No architectural changes are required in any case — it's additive, and
predictable enough to scope and estimate per KPI.
