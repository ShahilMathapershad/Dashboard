# Dashboard Cold-Start Overhaul — Design Spec

**Date:** 2026-04-26
**Status:** Approved for planning
**Goal:** Eliminate the Login → Dashboard cold-start delay (and intermittent infinite hang) by moving heavy work off the request path. Improve steady-state speed across the whole site.

---

## Problem

On Render's Starter plan (no dyno sleep), navigating from Login to Dashboard takes a long time and **occasionally hangs forever** until the user refreshes. The dashboard skeleton renders, but the chart loading bar never completes — the first link in the `Data → Model → Scenario` background-callback chain wedges.

**Root causes identified:**
- `pd.read_excel(live_url, …)` in `logic/data_fetcher.py:170` has **no timeout**.
- FRED `fred.get_series()` calls have no explicit timeout.
- Three sequentially chained `background=True` callbacks make any single hang catastrophic — the chain never advances.
- The dashboard does heavy work (FRED + World Bank fetch + model inference + scenario baseline) on every page load.
- `dashboard.py` is 2771 lines; `app.py` is 1619 lines; `model.py` is 1042 lines — large enough to make changes risky and slow.
- `assets/three-scenes.js` is 485KB and loaded on every page including the dashboard, where it isn't used.
- `assets/style.css` is 113KB, served uncompressed (Dash does not gzip by default).

## Architecture

Three independent workstreams that map cleanly to parallel agents:

```
┌──────────────────────────────────────────────────────────────────┐
│  WORKSTREAM A — Backend (cache-first read, async refresh)         │
│  • New Supabase table `predictions` holds pre-computed forecasts, │
│    scenario baseline, feature contributions, fit history.         │
│  • Page load = single fast SELECT. Never hits FRED/World Bank.    │
│  • A separate background callback opportunistically refreshes     │
│    `predictions` if stale (>24h or last-day-of-month).            │
│  • All external calls wrapped with hard timeouts (FRED 15s,       │
│    World Bank 20s, Supabase 10s) and try/except so a hung         │
│    upstream silently fails the refresh — never the read.          │
│  • Model object stays cached in memory for live Scenario slider.  │
└──────────────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────────┐
│  WORKSTREAM B — Frontend (skeleton-first, lazy tabs, file split)  │
│  • dashboard.py (2771 lines) split into per-tab modules.          │
│  • Tabs render skeleton + cached values instantly on mount.       │
│  • Model/Scenario tab content built only when tab is activated    │
│    (saves layout-build time on first paint).                      │
│  • Replace 3-step trigger chain with one async refresh callback   │
│    that patches stores when fresh data lands.                     │
└──────────────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────────┐
│  WORKSTREAM C — Assets (bundle split, critical CSS, compression)  │
│  • three-scenes.js (485KB) excluded from auto-include and        │
│    loaded only on landing/login via per-page index_string.       │
│  • style.css (114KB) split: critical inline, rest async.          │
│  • Add Flask-Compress (gzip) — Dash serves uncompressed today.    │
│  • Audit interactions.js for dead code; long-cache static assets. │
└──────────────────────────────────────────────────────────────────┘
```

**Sequencing.** A small "Phase 0" (define `predictions` table schema + cache-contract types) runs first because B depends on knowing what fields it'll read. Then A, B, C run in parallel as separate agents.

**Target metrics.** Login → Dashboard interactive < 1.5s on warm Render. Zero hangs (cap on request-path work eliminates the failure mode). Three.js gone from dashboard's critical path.

---

## File Structure

### Phase 0 — Cache Contract (sequential prerequisite)

| File | Action | Purpose |
|------|--------|---------|
| `logic/cache_contract.py` | new | TypedDicts defining `predictions` row shape: `forecasts_1m_3m_6m`, `feature_contributions`, `fit_history`, `scenario_baseline`, `metadata.computed_at`, `metadata.data_through`, `cache_contract_version`. The contract A produces and B reads. |
| `docs/superpowers/specs/predictions-table.sql` | new | DDL for the new Supabase `predictions` table. Single-row design: primary key `model_version` (text), all payload fields as JSONB columns. Refresh path uses `UPSERT ON CONFLICT (model_version) DO UPDATE`. No history retained — last write wins. |

### Workstream A — Backend

**Split `logic/data_fetcher.py` (562 lines) → `logic/data/` package:**

```
logic/data/
  fred_source.py        (~120 lines)  FRED API with timeout=15s
  worldbank_source.py   (~150 lines)  Gold price Excel scrape with timeout=20s
  static_inputs.py      (~60 lines)   Hardcoded SA inflation
  processing.py         (~150 lines)  Monthly resample + merge
  storage.py            (~150 lines)  Supabase upsert/delete + read with timeout=10s
  freshness.py          (~80 lines)   `should_update_from_api` logic
  __init__.py                          Orchestrator (re-exports legacy data_fetcher API)
```

**Split `logic/model.py` (1042 lines) → `logic/model/` package:**

```
logic/model/
  loading.py            (~80 lines)   joblib.load + in-memory caching
  features.py           (~250 lines)  11-feature engineering pipeline
  inference.py          (~150 lines)  Single-step predict
  forecasting.py        (~200 lines)  Multi-horizon iteration (1M/3M/6M)
  scenario.py           (~250 lines)  Scenario sensitivity analysis
  explain.py            (~150 lines)  Feature contribution computation
  __init__.py                          Re-exports public API + new
                                        `compute_full_predictions_payload()`
```

**New `logic/predictions_cache/` package:**

```
logic/predictions_cache/
  read.py               (~80 lines)   `read_cached() -> CachePayload | None`
  write.py              (~100 lines)  `write_payload(payload)`
  freshness.py          (~60 lines)   `is_stale(metadata) -> bool`
  refresh.py            (~150 lines)  Opportunistic refresh with parallel
                                        ThreadPoolExecutor + threading.Lock
  bootstrap.py          (~80 lines)   One-time eager init for empty cache
  __init__.py                          Re-exports public API
```

**Modify `logic/supabase_client.py`** to add timeout config and a `predictions` accessor.

### Workstream B — Frontend

**Split `pages/dashboard.py` (2771 lines) → per-tab packages:**

```
pages/dashboard.py            (~400 lines)  Page entry, tab shell, store hydration
pages/dashboard_tabs/
  data/
    layout.py                 (~200 lines)  Layout function only
    callbacks.py              (~250 lines)  Dash callbacks
    figures.py                (~200 lines)  Plotly figure builders
    __init__.py                              Re-exports `layout`, `register_callbacks`
  model/
    layout.py                 (~200 lines)
    callbacks.py              (~250 lines)
    figures.py                (~250 lines)
    __init__.py
  scenario/
    layout.py                 (~250 lines)
    callbacks.py              (~300 lines)
    figures.py                (~250 lines)
    __init__.py

pages/dashboard_components/
  skeleton.py                 (~80 lines)   Shared skeleton placeholders
  cards.py                    (~120 lines)  Reusable card/metric components
  figures_common.py           (~100 lines)  Shared color palettes, axis defaults
```

**Lazy tab activation.** Model/Scenario layouts are built only when the user first clicks the tab — driven by an `active_tab` callback whose output target is the tab's content container.

### Workstream C — Assets / Build

**Split `app.py` (1619 lines) → `app.py` (~80) + `core/` package:**

```
app.py                        (~80 lines)   Dash init, server export, register everything
core/
  stores.py                   (~150 lines)  The 20 dcc.Store definitions
  index_template.py           (~120 lines)  Custom index_string with critical CSS +
                                              conditional Three.js
  auth_callbacks.py           (~200 lines)  Login redirects, user-session handling
  theme_callbacks.py          (~150 lines)  Dark/light theme + clientside DOM sync
  chat_callbacks.py           (~250 lines)  Gemini AI chat panel
  cache_callbacks.py          (~150 lines)  Hydrate-from-cache + opportunistic refresh
  clientside.py               (~150 lines)  Clientside callback registrations
  routing.py                  (~120 lines)  Page routing + redirect logic
```

**Asset changes:**

| File | Action | Purpose |
|------|--------|---------|
| `assets/three-scenes.js` | keep in place | Stays in `assets/` for static serving, but excluded from Dash auto-include via `assets_ignore=r"three-scenes\.js"` in `Dash(...)` init. Loaded only on landing/login by adding the script tag conditionally in a per-page `index_string` (in `core/index_template.py`). |
| `assets/style.css` | split | `assets/critical.css` (above-the-fold, inlined) + `assets/style.css` (async) |
| `app.py` / `core/index_template.py` | modify | Per-page `index_string`: inline critical CSS, conditional Three.js script tag |
| `requirements.txt` | modify | Add `flask-compress==1.15` |
| `app.py` | modify | `Compress(server)` after Dash init for gzip |
| `assets/interactions.js` | audit + trim | Remove dead code, document remaining handlers |
| Cache headers | configure | Long-cache static assets via Dash `assets_external_path` or Flask response hooks |

### Parallel-Agent Boundaries

Each agent owns one boundary; they coordinate only via the cache contract from Phase 0.

- **Agent 1:** Phase 0 — define `cache_contract.py`, `predictions` table DDL, run migration.
- **Agent 2:** `logic/data/` package (split `data_fetcher.py` + add timeouts).
- **Agent 3:** `logic/model/` package (split `model.py` + add `compute_full_predictions_payload`).
- **Agent 4:** `logic/predictions_cache/` package + wire refresh.
- **Agent 5:** `core/` package (split `app.py`).
- **Agent 6:** `pages/dashboard_tabs/data/` (extract Data tab).
- **Agent 7:** `pages/dashboard_tabs/model/` (extract Model tab).
- **Agent 8:** `pages/dashboard_tabs/scenario/` (extract Scenario tab).
- **Agent 9:** `assets/` (Three.js bundle isolation, critical CSS split).
- **Agent 10:** Compression + cache headers (`flask-compress` + Dash assets config).

Agents 2–4 depend on Agent 1's contract. Agents 6–8 depend on Agents 2–4's public APIs being stable. 5, 9, 10 are independent.

---

## Data Flow

### Flow 1 — Page Load (the cold-start fix)

```
User clicks "Sign in"
  └─► auth_callbacks: validate against Supabase users → set user-session
      └─► redirect /dashboard
          └─► pages/dashboard.py layout() builds tab shell + skeleton placeholders
              ├─► HYDRATE CALLBACK fires (no background=True; runs in request thread)
              │     • SELECT * FROM predictions WHERE model_version = $current
              │     • ~100-200ms, returns full CachePayload (or None if cache empty)
              │     • Populates ~20 dcc.Stores (forecasts, contributions, fit history,
              │       scenario baseline, metadata)
              ├─► Tab render callbacks fire from store changes:
              │     • Data tab figures built client-side from cached time series
              │     • Active tab paints; inactive tabs lazy
              └─► REFRESH CHECK CALLBACK fires concurrently
                    • If metadata.computed_at < 24h old → no-op
                    • Else → kick off Flow 2 (async, doesn't block render)

Total time to interactive: ~200-400ms (target < 1.5s)
```

### Flow 2 — Background Refresh (opportunistic, async)

Triggered by a stale cache on page load, or a manual "refresh" button.

```python
# logic/predictions_cache/refresh.py
with concurrent.futures.ThreadPoolExecutor() as ex:
    fred_future = ex.submit(fred_source.fetch)         # internal timeout=15s
    wb_future   = ex.submit(worldbank_source.fetch)    # internal timeout=20s
    sa_data     = static_inputs.load()                 # instant

try:
    fred_df = fred_future.result(timeout=20)
    wb_df   = wb_future.result(timeout=25)
except (TimeoutError, RequestException):
    return RefreshResult(status="failed", keep_cached=True)

merged  = processing.merge(fred_df, wb_df, sa_data)
storage.upsert_data_table(merged)
payload = model.compute_full_predictions_payload(merged)
predictions_cache.write(payload)

return RefreshResult(status="success", payload=payload)
```

**This is the ONLY `background=True` callback in the new architecture.** No more 3-step trigger chain. The chain is replaced by one fire-and-forget async refresh whose failure is invisible.

The refresh callback's output triggers a "swap" callback in the page that re-hydrates `dcc.Store`s with fresh values. Plotly figures re-render in place. User sees a subtle "Updated <timestamp>" toast.

### Flow 3 — Live Scenario Interactivity (unchanged in spirit)

```
User drags slider on Scenario tab
  └─► scenario/callbacks.py debounced callback fires (~150ms throttle)
      └─► model/scenario.py.predict_scenario(slider_state)
            • Uses in-memory model (loaded once at app startup)
            • Reads scenario_baseline from store (no Supabase round-trip)
            • Computes delta vs baseline
            • Returns updated comparison cards + waterfall chart payload
      └─► Returns in 50-100ms (CPU-bound only, no network)
```

The model object stays in memory under `--preload` so scenario interactivity remains fast. The cache stores *pre-computed* predictions; live scenario what-ifs always run the model.

### Failure Modes

| Scenario | Behavior |
|----------|----------|
| FRED times out | Refresh aborts; cache untouched; user sees last-good data |
| World Bank scrape fails | Same — cache untouched |
| Supabase `predictions` SELECT fails | Hydrate returns `None`; dashboard renders skeleton + a "Connection issue, retrying…" toast; client-side retries every 5s |
| Empty `predictions` table (first deploy) | Eager refresh with a "Initializing data…" splash. One-time only. Mitigation: pre-seed via `python -m logic.predictions_cache.bootstrap` in deploy hook. |
| User on Scenario tab when refresh completes | Scenario baseline updates in-place; current slider deltas recomputed against new baseline |
| Refresh in flight when user navigates away | `concurrent.futures` cleans up; result dropped silently |
| Render restart mid-refresh | Refresh dies; no partial writes (single-row upsert is atomic); next page load re-detects staleness, re-fires |

**Key invariant: the read path never blocks on external services.** Hangs become structurally impossible on the user's critical path.

---

## Error Handling

### Layered Defense

Every external call has three lines of defense:

1. **Hard timeout** — bounded wait, never hangs.
2. **Try/except** — never propagates raw exceptions to caller.
3. **Cached fallback** — user always sees something usable.

| Source | Timeout | On failure |
|--------|---------|------------|
| FRED API (per series) | 15s | Skip refresh, log warning, keep cached |
| World Bank Excel scrape | 20s | Skip refresh, log warning, keep cached |
| Supabase reads | 10s | Hydrate returns `None`, page shows reconnect toast |
| Supabase writes (refresh upsert) | 30s | Refresh marked failed, cache stays at last-good |
| Gemini chat completion | 25s | Show "Couldn't reach assistant, try again" in chat panel |
| Model inference (in-memory) | n/a | Caught at boundary; scenario tab shows "Calculation failed" cell |

**No bare `except:`. No retry loops on the request path.** Retries happen only via the next opportunistic refresh on the next page load — this prevents thundering-herd on a flaky upstream.

### Concurrency Safety

- **In-memory model is read-only after load.** No mutex needed for predictions.
- **Refresh writes** to Supabase are atomic single-row upserts on `predictions` (keyed by `model_version`); concurrent refreshes are idempotent — last write wins.
- **A `threading.Lock` in `predictions_cache/refresh.py`** guards `refresh_async()` so a flood of dashboard hits doesn't fire parallel refreshes. First caller fetches; others see "refresh already in progress" and skip.
- **DiskCache stays** for the model object only (startup speedup). It is no longer used for the trigger chain.

### Observability

Single structured logger writing to stdout (Render captures it):

```python
# core/logging.py
log.info("cache.hydrate.start", user_id=...)
log.info("cache.hydrate.hit",   age_seconds=...)
log.info("cache.hydrate.miss",  reason="empty_table")
log.info("cache.refresh.start", trigger="stale|manual|empty")
log.info("cache.refresh.fetch.fred",       elapsed_ms=..., status="ok|timeout|error")
log.info("cache.refresh.fetch.worldbank",  elapsed_ms=..., status="ok|timeout|error")
log.info("cache.refresh.complete",         elapsed_ms=..., status="success|failed")
log.warn("cache.refresh.skipped", reason="lock_held")
log.error("cache.refresh.failed", error=..., trace=...)
```

Each line is a single JSON-ish dict. Grep `cache.refresh.fetch.fred status=timeout` in Render's log stream to immediately see if FRED is the recurring offender. **No new infra.**

### Edge Cases & Decisions

| Edge case | Decision |
|-----------|----------|
| Empty `predictions` on first deploy | Eager blocking refresh with "Setting up your dashboard, this takes ~30s…" splash. One-time only. Optional: pre-seed via Render deploy hook. |
| Stale cache > 7 days old | Still serve it, but show banner: *"Data last updated <relative time> ago — attempting refresh."* |
| `predictions` schema change | Schema-versioned via `cache_contract_version` field. Hydrate validates; if mismatch → treat as cache miss → trigger eager refresh with new schema. |
| Render restart mid-refresh | Refresh dies; single-row upsert is atomic so no partial writes; next page load re-detects staleness, re-fires. |
| Memory pressure during refresh (512MB cap) | Free intermediate DataFrames eagerly (`del`), use `pd.concat(copy=False)`, log `cache.refresh.memory.peak_mb`. Fallback (not shipped day-one): move refresh to a separate Render Cron Job. |
| User signed out mid-refresh | No effect — refresh runs server-side; result lands in Supabase regardless. |
| Three.js failing to load | Page still functional via plain CSS hero (Three scene is decorative, not load-bearing). |
| `flask-compress` breaks something | Single-line revert in `app.py`. Worth its own commit so it can be reverted alone. |
| Critical CSS extraction misses a rule | Fallback: full CSS still loads async; brief unstyled flash for non-critical elements only. Mitigation: only inline genuine above-the-fold rules. |

### Backward Compatibility

- **`predictions` table is additive.** Existing `data` table untouched.
- **`logic/data_fetcher.py` and `logic/model.py` keep their public APIs** via `__init__.py` re-exports. No callers in `pages/` need to change because of the package split alone.
- **Each agent's PR is independently mergeable and revertable.** Worst case: revert C (assets) without affecting A/B.

### Out of Scope (YAGNI)

- No new database (Supabase already handles caching).
- No Redis / message queue.
- No service worker / PWA.
- No SSR rewrite — staying with Dash.
- No moving inference to a separate worker (revisit if 512MB pressure becomes real).
- No custom CDN — Render's static asset serving is fine for our scale.

---

## Testing & Verification

There is no test framework or test files in this repository today. Adding pytest is **out of scope** for this overhaul. Instead: a measurement-driven verification strategy.

### Three Layers

1. **Lightweight smoke scripts** (per workstream) under `scripts/verify/`. Standalone Python that imports new modules and asserts behaviors. Run locally pre-deploy. Not pytest — `python scripts/verify/X.py` exits 0 on success.
2. **Browser timing measurements** (before/after). Chrome DevTools Performance tab: capture trace of login → dashboard. Numbers go into a results table.
3. **Render production smoke** (post-deploy). Hit dashboard 5x, watch logs for `cache.refresh.*`, confirm zero hangs in 30 minutes of normal use.

### Per-Workstream Verification

**Phase 0 — Cache contract:**
- `scripts/verify/contract.py` — instantiate `CachePayload` with mock data; assert all required fields present and serializable to JSON.
- Run `predictions-table.sql` against Supabase; assert SELECT returns no rows initially.

**Workstream A — Backend:**
- `scripts/verify/timeouts.py` — monkeypatch `requests.get` to sleep 60s; assert `fred_source.fetch()` raises within 16s, `worldbank_source.fetch()` raises within 21s. **The single most important test — proves hangs are gone.**
- `scripts/verify/refresh_idempotent.py` — call `refresh_async()` twice; assert second call returns "lock held, skipped" within 50ms.
- `scripts/verify/cache_roundtrip.py` — write `CachePayload`, read it back, assert equality.
- Manual: confirm fresh refresh produces predictions matching legacy code (compare 1M / 3M / 6M forecasts to ~6 decimal places).

**Workstream B — Frontend:**
- Manual smoke: log in, open dashboard, confirm each tab renders. Click each tab — assert layout builds (Model/Scenario lazy-built on first activation).
- Drag every Scenario slider — assert response < 200ms.
- DevTools: instrument layout function timing via `console.time` in clientside callbacks.
- Verify the 20 `dcc.Store`s hydrate (DevTools → Application → Session Storage).

**Workstream C — Assets:**
- Lighthouse on `/login` and `/dashboard`: record FCP, LCP, TTI, total payload.
- Confirm `three-scenes.js` (485KB) is **not** in the dashboard's network waterfall.
- `curl -H "Accept-Encoding: gzip" -I <render-url>/dashboard` → assert `Content-Encoding: gzip`.
- Visual check: critical CSS inlined → no FOUC on first paint.

### Acceptance Metrics

Capture **before** numbers on `main`, **after** numbers on the merged overhaul branch. Same Render env, warm dyno, median of 5 runs.

| Metric | After (acceptance threshold) |
|--------|------------------------------|
| Login → Dashboard interactive (Lighthouse TTI) | < 1500ms |
| Dashboard layout render (server-side log timing) | < 250ms |
| Hydrate callback (Supabase SELECT predictions) | < 300ms |
| Total JS payload on /dashboard | < 150KB (Three.js excluded) |
| Total CSS payload on /dashboard (gzipped) | < 15KB inline + async rest |
| Hangs observed in 30-min smoke | **0** |
| Tab switch latency (Data → Model → Scenario) | < 400ms first activation, < 50ms subsequent |
| Scenario slider response | < 200ms median |

If any "after" metric fails, the workstream that owns it doesn't merge until fixed.

### Risk-of-Regression Watchlist

Manually re-verify after each workstream deploys (no automated coverage):

1. Login still works.
2. Registration still creates Supabase rows.
3. Profile password change still works.
4. AI chat still streams Gemini responses.
5. Theme toggle (dark/light) still syncs to DOM.
6. All three dashboard tabs render with both empty and populated cache.
7. Data tab table toggle still works.
8. Scenario "save snapshot" / "compare snapshots" still works.

---

## Approval

- Architecture: approved
- File structure (with deeper decomposition): approved
- Data flow: approved
- Error handling: approved
- Testing & verification: approved

Next step: invoke `superpowers:writing-plans` to produce the detailed task-by-task implementation plan suitable for parallel-agent execution.
